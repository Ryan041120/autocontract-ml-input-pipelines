"""Zero-source TorchGeo adapter and sealed H7D evaluator."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7
import autocontract_h7d_effect_v4 as v4


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7d_corpus" / "torchgeo_repo"
PROTOCOL = OUT / "autocontract_h7d_protocol.json"
FREEZE = OUT / "autocontract_h7d_freeze.json"

KORNIA_BASES = frozenset(
    (
        "IntensityAugmentationBase2D",
        "GeometricAugmentationBase2D",
        "GeometricAugmentationBase3D",
    )
)
TORCHGEO_RULES = (
    "Kornia augmentation bases provide forward-to-hook execution semantics",
    "apply_transform/generate_parameters/compute_transformation form the execution hooks",
    "built-in TorchGeo transforms operate on a fixed Tensor record scope",
    "Kornia random parameter generation is a resolved Torch RNG delegation",
    "repeat_interleave or gamma-expanded batch shapes denote one-to-many output cardinality",
)


@dataclass(frozen=True)
class Unit:
    name: str
    path: str
    expected: str
    reason: str


def read_source(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def execution_hooks(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    names = {"apply_transform", "generate_parameters", "compute_transformation"}
    return [
        method
        for cls in v2.class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in names
    ]


def construction_hooks(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    return [
        method
        for cls in v2.class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in v2.CONSTRUCTION_METHODS
    ]


def infer_torchgeo(unit: Unit, source: str) -> v4.AnalysisV4:
    tree = ast.parse(source)
    classes, _ = v2.top_definitions(tree)
    if unit.name not in classes:
        return v4.AnalysisV4(
            "unknown", v4.EffectV4(None, "unknown", "none"),
            ("sealed_source_unit_missing:" + unit.name,), "torchgeo", (),
        )
    root = classes[unit.name]
    bases = {
        name
        for cls in v2.class_chain(root, classes)
        for name in v2.base_names(cls)
        if name not in classes
    }
    if not (bases & KORNIA_BASES):
        return v4.AnalysisV4(
            "unknown", v4.EffectV4(None, "unknown", "none"),
            ("unresolved_kornia_base:" + "+".join(sorted(bases)),), "torchgeo", (),
        )
    execution = execution_hooks(root, classes)
    construction = construction_hooks(root, classes)
    if not execution:
        return v4.AnalysisV4(
            "unknown", v4.EffectV4(None, "fixed_fields", "none"),
            ("missing_kornia_execution_hook",), "torchgeo", (),
        )
    rendered = "\n".join(ast.unparse(node) for node in execution)
    expands_batch = (
        "repeat_interleave" in rendered
        or ("batch_shape" in rendered and "gamma" in rendered and "*" in rendered)
    )
    construction_reads, construction_writes = v2.external_effects(construction)
    execution_reads, execution_writes = v2.external_effects(execution)
    stateful, state_attrs = h7.execution_state_writes(execution)
    base_effect = h7.EffectV3(
        construction_reads,
        construction_writes,
        v2.self_state_write(construction),
        v2.rng_sources(construction),
        frozenset(("tensor",)),
        frozenset(("tensor",)),
        execution_reads,
        execution_writes,
        v2.rng_sources(execution) | frozenset(("torch",)),
        False,
        "fixed",
        False,
        "one",
        "many" if expands_batch else "one",
        "preserve",
        stateful,
    )
    effect = v4.EffectV4(base_effect, "fixed_fields", "none")
    return v4.AnalysisV4(
        "resolved", effect, (), "torchgeo",
        (
            "entrypoint:Kornia.forward->hooks",
            "record_scope:fixed_fields:tensor",
            f"cardinality:one->{'many' if expands_batch else 'one'}",
        ) + tuple(f"execution_state:{attr}" for attr in state_attrs),
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    checks = {
        "effect_v4_sha256": digest(Path(v4.__file__)),
        "effect_v4_manifest_sha256": digest(OUT / "autocontract_h7d_v4_manifest.json"),
        "torchgeo_adapter_sha256": digest(Path(__file__)),
        "protocol_sha256": digest(PROTOCOL),
    }
    for name, actual in checks.items():
        if freeze[name] != actual:
            raise RuntimeError(f"H7D freeze violation for {name}: {actual}")
    return freeze


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    freeze = verify_freeze()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    units = [Unit(**item) for item in protocol["sealed_units"]]
    rows: list[dict[str, object]] = []
    for unit in units:
        result = infer_torchgeo(unit, read_source(unit.path))
        reasons = v4.validator_v4(result)
        decision = "reject" if reasons else "admit"
        reason_match = (
            not reasons if unit.reason == "none"
            else any(unit.reason in reason for reason in reasons)
        )
        rows.append(
            {
                "unit": unit.name,
                "expected_decision": unit.expected,
                "actual_decision": decision,
                "decision_correct": decision == unit.expected,
                "expected_reason": unit.reason,
                "reason_match": reason_match,
                "status": result.status,
                "record_scope": result.effect.record_scope,
                "delegation_kind": result.effect.delegation_kind,
                "validator_reasons": ";".join(reasons) or "none",
                "evidence": ";".join(result.evidence) or "none",
            }
        )
    safe = [row for row in rows if row["expected_decision"] == "admit"]
    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    false_accepts = sum(row["actual_decision"] == "admit" for row in unsafe)
    safe_recall = sum(row["actual_decision"] == "admit" for row in safe) / len(safe)
    reason_accuracy = sum(row["reason_match"] is True for row in rows) / len(rows)
    resolved_coverage = sum(row["status"] == "resolved" for row in rows) / len(rows)
    thresholds = protocol["thresholds"]
    passed = (
        false_accepts <= thresholds["known_unsafe_false_accepts"]
        and safe_recall >= thresholds["safe_recall"]
        and reason_accuracy >= thresholds["reason_category_accuracy"]
        and resolved_coverage >= thresholds["resolved_coverage"]
    )
    summary = {
        "protocol": protocol["protocol"],
        "units": len(rows),
        "decisions_correct": sum(row["decision_correct"] is True for row in rows),
        "known_unsafe_false_accepts": false_accepts,
        "supported_safe_recall": safe_recall,
        "reason_category_accuracy": reason_accuracy,
        "resolved_coverage": resolved_coverage,
        "h7d_blind_gate_pass": passed,
        "effect_v4_sha256": freeze["effect_v4_sha256"],
        "torchgeo_adapter_sha256": freeze["torchgeo_adapter_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
    }
    write_csv(OUT / "autocontract_h7d_torchgeo.csv", rows)
    write_csv(OUT / "autocontract_h7d_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7D zero-source TorchGeo holdout",
            "",
            f"Decisions correct: {summary['decisions_correct']}/{len(rows)}.",
            f"Known-unsafe false accepts: {false_accepts}.",
            f"Safe recall: {safe_recall:.1%}.",
            f"Reason-category accuracy: {reason_accuracy:.1%}.",
            f"Resolved coverage: {resolved_coverage:.1%}.",
            f"H7D blind gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "| Unit | Status | Scope | Expected | Actual | Reason |",
            "|---|---|---|---|---|---|",
            *[
                f"| `{row['unit']}` | {row['status']} | {row['record_scope']} | "
                f"{row['expected_decision']} | {row['actual_decision']} | {row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "The adapter was written from public interface documentation before repository source blobs were opened.",
            "",
        ]
    )
    (OUT / "autocontract_h7d_torchgeo.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
