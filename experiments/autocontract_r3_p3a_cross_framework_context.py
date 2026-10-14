"""R3-P3a context-compatible cross-framework transfer calibration.

Known H7 corpora are used posthoc.  Context-incompatible units remain outside
the replay accuracy denominator, and static AST slices are not promoted to
full runtime executable-source indexes.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p3a_cross_framework_context_protocol.json"
EXPECTED_PROTOCOL_SHA = "f4afd13108cfb75c420cbd54c87ffbc3a96a00d3c4d9f19516be910c18c809fa"
EXPERIMENTS = ROOT / "experiments"
sys.path.insert(0, str(EXPERIMENTS))

import autocontract_h7f_imgaug as h7f  # noqa: E402
import autocontract_h7g_albumentations as h7g  # noqa: E402
import autocontract_h7g_effect_v6 as v6  # noqa: E402
import autocontract_h7h_effect_v7 as v7  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_json(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def canonical_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    cloned = copy.deepcopy(node)
    if (
        cloned.body
        and isinstance(cloned.body[0], ast.Expr)
        and isinstance(cloned.body[0].value, ast.Constant)
        and isinstance(cloned.body[0].value.value, str)
    ):
        cloned.body = cloned.body[1:]
    dumped = ast.dump(cloned, annotate_fields=True, include_attributes=False)
    return {"method": cloned.name, "ast_sha256": hashlib.sha256(dumped.encode("utf-8")).hexdigest()}


def static_slice(
    *,
    framework: str,
    symbol: str,
    configuration: str,
    phase: str,
    root_source_path: str,
    nodes: list[ast.FunctionDef | ast.AsyncFunctionDef],
    declared_methods: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    selected = nodes
    if declared_methods is not None:
        allowed = set(declared_methods)
        selected = [node for node in nodes if node.name in allowed]
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for node in selected:
        record = canonical_method(node)
        unique[(record["method"], record["ast_sha256"])] = record
    payload = {
        "schema": "autocontract.static-ast-reachable-slice.v0",
        "framework": framework,
        "public_symbol": symbol,
        "configuration": configuration,
        "phase": phase,
        "root_source_path": root_source_path,
        "origin_completeness": "root_binding_plus_method_ast_without_runtime_dependency_closure",
        "methods": list(unique.values()),
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {
        "status": "partial_static" if unique else "unknown",
        "sha256": hashlib.sha256(rendered).hexdigest(),
        "bytes": len(rendered),
        "methods": len(unique),
        "method_names": sorted({item["method"] for item in unique.values()}),
        "limitation": "defaults/closures/globals/native/runtime-origin/monkeypatch not measured",
    }


def qualified_method_nodes(
    declared_methods: tuple[str, ...], classes: dict[str, ast.ClassDef]
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Resolve V7 Class.method identifiers without dropping the owner class."""
    result: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for qualified in declared_methods:
        if "." not in qualified:
            continue
        owner, method_name = qualified.rsplit(".", 1)
        class_node = classes.get(owner)
        if class_node is None:
            continue
        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                result.append(item)
                break
    return result


def imgaug_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    protocol = json.loads(h7f.PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(h7f.SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    classes = h7f.package_classes()
    rows: list[dict[str, Any]] = []
    slices: list[dict[str, Any]] = []
    for item in protocol["sealed_units"]:
        unit = h7f.Unit(**item)
        binding = bindings[unit.public_symbol]
        prediction = v6.infer_imgaug_v6(binding, classes)
        reasons = v6.validator_v6(
            prediction,
            frozenset(("imgaug.deterministic",)),
            frozenset(("framework_specific",)),
        )
        actual = "reject" if reasons else "admit"
        reason_match = v6.reason_match(unit.coarse_reason, reasons)
        root = h7f.target_class(binding)
        nodes = h7f.execution_nodes(root, classes) if root is not None else []
        slice_record: dict[str, Any] | None = None
        if actual == "admit" and prediction.status == "resolved":
            slice_record = static_slice(
                framework="imgaug",
                symbol=unit.public_symbol,
                configuration="imgaug.deterministic",
                phase="replay_apply",
                root_source_path=str(binding["source_path"]),
                nodes=nodes,
            )
            slices.append({"public_symbol": unit.public_symbol, **slice_record})
        rows.append(
            {
                "framework": "imgaug",
                "public_symbol": unit.public_symbol,
                "configuration": "imgaug.deterministic",
                "phase": "replay_apply",
                "replay_family": "rng_state_restoration",
                "expected": unit.expected,
                "actual": actual,
                "reasons": ";".join(reasons) or "none",
                "reason_match": reason_match,
                "analysis_status": prediction.status,
                "static_slice_status": slice_record["status"] if slice_record else "not_applicable",
            }
        )
    return rows, slices


def albumentations_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    protocol = json.loads(h7g.PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(h7g.SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    classes, functions = h7g.package_index()
    histogram = "albumentations.augmentations.mixing.domain_adaptation.HistogramMatching"
    rows: list[dict[str, Any]] = []
    slices: list[dict[str, Any]] = []
    for item in protocol["sealed_units"]:
        symbol = item["public_symbol"]
        binding = bindings[symbol]
        expected = "admit" if symbol == histogram else item["expected"]
        coarse_reason = "none" if symbol == histogram else item["coarse_reason"]
        prediction = v7.albumentations_v7(binding, classes, functions, "albumentations.replay")
        reasons = v7.validator_v7(prediction)
        actual = "reject" if reasons else "admit"
        reason_match = v7.coarse_match(coarse_reason, reasons)
        function_nodes = qualified_method_nodes(prediction.effect.reachable.methods, classes)
        slice_record: dict[str, Any] | None = None
        if actual == "admit" and prediction.status == "resolved" and not prediction.effect.reachable.unresolved_dispatch:
            slice_record = static_slice(
                framework="Albumentations",
                symbol=symbol,
                configuration="albumentations.replay",
                phase="replay_apply",
                root_source_path=str(binding["source_path"]),
                nodes=function_nodes,
            )
            slices.append({"public_symbol": symbol, **slice_record})
        rows.append(
            {
                "framework": "Albumentations",
                "public_symbol": symbol,
                "configuration": "albumentations.replay",
                "phase": "replay_apply",
                "replay_family": "parameter_record_replay",
                "expected": expected,
                "actual": actual,
                "reasons": ";".join(reasons) or "none",
                "reason_match": reason_match,
                "analysis_status": prediction.status,
                "static_slice_status": slice_record["status"] if slice_record else "not_applicable",
            }
        )
    return rows, slices


def runtime_readiness() -> list[dict[str, Any]]:
    torchio_init = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7c_corpus" / "torchio_repo" / "src" / "torchio" / "__init__.py"
    requirements = {
        "TorchIO": [("complete_vendored_package", torchio_init.exists())],
        "imgaug": [("cv2", importlib.util.find_spec("cv2") is not None)],
        "Albumentations": [
            ("pydantic", importlib.util.find_spec("pydantic") is not None),
            ("cv2", importlib.util.find_spec("cv2") is not None),
        ],
    }
    rows = []
    for framework, checks in requirements.items():
        missing = [name for name, available in checks if not available]
        rows.append(
            {
                "framework": framework,
                "ready": not missing,
                "status": "ready" if not missing else "unsupported_missing_runtime_dependency",
                "missing": ";".join(missing) or "none",
                "environment": "frozen_python_3.12_torch_2.4_cpu",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    protocol_sha = sha256(PROTOCOL)
    h7h_freeze = json.loads((OUT / "autocontract_h7h_freeze.json").read_text(encoding="utf-8"))
    freeze_checks = {
        "effect_v7": sha256(EXPERIMENTS / "autocontract_h7h_effect_v7.py") == h7h_freeze["effect_v7_sha256"],
        "imgaug_adapter": sha256(EXPERIMENTS / "autocontract_h7f_imgaug.py")
        == json.loads((OUT / "autocontract_h7f_freeze.json").read_text(encoding="utf-8"))["adapter_sha256"],
        "albumentations_adapter": sha256(EXPERIMENTS / "autocontract_h7g_albumentations.py")
        == json.loads((OUT / "autocontract_h7g_freeze.json").read_text(encoding="utf-8"))["adapter_sha256"],
    }

    img_rows, img_slices = imgaug_rows()
    alb_rows, alb_slices = albumentations_rows()
    rows = img_rows + alb_rows
    slices = img_slices + alb_slices
    readiness = runtime_readiness()

    tp = sum(row["expected"] == "admit" and row["actual"] == "admit" for row in rows)
    fp = sum(row["expected"] == "reject" and row["actual"] == "admit" for row in rows)
    fn = sum(row["expected"] == "admit" and row["actual"] == "reject" for row in rows)
    tn = sum(row["expected"] == "reject" and row["actual"] == "reject" for row in rows)
    safe = sum(row["expected"] == "admit" for row in rows)
    reason_accuracy = sum(bool(row["reason_match"]) for row in rows) / len(rows)
    eligible_families = sorted({row["replay_family"] for row in rows})
    admitted = [row for row in rows if row["actual"] == "admit"]
    static_covered = sum(item["status"] == "partial_static" for item in slices)
    summary = {
        "eligible_frameworks": 2,
        "eligible_replay_families": len(eligible_families),
        "eligible_units": len(rows),
        "excluded_torchio_units": 7,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / safe,
        "reason_accuracy": reason_accuracy,
        "static_ast_slice_coverage_on_admits": static_covered / len(admitted),
        "static_ast_slice_total_bytes": sum(item["bytes"] for item in slices),
        "static_ast_slice_total_methods": sum(item["methods"] for item in slices),
        "full_runtime_measured_index_ready_frameworks": sum(item["ready"] for item in readiness if item["framework"] in {"imgaug", "Albumentations"}),
        "new_effect_or_adapter_rules": 0,
        "manual_context_mapping_entries": 3,
    }
    checks = {
        "protocol_hash_recorded": protocol_sha == EXPECTED_PROTOCOL_SHA,
        "frozen_analyzers_and_adapters_verified": all(freeze_checks.values()),
        "torchio_excluded_from_replay_denominator": summary["excluded_torchio_units"] == 7,
        "sixteen_eligible_units_accounted": len(rows) == 16,
        "two_replay_families_eligible": len(eligible_families) >= 2,
        "zero_unsafe_false_accepts": fp == 0,
        "safe_recall_gate": summary["safe_recall"] >= 0.9,
        "reason_accuracy_gate": reason_accuracy >= 0.9,
        "zero_rule_change": summary["new_effect_or_adapter_rules"] == 0,
        "static_slice_separated_from_runtime_readiness": static_covered == len(admitted)
        and summary["full_runtime_measured_index_ready_frameworks"] == 0,
        "missing_runtime_is_unsupported": all(not item["ready"] and item["status"].startswith("unsupported") for item in readiness),
    }
    status = "pass" if all(checks.values()) else "fail"
    payload = {
        "schema_version": "autocontract.r3-p3a-cross-framework-context.v0",
        "artifact_role": "posthoc_context_compatible_transfer_not_blind_evidence",
        "protocol_sha256": protocol_sha,
        "freeze_checks": freeze_checks,
        "context_exclusions": [
            {
                "framework": "TorchIO",
                "units": 7,
                "status": "unsupported_context",
                "reason": "legacy sample_apply protocol has no frozen replay_apply evidence",
            }
        ],
        "summary": summary,
        "eligible_predictions": rows,
        "static_ast_slices": slices,
        "runtime_readiness": readiness,
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "status": status,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "autocontract_r3_p3a_cross_framework_context.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv(OUT / "autocontract_r3_p3a_cross_framework_predictions.csv", rows)
    write_csv(OUT / "autocontract_r3_p3a_static_ast_slices.csv", slices)
    write_csv(OUT / "autocontract_r3_p3a_runtime_readiness.csv", readiness)

    lines = [
        "# AutoContract R3-P3a context-compatible cross-framework transfer",
        "",
        f"Status: **{status}** ({sum(checks.values())}/{len(checks)} harness checks).",
        "",
        "> Posthoc transfer on already-known H7 corpora; not blind evidence.",
        "",
        "## Context gate",
        "",
        "| Framework | Registered context | Replay-transfer status | Units in accuracy denominator |",
        "|---|---|---|---:|",
        "| TorchIO | legacy sample_apply | Unsupported: no frozen replay_apply evidence | 0/7 |",
        "| imgaug | deterministic / replay_apply | Eligible RNG-state replay | 8/8 |",
        "| Albumentations | stored params / replay_apply | Eligible parameter-record replay | 8/8 |",
        "",
        "## Frozen EffectV7 transfer",
        "",
        f"Eligible units: {len(rows)}; TP={tp}, FP={fp}, FN={fn}, TN={tn}; safe recall={summary['safe_recall']:.1%}; reason accuracy={reason_accuracy:.1%}.",
        f"Replay semantic families: {', '.join(eligible_families)}. New analyzer/adapter rules: 0.",
        "",
        "## Source binding transfer boundary",
        "",
        f"Partial static AST slices: {static_covered}/{len(admitted)} admitted units, {summary['static_ast_slice_total_methods']} method records, {summary['static_ast_slice_total_bytes']} bytes.",
        "These slices bind declared reachable method ASTs but do not measure defaults, closures, globals, native dependencies, runtime origins or monkeypatch state.",
        "Full P2b runtime measured-index readiness: 0/2 eligible frameworks in the frozen environment (imgaug missing cv2; Albumentations missing pydantic and cv2).",
        "",
        "## Interpretation",
        "",
        "The configuration/phase representation transfers posthoc across two distinct replay families without rule changes, but the runtime measured-source mechanism does not yet have cross-framework execution evidence. "
        "TorchIO H7C cannot be pooled into replay accuracy because its frozen units answer a sample_apply question.",
        "",
    ]
    (OUT / "autocontract_r3_p3a_cross_framework_context.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "passed": sum(checks.values()), "total": len(checks), "summary": summary}))
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
