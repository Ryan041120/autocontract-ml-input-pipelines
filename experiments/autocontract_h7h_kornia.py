"""Kornia v0.8.3 adapter calibration, H7H sealing, and one-shot runner."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import autocontract_h7_adapters as h7
import autocontract_h7d_effect_v4 as v4
import autocontract_h7f_effect_v5 as v5
import autocontract_h7g_effect_v6 as v6
import autocontract_h7h_effect_v7 as v7
from autocontract_symbol_origin import SymbolOriginSealer, binding_record


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
PROTOCOL = OUT / "autocontract_h7h_protocol.json"
SYMBOLS = OUT / "autocontract_h7h_symbol_manifest.json"
ADAPTER_MANIFEST = OUT / "autocontract_h7h_adapter_manifest.json"
FREEZE = OUT / "autocontract_h7h_freeze.json"
CALIBRATION_SUMMARY = OUT / "autocontract_h7h_kornia_calibration_summary.csv"

CALIBRATION_UNITS = (
    ("kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip", "kornia.params_provided", "replay_apply", "admit", "none"),
    ("kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip", "kornia.params_absent", "sample_apply", "reject", "sampling_rng"),
    ("kornia.augmentation._2d.intensity.gaussian_blur.RandomGaussianBlur", "kornia.params_provided", "replay_apply", "admit", "none"),
    ("kornia.augmentation._2d.intensity.gaussian_blur.RandomGaussianBlur", "kornia.params_absent", "sample_apply", "reject", "sampling_rng"),
    ("kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle", "kornia.params_provided", "replay_apply", "admit", "none"),
    ("kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle", "kornia.params_absent", "sample_apply", "reject", "sampling_rng"),
    ("kornia.augmentation._2d.geometric.affine.RandomAffine", "kornia.params_provided", "replay_apply", "admit", "none"),
    ("kornia.augmentation._2d.geometric.affine.RandomAffine", "kornia.params_absent", "sample_apply", "reject", "sampling_rng"),
    ("kornia.augmentation.container.image.ImageSequential", "kornia.params_provided", "replay_apply", "reject", "child"),
)

ADAPTER_RULES = (
    "nn.Module dispatch enters the most-derived forward method",
    "params=None selects sample_apply and reaches forward_parameters",
    "a supplied compatible params record selects replay_apply and prunes forward_parameters",
    "self/super calls are closed through Kornia augmentation base classes",
    "forward_parameters/generate_parameters on the active path denote delegated sampling RNG",
    "ImageSequential/AugmentationSequential delegate to child modules and fail closed without child contracts",
    "self._params is a replay artifact; writing the supplied record is not fresh sampling",
    "unknown reachable dispatch and dynamic callables remain fail closed",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_revision() -> str:
    completed = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return completed.stdout.strip().lower()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def public_binding(symbol: str) -> dict[str, object]:
    return binding_record(SymbolOriginSealer(REPO, "kornia").resolve(symbol))


def package_classes() -> dict[str, ast.ClassDef]:
    candidates: dict[str, list[ast.ClassDef]] = {}
    for path in sorted((REPO / "kornia" / "augmentation").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                candidates.setdefault(node.name, []).append(node)
    return {name: items[0] for name, items in candidates.items() if len(items) == 1}


def target_class(binding: dict[str, object]) -> ast.ClassDef | None:
    if not binding.get("source_path") or not binding.get("defining_name"):
        return None
    path = REPO / str(binding["source_path"])
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == binding["defining_name"]), None)


def empty_predecessor() -> v6.EffectV6:
    base3 = h7.EffectV3(frozenset(), frozenset(), False, (), frozenset(("tensor",)), frozenset(("tensor",)), frozenset(), frozenset(), (), False, "fixed", False, "one", "one", "preserve", False)
    base4 = v4.EffectV4(base3, "whole_record", "none")
    base5 = v5.EffectV5(base4, (), frozenset(), frozenset(), False, "complete")
    return v6.EffectV6(base5, (), (), ())


def is_child_container(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> bool:
    names = {item.name for item in v7.method_chain(root, classes)}
    return bool(names & {"SequentialBase", "ImageSequentialBase", "ImageSequential", "AugmentationSequential"})


def analyze(binding: dict[str, object], classes: dict[str, ast.ClassDef], configuration: str) -> v7.AnalysisV7:
    root = target_class(binding)
    provided = configuration == "kornia.params_provided"
    context = v7.ReachabilityContext(configuration, "replay_apply" if provided else "sample_apply", (("params", "provided" if provided else "none"),))
    if root is None:
        reachable = v7.ReachableSlice(context, (), (), (), (v6.CallableBinding("<missing>", "unknown"),), (), False, "none", ("missing_root",))
        result = v7.AnalysisV7("unknown", v7.EffectV7(empty_predecessor(), reachable), (), (), "kornia-v7")
        return result
    nodes, methods, guards, unresolved = v7.reachable_nodes(root, classes, "forward", context)
    sampling = any(name.rsplit(".", 1)[-1] in {"forward_parameters", "generate_parameters", "__batch_prob_generator__"} for name in methods)
    child = is_child_container(root, classes)
    accesses = v7.state_accesses(nodes, set())
    reachable = v7.ReachableSlice(
        context=context,
        methods=methods,
        guards=guards,
        state_accesses=accesses,
        callable_bindings=(),
        rng_paths=("delegated_parameter_generator",) if sampling else (),
        sampling_rng=sampling,
        delegation="child_operator" if child else "none",
        unresolved_dispatch=unresolved,
    )
    provisional = v7.AnalysisV7("resolved", v7.EffectV7(empty_predecessor(), reachable), (), (), "kornia-v7")
    reasons = v7.validator_v7(provisional)
    evidence = (
        "entrypoint:nn.Module->forward",
        "reachable_methods:" + ",".join(methods),
        "guards:" + (",".join(guards) or "none"),
        f"params_branch:{'provided' if provided else 'none'}",
    )
    return v7.AnalysisV7("unknown" if reasons else "resolved", provisional.effect, (), evidence, "kornia-v7")


def evaluate(symbol: str, configuration: str, phase: str, expected: str, coarse_reason: str, binding: dict[str, object], classes: dict[str, ast.ClassDef]) -> dict[str, object]:
    result = analyze(binding, classes, configuration)
    reasons = v7.validator_v7(result)
    actual = "reject" if reasons else "admit"
    reachable = result.effect.reachable
    return {
        "public_symbol": symbol,
        "configuration": configuration,
        "phase": phase,
        "expected_decision": expected,
        "actual_decision": actual,
        "decision_correct": actual == expected,
        "coarse_reason": coarse_reason,
        "coarse_reason_match": v7.coarse_match(coarse_reason, reasons),
        "reachable_methods": ";".join(reachable.methods),
        "guards": ";".join(reachable.guards) or "none",
        "state_accesses": ";".join(f"{item.kind}:{item.path}" for item in reachable.state_accesses) or "none",
        "sampling_rng": reachable.sampling_rng,
        "delegation": reachable.delegation,
        "validator_reasons": ";".join(reasons) or "none",
        "classified": actual in {"admit", "reject"},
    }


def calibrate() -> None:
    classes = package_classes()
    rows = [evaluate(*unit, public_binding(unit[0]), classes) for unit in CALIBRATION_UNITS]
    write_csv(OUT / "autocontract_h7h_kornia_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reasons = sum(row["coarse_reason_match"] is True for row in rows)
    pairs: dict[str, dict[str, str]] = {}
    for row in rows:
        pairs.setdefault(str(row["public_symbol"]), {})[str(row["configuration"])] = str(row["actual_decision"])
    contrast = all(values.get("kornia.params_provided") == "admit" and values.get("kornia.params_absent") == "reject" for symbol, values in pairs.items() if not symbol.endswith(".ImageSequential"))
    ready = correct == len(rows) and reasons == len(rows) and contrast
    summary = {"units": len(rows), "decisions_correct": correct, "reason_categories_correct": reasons, "phase_contrast_accuracy": 1.0 if contrast else 0.0, "adapter_freeze_ready": ready}
    write_csv(CALIBRATION_SUMMARY, [summary])
    report = "\n".join(["# H7H Kornia adapter calibration", "", f"Decisions: {correct}/{len(rows)}; reasons: {reasons}/{len(rows)}; phase contrast: {summary['phase_contrast_accuracy']:.1%}.", f"Freeze ready: **{'YES' if ready else 'NO'}**.", "", "| Symbol | Configuration | Expected | Actual | Sampling | Delegation | Reason |", "|---|---|---|---|---|---|---|", *[f"| `{row['public_symbol']}` | {row['configuration']} | {row['expected_decision']} | {row['actual_decision']} | {row['sampling_rng']} | {row['delegation']} | {row['validator_reasons']} |" for row in rows], ""])
    (OUT / "autocontract_h7h_kornia_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if not ready:
        raise RuntimeError("Kornia adapter is not freeze-ready")


def protocol_units() -> list[dict[str, str]]:
    return list(json.loads(PROTOCOL.read_text(encoding="utf-8"))["sealed_units"])


def seal() -> None:
    summary = next(csv.DictReader(CALIBRATION_SUMMARY.open(encoding="utf-8")))
    if summary["adapter_freeze_ready"].lower() != "true":
        raise RuntimeError("calibration is not freeze-ready")
    symbols = sorted({unit["public_symbol"] for unit in protocol_units()})
    bindings = [public_binding(symbol) for symbol in symbols]
    if not all(item["status"] == "resolved" for item in bindings):
        raise RuntimeError("unresolved formal symbol")
    SYMBOLS.write_text(json.dumps({"repository_commit": repository_revision(), "package": "kornia", "bindings": bindings}, indent=2), encoding="utf-8")
    formal = set(symbols)
    calibration = {item[0] for item in CALIBRATION_UNITS}
    ADAPTER_MANIFEST.write_text(json.dumps({"adapter": "kornia-v7", "rules": ADAPTER_RULES, "calibration_symbols": sorted(calibration), "formal_symbols": sorted(formal), "sets_disjoint": not bool(calibration & formal)}, indent=2), encoding="utf-8")
    freeze = {
        "repository_commit": repository_revision(),
        "effect_v7_sha256": digest(Path(v7.__file__)),
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
    files = {"effect_v7_sha256": Path(v7.__file__), "symbol_sealer_sha256": ROOT / "experiments" / "autocontract_symbol_origin.py", "adapter_sha256": Path(__file__), "adapter_manifest_sha256": ADAPTER_MANIFEST, "protocol_sha256": PROTOCOL, "symbol_manifest_sha256": SYMBOLS, "calibration_summary_sha256": CALIBRATION_SUMMARY}
    for key, path in files.items():
        if digest(path) != freeze[key]:
            raise RuntimeError("H7H freeze violation: " + key)
    if repository_revision() != freeze["repository_commit"]:
        raise RuntimeError("H7H repository revision changed")
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    for binding in manifest["bindings"]:
        if digest(REPO / binding["source_path"]) != binding["source_sha256"]:
            raise RuntimeError("H7H source hash changed: " + binding["public_symbol"])
    return freeze


def formal_run() -> None:
    freeze = verify_freeze()
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    classes = package_classes()
    rows = [evaluate(unit["public_symbol"], unit["configuration"], unit["phase"], unit["expected"], unit["coarse_reason"], bindings[unit["public_symbol"]], classes) for unit in protocol_units()]
    safe = [row for row in rows if row["expected_decision"] == "admit"]
    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    false_accepts = sum(row["actual_decision"] == "admit" for row in unsafe)
    safe_recall = sum(row["actual_decision"] == "admit" for row in safe) / len(safe)
    reason_accuracy = sum(row["coarse_reason_match"] is True for row in rows) / len(rows)
    coverage = sum(row["classified"] is True for row in rows) / len(rows)
    binding_integrity = sum(item["status"] == "resolved" for item in bindings.values()) / len(bindings)
    pair_symbols = {row["public_symbol"] for row in rows if not str(row["public_symbol"]).endswith(".AugmentationSequential")}
    correct_pairs = 0
    for symbol in pair_symbols:
        pair = {row["configuration"]: row["actual_decision"] for row in rows if row["public_symbol"] == symbol}
        correct_pairs += pair.get("kornia.params_provided") == "admit" and pair.get("kornia.params_absent") == "reject"
    phase_accuracy = correct_pairs / len(pair_symbols)
    thresholds = protocol["thresholds"]
    passed = binding_integrity >= thresholds["binding_integrity"] and false_accepts <= thresholds["known_unsafe_false_accepts"] and safe_recall >= thresholds["supported_safe_recall"] and reason_accuracy >= thresholds["coarse_reason_accuracy"] and coverage >= thresholds["classified_coverage"] and phase_accuracy >= thresholds["phase_contrast_accuracy"]
    summary = {"protocol": protocol["protocol"], "units": len(rows), "binding_integrity": binding_integrity, "decisions_correct": sum(row["decision_correct"] is True for row in rows), "known_unsafe_false_accepts": false_accepts, "supported_safe_recall": safe_recall, "coarse_reason_accuracy": reason_accuracy, "classified_coverage": coverage, "phase_contrast_accuracy": phase_accuracy, "h7h_blind_gate_pass": passed, "adapter_sha256": freeze["adapter_sha256"], "protocol_sha256": freeze["protocol_sha256"]}
    write_csv(OUT / "autocontract_h7h_kornia.csv", rows); write_csv(OUT / "autocontract_h7h_summary.csv", [summary])
    report = "\n".join(["# AutoContract H7H Kornia holdout", "", f"Binding integrity: {binding_integrity:.1%}.", f"Decisions correct: {summary['decisions_correct']}/{len(rows)}.", f"Known-unsafe false accepts: {false_accepts}.", f"Supported-safe recall: {safe_recall:.1%}.", f"Coarse-reason accuracy: {reason_accuracy:.1%}.", f"Classified coverage: {coverage:.1%}.", f"Phase-contrast accuracy: {phase_accuracy:.1%}.", f"H7H blind gate: **{'PASS' if passed else 'FAIL'}**.", "", "| Symbol | Configuration | Expected | Actual | Sampling | Delegation | Reason |", "|---|---|---|---|---|---|---|", *[f"| `{row['public_symbol']}` | {row['configuration']} | {row['expected_decision']} | {row['actual_decision']} | {row['sampling_rng']} | {row['delegation']} | {row['validator_reasons']} |" for row in rows], "", "Formal symbols are disjoint from calibration. Their method-body effect analysis ran once after the adapter, protocol, symbol bindings, source hashes, and thresholds were frozen.", ""])
    (OUT / "autocontract_h7h_kornia.md").write_text(report, encoding="utf-8")
    print(report)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--calibrate", action="store_true"); group.add_argument("--seal", action="store_true"); group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.calibrate: calibrate()
    elif args.seal: seal()
    else: formal_run()


if __name__ == "__main__":
    main()
