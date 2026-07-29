"""EffectV6 Albumentations adapter, calibration, sealing, and H7G runner."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7
import autocontract_h7d_effect_v4 as v4
import autocontract_h7f_effect_v5 as v5
import autocontract_h7f_posthoc_callable_origin as provenance
import autocontract_h7g_effect_v6 as v6
from autocontract_symbol_origin import SymbolOriginSealer, binding_record


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = (
    ROOT
    / ".research"
    / "semantics_safe_reconfiguration"
    / "h7g_corpus"
    / "albumentations_repo"
)
PROTOCOL = OUT / "autocontract_h7g_protocol.json"
SYMBOLS = OUT / "autocontract_h7g_symbol_manifest.json"
ADAPTER_MANIFEST = OUT / "autocontract_h7g_adapter_manifest.json"
FREEZE = OUT / "autocontract_h7g_freeze.json"
CALIBRATION_SUMMARY = OUT / "autocontract_h7g_albumentations_calibration_summary.csv"

CALIBRATION_UNITS = (
    ("albumentations.core.transforms_interface.NoOp", "admit", "none"),
    ("albumentations.augmentations.pixel.transforms.Normalize", "admit", "none"),
    ("albumentations.augmentations.geometric.flip.HorizontalFlip", "admit", "none"),
    (
        "albumentations.augmentations.pixel.transforms.RandomBrightnessContrast",
        "admit",
        "none",
    ),
    ("albumentations.core.composition.Compose", "reject", "child"),
    ("albumentations.core.composition.ReplayCompose", "reject", "child"),
    (
        "albumentations.augmentations.other.lambda_transform.Lambda",
        "reject",
        "user_callable",
    ),
)
EXECUTION_NAMES = frozenset(
    (
        "__call__",
        "should_apply",
        "get_params",
        "get_params_dependent_on_data",
        "update_transform_params",
        "apply_with_params",
        "apply",
        "apply_to_mask",
        "apply_to_bboxes",
        "apply_to_keypoints",
        "apply_to_images",
        "apply_to_volume",
        "apply_to_volumes",
    )
)
RNG_ATTRS = frozenset(("py_random", "random_generator"))
CLASSIFIED_REASONS = frozenset(
    ("unresolved_child_effect", "unresolved_user_callable", "execution_external_effect")
)
ADAPTER_RULES = (
    "BasicTransform.__call__ plus root-most get_params/apply hooks form transform execution",
    "BaseCompose.__call__ plus calls over self.transforms denote child delegation",
    "kwargs are a framework-defined whole-record scope and unhandled keys are preserved",
    "self.py_random and self.random_generator method calls are delegated RNG mutation",
    "BasicTransform replay_mode bypasses sampling and applies stored self.params",
    "Compose(seed) is reproducible sequence state, not per-sample replay proof",
    "constructor Callable parameters propagated into invoked attrs/containers are public-input callables",
    "direct calls to package top-level functions are module-bound callables",
    "other execution cache/control state and external effects remain fail closed",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_revision() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def public_binding(symbol: str) -> dict[str, object]:
    return binding_record(SymbolOriginSealer(REPO, "albumentations").resolve(symbol))


def package_index() -> tuple[dict[str, ast.ClassDef], set[str]]:
    class_candidates: dict[str, list[ast.ClassDef]] = {}
    functions: set[str] = set()
    for path in sorted((REPO / "albumentations").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes, funcs = v2.top_definitions(tree)
        functions.update(funcs)
        for name, cls in classes.items():
            class_candidates.setdefault(name, []).append(cls)
    classes = {name: items[0] for name, items in class_candidates.items() if len(items) == 1}
    return classes, functions


def target_class(binding: dict[str, object]) -> ast.ClassDef | None:
    if not binding.get("source_path") or not binding.get("defining_name"):
        return None
    path = REPO / str(binding["source_path"])
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes, _ = v2.top_definitions(tree)
    return classes.get(str(binding["defining_name"]))


def class_chain(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    return v2.class_chain(root, {**classes, root.name: root})


def construction_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    return [
        method
        for cls in class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in v2.CONSTRUCTION_METHODS
    ]


def execution_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    selected: dict[str, ast.FunctionDef] = {}
    for cls in class_chain(root, classes):
        for name, method in v2.method_map(cls).items():
            if name in EXECUTION_NAMES:
                selected.setdefault(name, method)
    return list(selected.values())


def inherited_execution_nodes(
    root: ast.ClassDef, classes: dict[str, ast.ClassDef]
) -> list[ast.AST]:
    """Return all hook implementations for delegation across super overrides."""
    return [
        method
        for cls in class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in EXECUTION_NAMES
    ]


def is_compose(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> bool:
    return any(cls.name == "BaseCompose" for cls in class_chain(root, classes))


def has_child_delegation(execution: list[ast.AST]) -> bool:
    for node in execution:
        for loop in (item for item in ast.walk(node) if isinstance(item, ast.For)):
            iterator = v2.corpus_v1.attribute_chain(loop.iter)
            if iterator != "self.transforms":
                continue
            targets: set[str] = set()
            if isinstance(loop.target, ast.Name):
                targets.add(loop.target.id)
            for child in ast.walk(loop):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    if child.func.id in targets:
                        return True
    return False


def rng_accesses(execution: list[ast.AST]) -> set[str]:
    paths: set[str] = set()
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            chain = v2.corpus_v1.attribute_chain(child.func)
            parts = chain.split(".")
            if len(parts) >= 3 and parts[0] == "self" and parts[1] in RNG_ATTRS:
                paths.add(".".join(parts[:2]))
    return paths


def has_replay_guard(classes: dict[str, ast.ClassDef]) -> bool:
    basic = classes.get("BasicTransform")
    if basic is None:
        return False
    method = v2.method_map(basic).get("__call__")
    if method is None:
        return False
    rendered = ast.unparse(method)
    return (
        "if self.replay_mode" in rendered
        and "self.apply_with_params(self.params" in rendered
        and rendered.index("if self.replay_mode") < rendered.index("self.params = {}")
    )


def callable_annotations(method: ast.FunctionDef) -> set[str]:
    result: set[str] = set()
    for arg in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs):
        if arg.arg == "self" or arg.annotation is None:
            continue
        if "Callable" in ast.unparse(arg.annotation):
            result.add(arg.arg)
    return result


def container_callable_attrs(root: ast.ClassDef) -> set[str]:
    method = v2.method_map(root).get("__init__")
    if method is None:
        return set()
    public_callable_params = callable_annotations(method)
    found: set[str] = set()
    for loop in (node for node in ast.walk(method) if isinstance(node, ast.For)):
        if not isinstance(loop.target, (ast.Tuple, ast.List)) or len(loop.target.elts) < 2:
            continue
        value_target = loop.target.elts[1]
        if not isinstance(value_target, ast.Name):
            continue
        iter_names = {
            child.id
            for child in ast.walk(loop.iter)
            if isinstance(child, ast.Name) and child.id in public_callable_params
        }
        if not iter_names:
            continue
        for child in ast.walk(loop):
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            value = child.value
            if not isinstance(value, ast.Name) or value.id != value_target.id:
                continue
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            for target in targets:
                if isinstance(target, ast.Subscript):
                    root_path = v5.state_root(target)
                    if root_path.startswith("self."):
                        found.add(root_path + "[*]")
    return found


def direct_callable_bindings(
    root: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    functions: set[str],
    execution: list[ast.AST],
) -> tuple[v6.CallableBinding, ...]:
    attrs = provenance.constructor_origins(root, {**classes, root.name: root}, functions)
    invoked = h7f_invoked_attrs(execution)
    bindings: dict[str, v6.CallableOrigin] = {}
    origin_map: dict[str, v6.CallableOrigin] = {
        "module_symbol": "module_bound",
        "user_input": "public_input",
        "user_derived": "public_input_derived",
        "internal": "module_bound",
        "unknown": "unknown",
    }
    init_method = v2.method_map(root).get("__init__")
    callable_params = callable_annotations(init_method) if init_method is not None else set()
    for attr in invoked & set(attrs):
        if (
            any(token in attr.lower() for token in ("func", "fn", "callable"))
            or attr in callable_params
            or attr.endswith("read_fn")
        ):
            bindings[attr] = origin_map[attrs[attr]]
    for attr in container_callable_attrs(root):
        bindings[attr] = "public_input"
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            if isinstance(child.func, ast.Name) and child.func.id in functions:
                bindings.setdefault(child.func.id, "module_bound")
    return tuple(v6.CallableBinding(name, bindings[name]) for name in sorted(bindings))


def h7f_invoked_attrs(execution: list[ast.AST]) -> set[str]:
    attrs: set[str] = set()
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = v2.corpus_v1.attribute_chain(child.func)
            if chain.startswith("self."):
                attrs.add(chain.split(".", 2)[1])
    return attrs


def super_resolution(
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


def analyze(
    binding: dict[str, object], classes: dict[str, ast.ClassDef], functions: set[str]
) -> v6.AnalysisV6:
    root = target_class(binding)
    if root is None:
        empty_v4 = v4.EffectV4(None, "unknown", "none")
        empty_v5 = v5.EffectV5(
            empty_v4, (), frozenset(("unknown",)), frozenset(("unknown",)), False, "unknown"
        )
        effect = v6.EffectV6(
            empty_v5,
            (),
            (v6.CallableBinding("<missing>", "unknown"),),
            (v6.ModeObligation("albumentations.replay", "required", "unknown"),),
        )
        return v6.AnalysisV6(
            "unknown", effect, ("sealed_definition_missing",), "albumentations-v6", ()
        )

    construction = construction_nodes(root, classes)
    execution = execution_nodes(root, classes)
    child = is_compose(root, classes) and has_child_delegation(
        inherited_execution_nodes(root, classes)
    )
    callables = direct_callable_bindings(root, classes, functions, execution)
    dynamic_callable = any(
        item.origin in ("public_input", "public_input_derived", "external_dynamic", "unknown")
        for item in callables
    )
    delegation: v4.DelegationKind = (
        "child_operator" if child else "user_callable" if dynamic_callable else "none"
    )
    construction_reads, construction_writes = v2.external_effects(construction)
    execution_reads, execution_writes = v2.external_effects(execution)

    direct = v5.state_accesses(execution)
    rng_paths = rng_accesses(execution)
    replay_guard = has_replay_guard(classes)
    v5_accesses = list(direct)
    for path in sorted(rng_paths):
        if not any(item.path == path for item in v5_accesses):
            v5_accesses.append(v5.StateAccess(path, "container_mutation"))
    v5_accesses_tuple = tuple(sorted(v5_accesses, key=lambda item: (item.path, item.kind)))
    roles: set[v5.StateRole] = set()
    for item in v5_accesses_tuple:
        lowered = item.path.lower()
        if item.path in rng_paths or item.path == "self.params":
            roles.add("replayable")
        elif any(token in lowered for token in ("cache", "buffer", "history")):
            roles.add("cache")
        else:
            roles.add("persistent_control")
    modes: set[v5.RequiredMode] = set()
    if "replayable" in roles:
        if replay_guard:
            modes.add("framework_specific")
        else:
            modes.add("unknown")
            roles.add("unknown")

    base = h7.EffectV3(
        construction_reads,
        construction_writes,
        v2.self_state_write(construction),
        v2.rng_sources(construction),
        frozenset(("record",)),
        frozenset(("record",)),
        execution_reads,
        execution_writes,
        v2.rng_sources(execution),
        bool(rng_paths) or delegation != "none",
        "fixed",
        False,
        "one",
        "one",
        "preserve",
        bool(v5_accesses_tuple),
    )
    effect_v4 = v4.EffectV4(base, "whole_record", delegation)
    super_status = super_resolution(root, classes)
    effect_v5 = v5.EffectV5(
        effect_v4,
        v5_accesses_tuple,
        frozenset(roles),
        frozenset(modes),
        replay_guard and "replayable" in roles,
        super_status,
    )
    state_v6 = tuple(
        v6.StateAccessV6(
            item.path,
            "delegated_mutation" if item.path in rng_paths else item.kind,
        )
        for item in v5_accesses_tuple
    )
    obligations = (
        (v6.ModeObligation("albumentations.replay", "required", "conditional_restore"),)
        if "replayable" in roles
        else ()
    )
    effect = v6.EffectV6(effect_v5, state_v6, callables, obligations)
    reasons: list[str] = []
    if child:
        reasons.append("unresolved_child_effect")
    elif dynamic_callable:
        reasons.append("unresolved_user_callable")
    if super_status != "complete":
        reasons.append("partial_super_resolution")
    evidence = (
        "entrypoint:BasicTransform/BaseCompose.__call__",
        "record_scope:whole_record:kwargs",
        f"delegation:{delegation}",
        f"replay_guard:{str(replay_guard).lower()}",
        "rng_paths:" + (",".join(sorted(rng_paths)) or "none"),
        "callable_origins:"
        + (",".join(f"{item.attribute}={item.origin}" for item in callables) or "none"),
    )
    return v6.AnalysisV6(
        "unknown" if reasons else "resolved",
        effect,
        tuple(reasons),
        "albumentations-v6",
        evidence,
    )


def evaluate(
    symbol: str,
    expected: str,
    coarse_reason: str,
    binding: dict[str, object],
    classes: dict[str, ast.ClassDef],
    functions: set[str],
) -> dict[str, object]:
    result = analyze(binding, classes, functions)
    reasons = v6.validator_v6(
        result,
        frozenset(("albumentations.replay",)),
        frozenset(("framework_specific",)),
    )
    decision = "reject" if reasons else "admit"
    coarse_match = (
        not reasons if coarse_reason == "none" else any(coarse_reason in item for item in reasons)
    )
    classified = result.status == "resolved" or any(
        any(category in reason for category in CLASSIFIED_REASONS) for reason in reasons
    )
    return {
        "public_symbol": symbol,
        "expected_decision": expected,
        "actual_decision": decision,
        "decision_correct": decision == expected,
        "expected_coarse_reason": coarse_reason,
        "coarse_reason_match": coarse_match,
        "classified": classified,
        "status": result.status,
        "state_accesses": ";".join(
            f"{item.kind}:{item.path}" for item in result.effect.state_accesses
        )
        or "none",
        "callable_origins": ";".join(
            f"{item.attribute}={item.origin}" for item in result.effect.callable_bindings
        )
        or "none",
        "named_modes": ";".join(item.name for item in result.effect.mode_obligations)
        or "none",
        "super_resolution": result.effect.base.super_resolution,
        "validator_reasons": ";".join(reasons) or "none",
        "source_binding_sha256": binding.get("binding_sha256") or "none",
        "evidence": ";".join(result.evidence),
    }


def calibrate() -> None:
    classes, functions = package_index()
    rows = [
        evaluate(symbol, expected, reason, public_binding(symbol), classes, functions)
        for symbol, expected, reason in CALIBRATION_UNITS
    ]
    write_csv(OUT / "autocontract_h7g_albumentations_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reason_correct = sum(row["coarse_reason_match"] is True for row in rows)
    super_complete = sum(row["super_resolution"] == "complete" for row in rows)
    lambda_row = next(row for row in rows if row["public_symbol"].endswith("Lambda"))
    safe_rows = [row for row in rows if row["expected_decision"] == "admit"]
    ready = (
        correct == len(rows)
        and reason_correct == len(rows)
        and super_complete == len(rows)
        and "public_input" in lambda_row["callable_origins"]
        and all(row["actual_decision"] == "admit" for row in safe_rows)
    )
    summary = {
        "units": len(rows),
        "decisions_correct": correct,
        "reason_categories_correct": reason_correct,
        "super_resolution_complete": super_complete,
        "lambda_public_input_detected": "public_input" in lambda_row["callable_origins"],
        "adapter_freeze_ready": ready,
    }
    write_csv(CALIBRATION_SUMMARY, [summary])
    print(json.dumps(summary, indent=2))
    for row in rows:
        print(
            row["public_symbol"],
            row["actual_decision"],
            row["state_accesses"],
            row["callable_origins"],
            row["validator_reasons"],
        )
    if not ready:
        raise RuntimeError("Albumentations adapter is not freeze-ready")


def protocol_units() -> list[dict[str, str]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    return list(protocol["sealed_units"])


def seal() -> None:
    if not CALIBRATION_SUMMARY.is_file():
        raise RuntimeError("run --calibrate first")
    summary = next(csv.DictReader(CALIBRATION_SUMMARY.open(encoding="utf-8")))
    if summary["adapter_freeze_ready"].lower() != "true":
        raise RuntimeError("calibration is not freeze-ready")
    bindings = [public_binding(unit["public_symbol"]) for unit in protocol_units()]
    if not all(item["status"] == "resolved" for item in bindings):
        unresolved = [item["public_symbol"] for item in bindings if item["status"] != "resolved"]
        raise RuntimeError(f"unresolved formal symbols: {unresolved}")
    SYMBOLS.write_text(
        json.dumps(
            {
                "repository_commit": repository_revision(),
                "package": "albumentations",
                "bindings": bindings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    formal = {unit["public_symbol"] for unit in protocol_units()}
    calibration = {item[0] for item in CALIBRATION_UNITS}
    ADAPTER_MANIFEST.write_text(
        json.dumps(
            {
                "adapter": "albumentations-v6",
                "rules": ADAPTER_RULES,
                "active_named_mode": "albumentations.replay",
                "calibration_symbols": sorted(calibration),
                "formal_symbols": sorted(formal),
                "sets_disjoint": not bool(calibration & formal),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    freeze = {
        "repository_commit": repository_revision(),
        "effect_v6_sha256": digest(Path(v6.__file__)),
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
        "effect_v6_sha256": Path(v6.__file__),
        "symbol_sealer_sha256": ROOT / "experiments" / "autocontract_symbol_origin.py",
        "adapter_sha256": Path(__file__),
        "adapter_manifest_sha256": ADAPTER_MANIFEST,
        "protocol_sha256": PROTOCOL,
        "symbol_manifest_sha256": SYMBOLS,
        "calibration_summary_sha256": CALIBRATION_SUMMARY,
    }
    for key, path in files.items():
        if digest(path) != freeze[key]:
            raise RuntimeError(f"H7G freeze violation: {key}")
    if repository_revision() != freeze["repository_commit"]:
        raise RuntimeError("H7G repository revision changed")
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    for binding in manifest["bindings"]:
        if digest(REPO / binding["source_path"]) != binding["source_sha256"]:
            raise RuntimeError(f"H7G source hash changed: {binding['public_symbol']}")
    return freeze


def formal_run() -> None:
    freeze = verify_freeze()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    classes, functions = package_index()
    rows = [
        evaluate(
            unit["public_symbol"],
            unit["expected"],
            unit["coarse_reason"],
            bindings[unit["public_symbol"]],
            classes,
            functions,
        )
        for unit in protocol_units()
    ]
    safe = [row for row in rows if row["expected_decision"] == "admit"]
    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    false_accepts = sum(row["actual_decision"] == "admit" for row in unsafe)
    safe_recall = sum(row["actual_decision"] == "admit" for row in safe) / len(safe)
    coarse_accuracy = sum(row["coarse_reason_match"] is True for row in rows) / len(rows)
    coverage = sum(row["classified"] is True for row in rows) / len(rows)
    binding_integrity = sum(item["status"] == "resolved" for item in bindings.values()) / len(bindings)
    thresholds = protocol["thresholds"]
    passed = (
        binding_integrity >= thresholds["binding_integrity"]
        and false_accepts <= thresholds["known_unsafe_false_accepts"]
        and safe_recall >= thresholds["supported_safe_recall"]
        and coarse_accuracy >= thresholds["coarse_reason_accuracy"]
        and coverage >= thresholds["classified_coverage"]
    )
    summary = {
        "protocol": protocol["protocol"],
        "units": len(rows),
        "binding_integrity": binding_integrity,
        "decisions_correct": sum(row["decision_correct"] is True for row in rows),
        "known_unsafe_false_accepts": false_accepts,
        "supported_safe_recall": safe_recall,
        "coarse_reason_accuracy": coarse_accuracy,
        "classified_coverage": coverage,
        "h7g_blind_gate_pass": passed,
        "adapter_sha256": freeze["adapter_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
    }
    write_csv(OUT / "autocontract_h7g_albumentations.csv", rows)
    write_csv(OUT / "autocontract_h7g_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7G Albumentations holdout",
            "",
            f"Binding integrity: {binding_integrity:.1%}.",
            f"Decisions correct: {summary['decisions_correct']}/{len(rows)}.",
            f"Known-unsafe false accepts: {false_accepts}.",
            f"Supported-safe recall: {safe_recall:.1%}.",
            f"Coarse-reason accuracy: {coarse_accuracy:.1%}.",
            f"Classified coverage: {coverage:.1%}.",
            f"H7G blind gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "| Symbol | Expected | Actual | State | Callable | Mode | Reason |",
            "|---|---|---|---|---|---|---|",
            *[
                f"| `{row['public_symbol']}` | {row['expected_decision']} | "
                f"{row['actual_decision']} | {row['state_accesses']} | "
                f"{row['callable_origins']} | {row['named_modes']} | "
                f"{row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "The replay context is a per-sample stored-parameter context, not merely Compose(seed).",
            "Formal symbols are disjoint from calibration and were effect-analyzed only after freeze.",
            "",
        ]
    )
    (OUT / "autocontract_h7g_albumentations.md").write_text(report, encoding="utf-8")
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
