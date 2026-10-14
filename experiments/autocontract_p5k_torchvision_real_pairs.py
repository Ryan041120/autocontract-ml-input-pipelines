#!/usr/bin/env python3
"""Audit real torchvision reorder pairs without treating finite tests as proof."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import random
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
import torchvision
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5k_torchvision_real_pair_protocol.json"
MANIFEST = ROOT / "benchmark" / "final_v1" / "p5k_torchvision_pair_manifest.json"
OUT_CSV = ROOT / "outputs" / "autocontract_p5k_torchvision_pairs.csv"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def python_tree_sha256(root: Path) -> tuple[int, str]:
    files = sorted(root.rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return len(files), digest.hexdigest()


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def current_specs(feasibility: Any) -> dict[str, Any]:
    specs = feasibility.operators()
    legacy = specs["to_uint8"]
    specs["to_uint8"] = dataclasses.replace(
        legacy,
        factory=lambda: v2.ToDtype(torch.uint8),
    )
    return specs


def execute_chain(
    names: tuple[str, str],
    image: torch.Tensor,
    seed: int,
    specs: dict[str, Any],
    rng_mode: str,
) -> tuple[str, Any]:
    try:
        random.seed(seed)
        np.random.seed(seed % (2**32 - 1))
        torch.manual_seed(seed)
        value = image.clone()
        for name in names:
            if rng_mode == "operator_keyed":
                operator_key = zlib.crc32(name.encode("utf-8"))
                keyed_seed = (seed * 1_000_003 + operator_key) % (2**31 - 1)
                random.seed(keyed_seed)
                np.random.seed(keyed_seed % (2**32 - 1))
                torch.manual_seed(keyed_seed)
            value = specs[name].factory()(value)
        return "output", value
    except Exception as exc:
        return "exception", {"type": type(exc).__name__, "message": str(exc)}


def compare_outcomes(left: tuple[str, Any], right: tuple[str, Any], feasibility: Any) -> tuple[bool, str]:
    if left[0] != right[0]:
        return False, f"definedness:{left[0]}!={right[0]}"
    if left[0] == "exception":
        equal = left[1] == right[1]
        return equal, "same_exception" if equal else f"exception:{left[1]}!={right[1]}"
    return feasibility.outputs_equal(left[1], right[1])


def probe_pair(pair: dict[str, Any], specs: dict[str, Any], feasibility: Any, trials: int, rng_mode: str) -> dict[str, Any]:
    for trial in range(trials):
        image = feasibility.make_probe_image(31 + trial % 5, 37 + (2 * trial) % 7, trial)
        seed = 10_007 + 97 * trial
        original = execute_chain((pair["left"], pair["right"]), image, seed, specs, rng_mode)
        swapped = execute_chain((pair["right"], pair["left"]), image, seed, specs, rng_mode)
        equal, reason = compare_outcomes(original, swapped, feasibility)
        if not equal:
            return {
                "counterexample_found": True,
                "trials_run": trial + 1,
                "reason": reason,
                "seed": seed,
                "input_sha256": hashlib.sha256(image.numpy().tobytes()).hexdigest(),
                "original_kind": original[0],
                "swapped_kind": swapped[0],
            }
    return {
        "counterexample_found": False,
        "trials_run": trials,
        "reason": "no_counterexample_found",
        "seed": None,
        "input_sha256": None,
        "original_kind": "output_or_equal_exception",
        "swapped_kind": "output_or_equal_exception",
    }


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_top = {"schema_version", "status", "date", "framework", "operation_context", "input_domain", "comparison", "contamination", "pairs"}
    if set(manifest) != required_top:
        errors.append("top_keys")
    pairs = manifest.get("pairs", [])
    ids = [item.get("pair_id") for item in pairs if isinstance(item, dict)]
    if len(pairs) != 28 or len(ids) != len(set(ids)):
        errors.append("pair_count_or_duplicate")
    required_pair = {"pair_id", "left", "right", "origin", "legacy_global_label"}
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict) or set(pair) != required_pair:
            errors.append(f"pair_{index}_shape")
            continue
        if pair["left"] == pair["right"]:
            errors.append(f"pair_{index}_self")
        if pair["origin"] not in {"legacy", "p5k_extension"}:
            errors.append(f"pair_{index}_origin")
        if pair["legacy_global_label"] not in {"commutes", "noncommutes", None}:
            errors.append(f"pair_{index}_label")
    return errors


def write_csv(rows: list[dict[str, Any]]) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    frozen = {
        path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None
        for path in protocol["frozen_inputs"]
    }
    append_check(checks, "frozen_predecessors_unchanged", frozen == protocol["frozen_inputs"], frozen)
    manifest_errors = validate_manifest(manifest)
    append_check(checks, "candidate_manifest_is_complete_and_explicitly_contaminated", not manifest_errors and manifest["contamination"]["eligible_for_final_blind"] is False, manifest_errors)

    v2_root = Path(torchvision.__file__).resolve().parent / "transforms" / "v2"
    file_count, tree_digest = python_tree_sha256(v2_root)
    runtime = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "torchvision_v2_python_files": file_count,
        "torchvision_v2_python_tree_sha256": tree_digest,
    }
    append_check(checks, "runtime_matches_frozen_torchvision_source_tree", runtime == protocol["runtime"], runtime)

    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_feasibility as feasibility
    import autocontract_reorder_capability_v1 as v1
    import autocontract_r3_source_index_v1 as source_index_v1

    legacy_drift = None
    try:
        feasibility.operators()["to_uint8"].factory()
    except Exception as exc:
        legacy_drift = {"type": type(exc).__name__, "message": str(exc)}
    append_check(
        checks,
        "legacy_todtype_constructor_drift_is_reproduced",
        legacy_drift is not None and legacy_drift["type"] == "TypeError" and "scale" in legacy_drift["message"],
        legacy_drift,
    )

    specs = current_specs(feasibility)
    names = sorted({pair[side] for pair in manifest["pairs"] for side in ("left", "right")})
    construct_errors: dict[str, str] = {}
    instances: dict[str, Callable[..., Any]] = {}
    for name in names:
        try:
            instances[name] = specs[name].factory()
        except Exception as exc:
            construct_errors[name] = f"{type(exc).__name__}:{exc}"
    append_check(checks, "current_version_statements_construct_all_operators", not construct_errors and len(instances) == len(names), construct_errors)

    declared_slots = ("forward", "_transform", "_get_params")
    source_rows = []
    for name, instance in instances.items():
        index = source_index_v1.portable_operator_index(instance, callable_names=declared_slots)
        nonvacuous_status = "supported" if index["status"] == "supported" and index["entries"] else "unknown"
        source_rows.append({
            "operator": name,
            "type": f"{type(instance).__module__}.{type(instance).__qualname__}",
            "raw_status": index["status"],
            "entry_count": len(index["entries"]),
            "consumer_status": nonvacuous_status,
            "sha256": index["sha256"],
        })
    real_source = [row for row in source_rows if row["operator"] != "stateful_udf"]
    udf_source = next(row for row in source_rows if row["operator"] == "stateful_udf")
    append_check(checks, "all_torchvision_operators_have_nonvacuous_sourceindex_v1", len(real_source) == 12 and all(row["consumer_status"] == "supported" and row["entry_count"] >= 1 for row in real_source), real_source)
    append_check(checks, "empty_slot_udf_is_not_vacuously_accepted", udf_source["raw_status"] == "supported" and udf_source["entry_count"] == 0 and udf_source["consumer_status"] == "unknown", udf_source)

    static_operator_status: dict[str, dict[str, str]] = {}
    for name, instance in instances.items():
        try:
            v1.extract_affine(instance)
            static_operator_status[name] = {"status": "supported", "reason": "affine_extracted"}
        except v1.ReorderCapabilityV1Error as exc:
            static_operator_status[name] = {"status": "unknown", "reason": str(exc)}
    static_supported_pairs = [
        pair["pair_id"] for pair in manifest["pairs"]
        if static_operator_status[pair["left"]]["status"] == "supported"
        and static_operator_status[pair["right"]]["status"] == "supported"
    ]
    append_check(checks, "restricted_affine_has_zero_real_pair_coverage", not static_supported_pairs, {"supported_pairs": static_supported_pairs, "operator_reasons": static_operator_status})

    trials = int(protocol["probe_budget"]["trials_per_pair_per_rng_context"])
    pair_rows: list[dict[str, Any]] = []
    pair_details: list[dict[str, Any]] = []
    for pair in manifest["pairs"]:
        global_result = probe_pair(pair, specs, feasibility, trials, "global")
        keyed_result = probe_pair(pair, specs, feasibility, trials, "operator_keyed")
        strict_status = "unknown"
        global_evidence = "noncommutes_counterexample" if global_result["counterexample_found"] else "unknown_no_counterexample"
        keyed_evidence = "noncommutes_counterexample" if keyed_result["counterexample_found"] else "unknown_no_counterexample"
        pair_rows.append({
            "pair_id": pair["pair_id"],
            "left": pair["left"],
            "right": pair["right"],
            "origin": pair["origin"],
            "legacy_global_label": pair["legacy_global_label"] or "",
            "global_evidence": global_evidence,
            "global_trials": global_result["trials_run"],
            "global_reason": global_result["reason"],
            "keyed_evidence": keyed_evidence,
            "keyed_trials": keyed_result["trials_run"],
            "keyed_reason": keyed_result["reason"],
            "strict_v1_status": strict_status,
        })
        pair_details.append({**pair, "global": global_result, "operator_keyed": keyed_result, "strict_v1_status": strict_status})

    legacy = [row for row in pair_rows if row["origin"] == "legacy"]
    legacy_agreement = [
        row for row in legacy
        if (row["legacy_global_label"] == "noncommutes") == (row["global_evidence"] == "noncommutes_counterexample")
    ]
    legacy_unsafe = [row for row in legacy if row["legacy_global_label"] == "noncommutes"]
    legacy_safe = [row for row in legacy if row["legacy_global_label"] == "commutes"]
    append_check(checks, "legacy_global_diagnostics_reproduce_16_of_16", len(legacy_agreement) == 16 and all(row["global_evidence"] == "noncommutes_counterexample" for row in legacy_unsafe) and all(row["global_evidence"] == "unknown_no_counterexample" for row in legacy_safe), {"agreement": len(legacy_agreement), "unsafe_witnessed": sum(row["global_evidence"] == "noncommutes_counterexample" for row in legacy_unsafe), "safe_without_counterexample": sum(row["global_evidence"] == "unknown_no_counterexample" for row in legacy_safe)})
    append_check(checks, "bounded_negative_results_never_mint_supported", all(row["strict_v1_status"] == "unknown" for row in pair_rows), Counter(row["global_evidence"] for row in pair_rows))
    rng_contrasts = [row["pair_id"] for row in pair_rows if row["global_evidence"] != row["keyed_evidence"]]
    append_check(checks, "rng_context_changes_at_least_one_pair_decision", bool(rng_contrasts), rng_contrasts)

    write_csv(pair_rows)
    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5k-torchvision-real-pair-result.v0",
        "status": "pass" if passed == len(checks) else "fail",
        "passed": passed,
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "manifest_sha256": file_sha256(MANIFEST),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "runtime": runtime,
        "candidate_pairs": len(pair_rows),
        "legacy_pairs": len(legacy),
        "new_calibration_pairs": len(pair_rows) - len(legacy),
        "strict_supported_pairs": 0,
        "global_counterexamples": sum(row["global_evidence"] == "noncommutes_counterexample" for row in pair_rows),
        "global_unknown_no_counterexample": sum(row["global_evidence"] == "unknown_no_counterexample" for row in pair_rows),
        "operator_keyed_counterexamples": sum(row["keyed_evidence"] == "noncommutes_counterexample" for row in pair_rows),
        "operator_keyed_unknown_no_counterexample": sum(row["keyed_evidence"] == "unknown_no_counterexample" for row in pair_rows),
        "rng_context_contrast_pairs": rng_contrasts,
        "source_index": source_rows,
        "checks": checks,
        "pairs": pair_details,
        "claim_boundary": protocol["claim_boundary"],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
