"""H7C TorchIO adapter calibration and frozen-holdout analyzer.

Only the calibration subset may be used before this file and its framework
rules are frozen.  Holdout evaluation is performed by a separate driver.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7c_corpus" / "torchio_repo"
PROTOCOL = OUT / "autocontract_h7c_protocol.json"

TORCHIO_RULES = (
    "Transform.__call__ dispatches to subclass apply_transform",
    "RandomTransform and Transform probability gates consume Torch RNG",
    "Subject is one logical sample and Transform preserves subject lineage",
    "SpatialTransform targets a coupled subject.spatial_images group",
    "IntensityTransform targets a subject.intensity_images group",
    "child containers, user callables, and external-framework wrappers remain Unknown",
)


@dataclass(frozen=True)
class UnitSpec:
    name: str
    path: str
    expected: str
    reason: str


def load_protocol() -> dict[str, object]:
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def read_source(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def parse_bundle(paths: list[str]) -> tuple[dict[str, ast.ClassDef], dict[str, ast.FunctionDef]]:
    classes: dict[str, ast.ClassDef] = {}
    functions: dict[str, ast.FunctionDef] = {}
    for path in paths:
        tree = ast.parse(read_source(path))
        local_classes, local_functions = v2.top_definitions(tree)
        classes.update(local_classes)
        functions.update(local_functions)
    return classes, functions


def construction_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    return [
        method
        for cls in v2.class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in v2.CONSTRUCTION_METHODS
    ]


def has_external_framework_import(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "monai" or alias.name.startswith("monai.") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "monai" or node.module.startswith("monai."):
                return True
    return False


def has_user_callable_boundary(root: ast.ClassDef) -> bool:
    init = v2.method_map(root).get("__init__")
    if init is None:
        return False
    tokens = v2.corpus_v1.identifier_tokens([init])
    return bool(tokens & {"function", "callable", "lambda", "fn"})


def is_child_container(nodes: list[ast.AST]) -> bool:
    rendered = "\n".join(ast.unparse(node) for node in nodes)
    return (
        "self.transforms" in rendered
        or "self.transforms_dict" in rendered
    ) and "transform(subject)" in rendered


def infer_torchio(name: str, target_path: str, common_paths: list[str]) -> h7.AnalysisResult:
    paths = list(dict.fromkeys(common_paths + [target_path]))
    classes, _ = parse_bundle(paths)
    if name not in classes:
        return h7.AnalysisResult(
            "unknown", None, ("sealed_source_unit_missing:" + name,), "torchio", ()
        )
    root = classes[name]
    execution = h7.execution_nodes(root, classes, "__call__")
    construction = construction_nodes(root, classes)
    target_source = read_source(target_path)

    if not execution:
        return h7.AnalysisResult(
            "unknown", None, ("adapter_entrypoint_missing:Transform.__call__",), "torchio", ()
        )
    if is_child_container(execution):
        return h7.AnalysisResult(
            "unknown", None, ("unresolved_child_effect",), "torchio",
            ("entrypoint:Transform.__call__->apply_transform",),
        )
    if has_user_callable_boundary(root):
        return h7.AnalysisResult(
            "unknown", None, ("unresolved_user_callable",), "torchio",
            ("entrypoint:Transform.__call__->apply_transform",),
        )
    if has_external_framework_import(target_source):
        return h7.AnalysisResult(
            "unknown", None, ("external_framework_delegation",), "torchio",
            ("entrypoint:Transform.__call__->apply_transform",),
        )

    chain_names = {cls.name for cls in v2.class_chain(root, classes)}
    if "SpatialTransform" in chain_names:
        targets = frozenset(("subject.spatial_images",))
        coupled = True
        scope = "typed-subrecord:spatial"
    elif "IntensityTransform" in chain_names:
        targets = frozenset(("subject.intensity_images",))
        coupled = False
        scope = "typed-subrecord:intensity"
    else:
        targets = frozenset(("subject",))
        coupled = True
        scope = "whole-record"

    construction_reads, construction_writes = v2.external_effects(construction)
    execution_reads, execution_writes = v2.external_effects(execution)
    stateful, state_attrs = h7.execution_state_writes(execution)
    effect = h7.EffectV3(
        construction_reads,
        construction_writes,
        v2.self_state_write(construction),
        v2.rng_sources(construction),
        targets,
        targets,
        execution_reads,
        execution_writes,
        v2.rng_sources(execution) | frozenset(("torch",)),
        False,
        "fixed",
        coupled,
        "one",
        "one",
        "preserve",
        stateful,
    )
    return h7.AnalysisResult(
        "resolved", effect, (), "torchio",
        ("entrypoint:Transform.__call__->apply_transform", f"record_scope:{scope}", "rng:torch")
        + tuple(f"execution_state:{attr}" for attr in state_attrs),
    )


def generic_calibration_result(spec: UnitSpec) -> h7.AnalysisResult:
    source = read_source(spec.path)
    probe = v2.V2Unit("torchio_calibration", "class", spec.name, v2.fx())
    return h7.generic_analyze(probe, source)


def row_for(spec: UnitSpec, result: h7.AnalysisResult, mode: str) -> dict[str, object]:
    reasons = h7.validator_reasons(result)
    decision = "reject" if reasons else "admit"
    expected_reason_match = (
        not reasons if spec.reason == "none"
        else any(spec.reason in reason for reason in reasons)
    )
    return {
        "mode": mode,
        "unit": spec.name,
        "expected_decision": spec.expected,
        "actual_decision": decision,
        "decision_correct": decision == spec.expected,
        "expected_reason": spec.reason,
        "reason_match": expected_reason_match,
        "analysis_status": result.status,
        "analysis_reasons": ";".join(result.reasons) or "none",
        "validator_reasons": ";".join(reasons) or "none",
        "evidence": ";".join(result.evidence) or "none",
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration", action="store_true")
    args = parser.parse_args()
    if not args.calibration:
        raise SystemExit("Use --calibration; sealed holdout has a separate driver")

    protocol = load_protocol()
    common = protocol["adapter_calibration"]["common_files"]
    specs = [UnitSpec(**item) for item in protocol["adapter_calibration"]["units"]]
    rows: list[dict[str, object]] = []
    for spec in specs:
        rows.append(row_for(spec, generic_calibration_result(spec), "generic"))
        result = infer_torchio(spec.name, spec.path, common)
        rows.append(row_for(spec, result, "torchio_adapter"))
    write_csv(OUT / "autocontract_h7c_calibration.csv", rows)

    generic = [row for row in rows if row["mode"] == "generic"]
    adapted = [row for row in rows if row["mode"] == "torchio_adapter"]
    generic_safe_recall = sum(
        row["actual_decision"] == "admit" for row in generic if row["expected_decision"] == "admit"
    ) / sum(row["expected_decision"] == "admit" for row in generic)
    adapted_correct = sum(row["decision_correct"] is True for row in adapted)
    report = "\n".join(
        [
            "# AutoContract H7C TorchIO adapter calibration",
            "",
            f"Generic unknown-reject safe recall: {generic_safe_recall:.1%}.",
            f"Adapter calibration decisions: {adapted_correct}/{len(adapted)} correct.",
            "",
            "| Unit | Generic | Adapter | Adapter reason |",
            "|---|---|---|---|",
            *[
                f"| `{spec.name}` | {next(row['actual_decision'] for row in generic if row['unit'] == spec.name)} | "
                f"{next(row['actual_decision'] for row in adapted if row['unit'] == spec.name)} | "
                f"{next(row['validator_reasons'] for row in adapted if row['unit'] == spec.name)} |"
                for spec in specs
            ],
            "",
            "Framework rules are structural and are listed in the frozen adapter manifest.",
            "",
        ]
    )
    (OUT / "autocontract_h7c_calibration.md").write_text(report, encoding="utf-8")
    manifest = {
        "framework": "torchio",
        "release": protocol["repository"]["release"],
        "commit_sha": protocol["repository"]["commit_sha"],
        "rules": TORCHIO_RULES,
        "calibration_units": [spec.name for spec in specs],
    }
    (OUT / "autocontract_h7c_adapter_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(report)
    if adapted_correct != len(adapted):
        raise RuntimeError("TorchIO adapter calibration failed")


if __name__ == "__main__":
    main()
