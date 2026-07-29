"""EffectV5 imgaug adapter, calibration, sealing, and one-shot H7F run.

The calibration symbols are intentionally disjoint from the sealed H7F
symbols.  ``--seal`` resolves only public symbol origins and hashes sources;
it does not run the effect analyzer on the formal units.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7
import autocontract_h7d_effect_v4 as v4
import autocontract_h7f_effect_v5 as v5
from autocontract_symbol_origin import SymbolOriginSealer, binding_record


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = (
    ROOT
    / ".research"
    / "semantics_safe_reconfiguration"
    / "h7f_corpus"
    / "imgaug_repo"
)
PROTOCOL = OUT / "autocontract_h7f_protocol.json"
SYMBOLS = OUT / "autocontract_h7f_symbol_manifest.json"
ADAPTER_MANIFEST = OUT / "autocontract_h7f_adapter_manifest.json"
FREEZE = OUT / "autocontract_h7f_freeze.json"
CALIBRATION_SUMMARY = OUT / "autocontract_h7f_imgaug_calibration_summary.csv"

CALIBRATION_UNITS = (
    ("imgaug.augmenters.meta.Identity", "admit", "none"),
    ("imgaug.augmenters.flip.Fliplr", "admit", "none"),
    ("imgaug.augmenters.arithmetic.Add", "admit", "none"),
    ("imgaug.augmenters.blur.GaussianBlur", "admit", "none"),
    ("imgaug.augmenters.meta.Sequential", "reject", "child"),
    ("imgaug.augmenters.meta.Sometimes", "reject", "child"),
    ("imgaug.augmenters.meta.Lambda", "reject", "user_callable"),
    (
        "imgaug.augmenters.debug.SaveDebugImageEveryNBatches",
        "reject",
        "external_effect",
    ),
)
EXECUTION_NAMES = frozenset(
    (
        "augment_batch_",
        "_augment_batch_",
        "_augment_images",
        "_augment_heatmaps",
        "_augment_segmentation_maps",
        "_augment_keypoints",
        "_augment_bounding_boxes",
        "_augment_polygons",
        "_augment_line_strings",
    )
)
EXTERNAL_PARAM_TOKENS = frozenset(("destination", "file", "folder", "path"))
CALLABLE_PARAM_TOKENS = frozenset(("callable", "func", "function", "fn"))
CLASSIFIED_REASONS = frozenset(
    ("unresolved_child_effect", "unresolved_user_callable", "execution_external_effect")
)
ADAPTER_RULES = (
    "Augmenter.augment_batch_ and the selected _augment_* override form the execution path",
    "the Batch object is one whole-record input and output",
    "random_state consumption denotes delegated replayable RNG state",
    "_maybe_deterministic_ctx restores RNG state when deterministic mode is active",
    "non-self augment_batch_ invocation denotes child-operator delegation",
    "constructor-supplied self callables invoked during execution denote user delegation",
    "constructor-supplied destination/path objects invoked during execution denote external effects",
    "direct execution writes to other self state remain cache/control/unknown and fail closed",
)


@dataclass(frozen=True)
class Unit:
    public_symbol: str
    expected: str
    coarse_reason: str


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_revision() -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().lower()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def public_binding(symbol: str) -> dict[str, object]:
    return binding_record(SymbolOriginSealer(REPO, "imgaug").resolve(symbol))


def package_classes() -> dict[str, ast.ClassDef]:
    candidates: dict[str, list[ast.ClassDef]] = {}
    for path in sorted((REPO / "imgaug").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes, _ = v2.top_definitions(tree)
        for name, cls in classes.items():
            candidates.setdefault(name, []).append(cls)
    return {name: items[0] for name, items in candidates.items() if len(items) == 1}


def target_class(binding: dict[str, object]) -> ast.ClassDef | None:
    source_path = binding.get("source_path")
    defining_name = binding.get("defining_name")
    if not source_path or not defining_name:
        return None
    path = REPO / str(source_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes, _ = v2.top_definitions(tree)
    return classes.get(str(defining_name))


def class_chain(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    merged = dict(classes)
    merged[root.name] = root
    return v2.class_chain(root, merged)


def construction_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    return [
        method
        for cls in class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in v2.CONSTRUCTION_METHODS
    ]


def execution_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    """Select the root-most implementation of each imgaug execution hook."""
    selected: dict[str, ast.FunctionDef] = {}
    for cls in class_chain(root, classes):
        for name, method in v2.method_map(cls).items():
            if name in EXECUTION_NAMES:
                selected.setdefault(name, method)
    return list(selected.values())


def operator_execution_nodes(
    root: ast.ClassDef, classes: dict[str, ast.ClassDef]
) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    for cls in class_chain(root, classes):
        if cls.name == "Augmenter":
            continue
        for name, method in v2.method_map(cls).items():
            if name in EXECUTION_NAMES:
                nodes.append(method)
    return nodes


def assigned_constructor_attrs(
    construction: list[ast.AST], parameter_kind: str
) -> set[str]:
    attrs: set[str] = set()
    for node in construction:
        parameters = {
            arg.arg
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        }
        for child in ast.walk(node):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            value = child.value
            if not isinstance(value, ast.Name) or value.id not in parameters:
                continue
            if parameter_kind == "callable" and not any(
                token in value.id.lower() for token in CALLABLE_PARAM_TOKENS
            ):
                continue
            if parameter_kind == "external" and not any(
                token in value.id.lower() for token in EXTERNAL_PARAM_TOKENS
            ):
                continue
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                chain = v2.corpus_v1.attribute_chain(target)
                if chain.startswith("self.") and chain.count(".") == 1:
                    attrs.add(chain.split(".", 1)[1])
    return attrs


def invoked_self_attrs(execution: list[ast.AST]) -> set[str]:
    attrs: set[str] = set()
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = v2.corpus_v1.attribute_chain(child.func)
            if chain.startswith("self."):
                attrs.add(chain.split(".", 2)[1])
    return attrs


def has_child_delegation(execution: list[ast.AST]) -> bool:
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr != "augment_batch_":
                continue
            receiver = ast.unparse(child.func.value)
            if receiver != "self":
                return True
    return False


def consumes_rng(execution: list[ast.AST]) -> bool:
    for node in execution:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == "random_state" and isinstance(child.ctx, ast.Load):
                return True
    return False


def imgaug_mode_guard() -> bool:
    path = REPO / "imgaug" / "augmenters" / "meta.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes, _ = v2.top_definitions(tree)
    context = classes.get("_maybe_deterministic_ctx")
    augmenter = classes.get("Augmenter")
    if context is None or augmenter is None:
        return False
    context_text = ast.unparse(context)
    entry = v2.method_map(augmenter).get("augment_batch_")
    entry_text = ast.unparse(entry) if entry is not None else ""
    return (
        "self.deterministic" in context_text
        and "self.random_state.state = self.old_state" in context_text
        and "_maybe_deterministic_ctx(self)" in entry_text
    )


def super_resolution_imgaug(
    root: ast.ClassDef, classes: dict[str, ast.ClassDef]
) -> v5.SuperResolution:
    chain = class_chain(root, classes)
    for index, cls in enumerate(chain):
        ancestors = chain[index + 1 :]
        for name, method in v2.method_map(cls).items():
            if name not in EXECUTION_NAMES:
                continue
            for child in ast.walk(method):
                if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                    continue
                receiver = child.func.value
                if not (
                    isinstance(receiver, ast.Call)
                    and isinstance(receiver.func, ast.Name)
                    and receiver.func.id == "super"
                ):
                    continue
                if not any(child.func.attr in v2.method_map(parent) for parent in ancestors):
                    return "partial"
    return "complete" if chain else "unknown"


def classify_direct_state(
    accesses: tuple[v5.StateAccess, ...]
) -> set[v5.StateRole]:
    roles: set[v5.StateRole] = set()
    for access in accesses:
        lowered = access.path.lower()
        if access.path == "self.random_state":
            continue
        if any(token in lowered for token in ("cache", "buffer", "history", "counter", "schedule")):
            roles.add("cache")
        else:
            roles.add("persistent_control")
    return roles


def analyze(binding: dict[str, object], classes: dict[str, ast.ClassDef]) -> v5.AnalysisV5:
    root = target_class(binding)
    empty_base = v4.EffectV4(None, "unknown", "none")
    if root is None:
        effect = v5.EffectV5(
            empty_base,
            (),
            frozenset(("unknown",)),
            frozenset(("unknown",)),
            False,
            "unknown",
        )
        return v5.AnalysisV5(
            "unknown", effect, ("sealed_definition_missing",), "imgaug-v5", ()
        )

    construction = construction_nodes(root, classes)
    execution = execution_nodes(root, classes)
    operator_execution = operator_execution_nodes(root, classes)
    callable_attrs = assigned_constructor_attrs(construction, "callable")
    invoked_attrs = invoked_self_attrs(execution)
    user_callable = bool(callable_attrs & invoked_attrs)
    child = has_child_delegation(operator_execution)
    if child:
        delegation: v4.DelegationKind = "child_operator"
    elif user_callable:
        delegation = "user_callable"
    else:
        delegation = "none"

    external_attrs = assigned_constructor_attrs(construction, "external")
    external = bool(external_attrs & invoked_attrs)
    construction_reads, construction_writes = v2.external_effects(construction)
    execution_reads, execution_writes = v2.external_effects(execution)
    if external:
        execution_writes = execution_writes | frozenset(("external_destination",))

    direct_accesses = v5.state_accesses(execution)
    rng = consumes_rng(operator_execution)
    guard = imgaug_mode_guard()
    accesses = list(direct_accesses)
    if rng and not any(item.path == "self.random_state" for item in accesses):
        accesses.append(v5.StateAccess("self.random_state", "container_mutation"))
    accesses_tuple = tuple(sorted(accesses, key=lambda item: (item.path, item.kind)))
    roles = classify_direct_state(accesses_tuple)
    modes: set[v5.RequiredMode] = set()
    if rng:
        if guard:
            roles.add("replayable")
            modes.add("framework_specific")
        else:
            roles.add("unknown")
            modes.add("unknown")

    base = h7.EffectV3(
        construction_reads,
        construction_writes,
        v2.self_state_write(construction),
        v2.rng_sources(construction),
        frozenset(("batch",)),
        frozenset(("batch",)),
        execution_reads,
        execution_writes,
        v2.rng_sources(execution),
        rng or delegation != "none",
        "fixed",
        False,
        "one",
        "one",
        "preserve",
        bool(accesses_tuple),
    )
    effect_v4 = v4.EffectV4(base, "whole_record", delegation)
    super_status = super_resolution_imgaug(root, classes)
    effect = v5.EffectV5(
        effect_v4,
        accesses_tuple,
        frozenset(roles),
        frozenset(modes),
        guard if rng else False,
        super_status,
    )
    reasons: list[str] = []
    if child:
        reasons.append("unresolved_child_effect")
    elif user_callable:
        reasons.append("unresolved_user_callable")
    if super_status != "complete":
        reasons.append("partial_super_resolution")
    evidence = (
        "entrypoint:Augmenter.augment_batch_->_augment_batch_",
        "record_scope:whole_record:Batch",
        f"delegation:{delegation}",
        f"rng_consumed:{str(rng).lower()}",
        f"mode_guard:imgaug_deterministic:{str(guard and rng).lower()}",
        f"external_attrs:{','.join(sorted(external_attrs & invoked_attrs)) or 'none'}",
        "state_paths:"
        + (",".join(f"{item.kind}:{item.path}" for item in accesses_tuple) or "none"),
    )
    return v5.AnalysisV5(
        "unknown" if reasons else "resolved",
        effect,
        tuple(reasons),
        "imgaug-v5",
        evidence,
    )


def evaluate_unit(
    unit: Unit, binding: dict[str, object], classes: dict[str, ast.ClassDef]
) -> dict[str, object]:
    result = analyze(binding, classes)
    reasons = v5.validator_v5(result, frozenset(("framework_specific",)))
    decision = "reject" if reasons else "admit"
    reason_match = (
        not reasons
        if unit.coarse_reason == "none"
        else any(unit.coarse_reason in reason for reason in reasons)
    )
    classified = result.status == "resolved" or any(
        any(category in reason for category in CLASSIFIED_REASONS) for reason in reasons
    )
    return {
        "public_symbol": unit.public_symbol,
        "expected_decision": unit.expected,
        "actual_decision": decision,
        "decision_correct": decision == unit.expected,
        "expected_coarse_reason": unit.coarse_reason,
        "coarse_reason_match": reason_match,
        "classified": classified,
        "status": result.status,
        "state_roles": ";".join(sorted(result.effect.state_roles)) or "none",
        "required_modes": ";".join(sorted(result.effect.required_modes)) or "none",
        "super_resolution": result.effect.super_resolution,
        "validator_reasons": ";".join(reasons) or "none",
        "source_binding_sha256": binding.get("binding_sha256") or "none",
        "evidence": ";".join(result.evidence) or "none",
    }


def calibrate() -> None:
    classes = package_classes()
    rows = [
        evaluate_unit(Unit(*item), public_binding(item[0]), classes)
        for item in CALIBRATION_UNITS
    ]
    write_csv(OUT / "autocontract_h7f_imgaug_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reasons = sum(row["coarse_reason_match"] is True for row in rows)
    complete = sum(row["super_resolution"] == "complete" for row in rows)
    ready = correct == len(rows) and reasons == len(rows) and complete == len(rows)
    summary = {
        "units": len(rows),
        "decisions_correct": correct,
        "reason_categories_correct": reasons,
        "super_resolution_complete": complete,
        "adapter_freeze_ready": ready,
    }
    write_csv(CALIBRATION_SUMMARY, [summary])
    print(json.dumps(summary, indent=2))
    for row in rows:
        print(
            row["public_symbol"],
            row["actual_decision"],
            row["state_roles"],
            row["validator_reasons"],
        )
    if not ready:
        raise RuntimeError("imgaug adapter is not freeze-ready")


def protocol_units() -> list[Unit]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    return [Unit(**item) for item in protocol["sealed_units"]]


def seal() -> None:
    if not CALIBRATION_SUMMARY.is_file():
        raise RuntimeError("run --calibrate first")
    summary_rows = list(csv.DictReader(CALIBRATION_SUMMARY.open(encoding="utf-8")))
    if not summary_rows or summary_rows[0]["adapter_freeze_ready"].lower() != "true":
        raise RuntimeError("calibration is not freeze-ready")
    bindings = [public_binding(unit.public_symbol) for unit in protocol_units()]
    if not all(item["status"] == "resolved" for item in bindings):
        unresolved = [item["public_symbol"] for item in bindings if item["status"] != "resolved"]
        raise RuntimeError(f"unresolved formal symbols: {unresolved}")
    SYMBOLS.write_text(
        json.dumps(
            {
                "repository_commit": repository_revision(),
                "package": "imgaug",
                "bindings": bindings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    ADAPTER_MANIFEST.write_text(
        json.dumps(
            {
                "adapter": "imgaug-v5",
                "rules": ADAPTER_RULES,
                "active_mode": "imgaug_deterministic",
                "effect_v5_mode_token": "framework_specific",
                "calibration_symbols": [item[0] for item in CALIBRATION_UNITS],
                "formal_symbols": [unit.public_symbol for unit in protocol_units()],
                "sets_disjoint": not bool(
                    {item[0] for item in CALIBRATION_UNITS}
                    & {unit.public_symbol for unit in protocol_units()}
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    freeze = {
        "repository_commit": repository_revision(),
        "effect_v5_sha256": digest(Path(v5.__file__)),
        "symbol_sealer_sha256": digest(ROOT / "experiments" / "autocontract_symbol_origin.py"),
        "adapter_sha256": digest(Path(__file__)),
        "adapter_manifest_sha256": digest(ADAPTER_MANIFEST),
        "protocol_sha256": digest(PROTOCOL),
        "symbol_manifest_sha256": digest(SYMBOLS),
        "calibration_summary_sha256": digest(CALIBRATION_SUMMARY),
    }
    FREEZE.write_text(json.dumps(freeze, indent=2), encoding="utf-8")
    print(json.dumps(freeze, indent=2))


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    files = {
        "effect_v5_sha256": Path(v5.__file__),
        "symbol_sealer_sha256": ROOT / "experiments" / "autocontract_symbol_origin.py",
        "adapter_sha256": Path(__file__),
        "adapter_manifest_sha256": ADAPTER_MANIFEST,
        "protocol_sha256": PROTOCOL,
        "symbol_manifest_sha256": SYMBOLS,
        "calibration_summary_sha256": CALIBRATION_SUMMARY,
    }
    for key, path in files.items():
        if digest(path) != freeze[key]:
            raise RuntimeError(f"H7F freeze violation: {key}")
    if repository_revision() != freeze["repository_commit"]:
        raise RuntimeError("H7F repository revision changed")
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    for binding in manifest["bindings"]:
        if digest(REPO / binding["source_path"]) != binding["source_sha256"]:
            raise RuntimeError(f"H7F source hash changed: {binding['public_symbol']}")
    return freeze


def formal_run() -> None:
    freeze = verify_freeze()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    classes = package_classes()
    rows = [
        evaluate_unit(unit, bindings[unit.public_symbol], classes)
        for unit in protocol_units()
    ]
    safe = [row for row in rows if row["expected_decision"] == "admit"]
    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    false_accepts = sum(row["actual_decision"] == "admit" for row in unsafe)
    safe_recall = sum(row["actual_decision"] == "admit" for row in safe) / len(safe)
    coarse_accuracy = sum(row["coarse_reason_match"] is True for row in rows) / len(rows)
    classified_coverage = sum(row["classified"] is True for row in rows) / len(rows)
    binding_integrity = sum(item["status"] == "resolved" for item in bindings.values()) / len(bindings)
    thresholds = protocol["thresholds"]
    passed = (
        binding_integrity >= thresholds["binding_integrity"]
        and false_accepts <= thresholds["known_unsafe_false_accepts"]
        and safe_recall >= thresholds["supported_safe_recall"]
        and coarse_accuracy >= thresholds["coarse_reason_accuracy"]
        and classified_coverage >= thresholds["classified_coverage"]
    )
    summary = {
        "protocol": protocol["protocol"],
        "units": len(rows),
        "binding_integrity": binding_integrity,
        "decisions_correct": sum(row["decision_correct"] is True for row in rows),
        "known_unsafe_false_accepts": false_accepts,
        "supported_safe_recall": safe_recall,
        "coarse_reason_accuracy": coarse_accuracy,
        "classified_coverage": classified_coverage,
        "h7f_blind_gate_pass": passed,
        "adapter_sha256": freeze["adapter_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
    }
    write_csv(OUT / "autocontract_h7f_imgaug.csv", rows)
    write_csv(OUT / "autocontract_h7f_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7F imgaug holdout",
            "",
            f"Binding integrity: {binding_integrity:.1%}.",
            f"Decisions correct: {summary['decisions_correct']}/{len(rows)}.",
            f"Known-unsafe false accepts: {false_accepts}.",
            f"Supported-safe recall: {safe_recall:.1%}.",
            f"Coarse-reason accuracy: {coarse_accuracy:.1%}.",
            f"Classified coverage: {classified_coverage:.1%}.",
            f"H7F blind gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "| Symbol | Expected | Actual | State roles | Mode | Reason |",
            "|---|---|---|---|---|---|",
            *[
                f"| `{row['public_symbol']}` | {row['expected_decision']} | "
                f"{row['actual_decision']} | {row['state_roles']} | "
                f"{row['required_modes']} | {row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "The formal symbols are disjoint from adapter calibration symbols; protocol, "
            "thresholds, adapter, symbol origins, and sources were frozen before formal effect analysis.",
            "",
        ]
    )
    (OUT / "autocontract_h7f_imgaug.md").write_text(report, encoding="utf-8")
    print(report)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--calibrate", action="store_true")
    group.add_argument("--seal", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.calibrate:
        calibrate()
    elif args.seal:
        seal()
    else:
        formal_run()


if __name__ == "__main__":
    main()
