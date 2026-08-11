#!/usr/bin/env python3
"""Calibrate ReorderCapabilityV2 relation algebra on P5K and real cedar."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import torch


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5l_torchvision_relation_algebra_protocol.json"
SCHEMA = ROOT / "benchmark" / "final_v1" / "reorder_capability_v2.schema.json"
P5K_MANIFEST = ROOT / "benchmark" / "final_v1" / "p5k_torchvision_pair_manifest.json"
P5K_RESULT = ROOT / "outputs" / "autocontract_p5k_torchvision_real_pairs.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
EXPECTED_SUPPORTED = {
    "tv00_identity_resize",
    "tv01_normalize_center_crop",
    "tv02_normalize_random_hflip",
    "tv03_normalize_random_vflip",
    "tv04_normalize_random_crop",
    "tv05_grayscale3_random_hflip",
    "tv16_identity_normalize",
    "tv17_identity_random_crop",
    "tv19_grayscale3_center_crop",
    "tv20_grayscale3_random_vflip",
}
EXPECTED_REMAINING_UNKNOWN = {
    "tv18_normalize_resize",
    "tv22_resize_random_hflip",
    "tv24_gaussian_blur_normalize",
    "tv27_to_uint8_resize",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def input_domain() -> dict[str, Any]:
    return {
        "type": "torch.Tensor",
        "layout": "CHW",
        "channels": 3,
        "dtype": "torch.float32",
        "value_min": 0.0,
        "value_max": 1.0,
        "height_min": 31,
        "height_max": 35,
        "width_min": 37,
        "width_max": 43,
        "device": "cpu",
        "allow_nonfinite": False,
    }


def make_bundle(compiler: Any, v0: Any, v2cap: Any, ordered_ids: list[str], operators: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    items = []
    for operator_id in ordered_ids:
        operator = operators[operator_id]
        source_sha = v2cap.operator_source_sha256(operator)
        contract_sha = v0.canonical_sha256({"type": f"{type(operator).__module__}.{type(operator).__qualname__}", "repr": repr(operator)})
        items.append(compiler.make_operator(operator_id, source_index_sha256=source_sha, contract_sha256=contract_sha))
    pipeline = compiler.make_pipeline(items, operation="adjacent_reorder")
    pipeline["input_schema_sha256"] = v0.canonical_sha256(domain)
    return compiler.compile_constraints(pipeline)


def ordered_path(graph: dict[int, set[int]], source: int = 3) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        if len(graph[current]) != 1:
            raise ValueError("fixture graph is not linear")
        current = next(iter(graph[current]))
        path.append(current)
    return path


def tensor_digest(value: torch.Tensor) -> str:
    payload = {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "bytes_sha256": hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def execute_cedar(cedar_root: Path, bundle: dict[str, Any], ordered_ids: list[str], operators: dict[str, Any], samples: list[torch.Tensor], *, optimize: bool) -> dict[str, Any]:
    from cedar.compose import Feature, OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    recipe = bundle["backends"]["cedar"]["operators"]

    class RealTransformFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, operator_id in zip(recipe, ordered_ids, strict=True):
                pipe = MapperPipe(pipe, operators[operator_id], tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
            return pipe

    feature = RealTransformFeature()
    feature.apply(IterSource([sample.clone() for sample in samples]))
    candidates = calculate_reorderings(feature.logical_pipes, feature.logical_adj_list)
    if optimize:
        options = OptimizerOptions(enable_prefetch=False, available_local_cpus=1, enable_offload=False, enable_reorder=True, enable_local_parallelism=False, enable_fusion=False, enable_caching=False, disable_physical_opt=True, num_samples=100)
        plan = feature.optimize(options, str(cedar_root / "tests/data/test_profile_stats.yml"))
        path = ordered_path(plan.graph)
        iterator = feature.load_from_plan(CedarContext(), plan)
    else:
        path = ordered_path(feature.logical_adj_list)
        iterator = feature.load(CedarContext(), prefetch=False)
    outputs = [sample.data for sample in iterator]
    return {
        "candidate_count": len(candidates),
        "path": path,
        "fix": [item["fix"] for item in recipe],
        "output_digests": [tensor_digest(value) for value in outputs],
        "output_shapes": [list(value.shape) for value in outputs],
        "outputs": outputs,
    }


def public_case(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "outputs"}


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manifest = json.loads(P5K_MANIFEST.read_text(encoding="utf-8"))
    p5k = json.loads(P5K_RESULT.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    frozen = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in protocol["frozen_inputs"]}
    append_check(checks, "p5k_and_v1_predecessors_are_frozen", frozen == protocol["frozen_inputs"], frozen)
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "cedar_checkout_is_fixed_and_clean", head == UPSTREAM_COMMIT and status == "", {"head": head, "status": status or "clean"})

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_feasibility as feasibility
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_p5k_torchvision_real_pairs as p5k_runner
    import autocontract_reorder_capability_v0 as v0
    import autocontract_reorder_capability_v2 as v2cap

    append_check(checks, "runtime_and_tree_match_protocol", v2cap.framework_record() == protocol["runtime"], v2cap.framework_record())
    domain = input_domain()
    specs = p5k_runner.current_specs(feasibility)
    instances = {name: spec.factory() for name, spec in specs.items()}
    p5k_by_id = {item["pair_id"]: item for item in p5k["pairs"]}
    coverage_rows: list[dict[str, Any]] = []
    receipts_by_id: dict[str, dict[str, Any]] = {}
    for pair in manifest["pairs"]:
        pair_id, left_id, right_id = pair["pair_id"], pair["left"], pair["right"]
        reason = None
        receipt = None
        try:
            pair_ops = {left_id: instances[left_id], right_id: instances[right_id]}
            base = make_bundle(compiler, v0, v2cap, [left_id, right_id], pair_ops, domain)
            receipt = v2cap.make_verified_receipt(base, left_id, right_id, pair_ops, domain)
            jsonschema.validate(instance=receipt, schema=schema)
            receipts_by_id[pair_id] = receipt
            status_name = "supported"
            lemma = receipt["proof_artifact"]["lemma"]["lemma_id"]
        except (v2cap.ReorderCapabilityV2Error, jsonschema.ValidationError) as exc:
            status_name, lemma, reason = "unknown", None, str(exc)
        counterexample = bool(p5k_by_id[pair_id]["global"]["counterexample_found"])
        coverage_rows.append({"pair_id": pair_id, "left": left_id, "right": right_id, "p5k_counterexample": counterexample, "v2_status": status_name, "lemma": lemma, "reason": reason})

    supported_ids = {row["pair_id"] for row in coverage_rows if row["v2_status"] == "supported"}
    conflict_ids = {row["pair_id"] for row in coverage_rows if row["v2_status"] == "supported" and row["p5k_counterexample"]}
    remaining_unknown = {row["pair_id"] for row in coverage_rows if row["v2_status"] == "unknown" and not row["p5k_counterexample"]}
    append_check(checks, "exactly_ten_p5k_unknown_pairs_gain_verified_coverage", supported_ids == EXPECTED_SUPPORTED and len(supported_ids) == 10, sorted(supported_ids))
    append_check(checks, "no_observed_counterexample_pair_is_supported", not conflict_ids, sorted(conflict_ids))
    append_check(checks, "four_excluded_no_counterexample_pairs_remain_unknown", remaining_unknown == EXPECTED_REMAINING_UNKNOWN, sorted(remaining_unknown))
    append_check(checks, "all_emitted_receipts_validate_against_v2_schema", len(receipts_by_id) == 10)

    test_pair_id = "tv01_normalize_center_crop"
    test_pair = next(item for item in manifest["pairs"] if item["pair_id"] == test_pair_id)
    test_ops = {name: instances[name] for name in (test_pair["left"], test_pair["right"])}
    test_base = make_bundle(compiler, v0, v2cap, [test_pair["left"], test_pair["right"]], test_ops, domain)
    good = v2cap.make_verified_receipt(test_base, test_pair["left"], test_pair["right"], test_ops, domain)
    attacks: list[dict[str, Any]] = []

    def attack(name: str, receipts: list[dict[str, Any]], base: dict[str, Any] | None = None, ops: dict[str, Any] | None = None, attack_domain: dict[str, Any] | None = None, revoked: set[str] | None = None) -> None:
        result = v2cap.compile_reorder_safe_strict(base or test_base, receipts, ops or test_ops, attack_domain or domain, revoked_verifier_closure_sha256=revoked)
        attacks.append({"name": name, "passed": not result["proof_verification"]["verified_pairs"] and all(item["fix"] for item in result["backends"]["cedar"]["operators"]), "audit": result["proof_verification"]["receipt_audit"]})

    artifact_tamper = copy.deepcopy(good)
    artifact_tamper["proof_artifact"]["lemma"]["lemma_id"] = "identity_composition_v0"
    artifact_tamper["proof_sha256"] = v0.canonical_sha256(artifact_tamper["proof_artifact"])
    attack("lemma_artifact_rehashed", [artifact_tamper])
    version_tamper = copy.deepcopy(good); version_tamper["verifier"]["version"] = "9.9.9"
    attack("verifier_version", [version_tamper])
    closure_tamper = copy.deepcopy(good); closure_tamper["verifier"]["closure_sha256"] = "f" * 64
    attack("verifier_closure", [closure_tamper])
    drift_base = copy.deepcopy(test_base); drift_base["operators"][0]["source_index_sha256"] = "e" * 64; drift_base["backends"]["cedar"]["operators"][0]["source_index_sha256"] = "e" * 64
    attack("source_binding_drift", [good], base=drift_base)
    drift_domain = dict(domain); drift_domain["height_min"] = 20
    attack("input_domain_drift", [good], attack_domain=drift_domain)
    drift_ops = dict(test_ops); drift_ops["normalize"] = copy.deepcopy(test_ops["normalize"]); drift_ops["normalize"].mean[0] = 0.99
    attack("operator_config_drift", [good], ops=drift_ops)
    attack("duplicate_receipt", [good, copy.deepcopy(good)])
    attack("revoked_verifier", [good], revoked={good["verifier"]["closure_sha256"]})
    append_check(checks, "all_binding_artifact_duplicate_and_revocation_attacks_fail_closed", all(item["passed"] for item in attacks), attacks)

    chain_ids = ["identity", "normalize", "center_crop"]
    chain_ops = {name: instances[name] for name in chain_ids}
    chain_base = make_bundle(compiler, v0, v2cap, chain_ids, chain_ops, domain)
    chain_receipts = [v2cap.make_verified_receipt(chain_base, chain_ids[left], chain_ids[right], chain_ops, domain) for left in range(3) for right in range(left + 1, 3)]
    fail_closed = v2cap.compile_reorder_safe_strict(chain_base, [], chain_ops, domain)
    admitted = v2cap.compile_reorder_safe_strict(chain_base, chain_receipts, chain_ops, domain)
    samples = [feasibility.make_probe_image(31 + index, 37 + index, index) for index in range(5)]
    baseline = execute_cedar(cedar_root, fail_closed, chain_ids, chain_ops, samples, optimize=False)
    optimized = execute_cedar(cedar_root, admitted, chain_ids, chain_ops, samples, optimize=True)
    append_check(checks, "real_relation_receipts_restore_six_cedar_candidates", baseline["candidate_count"] == 1 and optimized["candidate_count"] == 6 and optimized["path"] != baseline["path"], {"baseline": public_case(baseline), "optimized": public_case(optimized)})
    max_delta = max(float(torch.max(torch.abs(left - right)).item()) for left, right in zip(baseline["outputs"], optimized["outputs"], strict=True))
    append_check(checks, "real_reordered_plan_preserves_output", max_delta <= 2e-5 and baseline["output_shapes"] == optimized["output_shapes"], {"max_abs_delta": max_delta, "baseline_digests": baseline["output_digests"], "optimized_digests": optimized["output_digests"]})
    append_check(checks, "output_contains_no_optimizer_decision_fields", not v0.contains_decision_fields(admitted))

    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5l-torchvision-relation-algebra-result.v0",
        "status": "pass" if passed == len(checks) else "fail",
        "passed": passed,
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "schema_sha256": file_sha256(SCHEMA),
        "module_sha256": file_sha256(ROOT / "experiments" / "autocontract_reorder_capability_v2.py"),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "p5k_pairs": len(coverage_rows),
        "p5k_unknown_pairs": 14,
        "verified_supported_pairs": len(supported_ids),
        "verified_unknown_coverage": len(supported_ids) / 14,
        "overall_strict_coverage": len(supported_ids) / len(coverage_rows),
        "counterexample_conflicts": len(conflict_ids),
        "coverage": coverage_rows,
        "attacks": attacks,
        "cedar": {"baseline": public_case(baseline), "optimized": public_case(optimized), "max_abs_delta": max_delta},
        "checks": checks,
        "claim_boundary": protocol["claim_boundary"],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedar-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.cedar_root.resolve(), args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
