"""Frozen H7E audiomentations adapter and one-shot holdout evaluator.

This adapter was written from public audiomentations documentation and the
sealed symbol-origin manifest.  It contains framework-level structural rules,
not operator-name labels.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7
import autocontract_h7d_effect_v4 as v4


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = (
    ROOT
    / ".research"
    / "semantics_safe_reconfiguration"
    / "h7e_corpus"
    / "audiomentations_repo"
)
PROTOCOL = OUT / "autocontract_h7e_protocol.json"
SYMBOLS = OUT / "autocontract_h7e_symbol_manifest.json"
ADAPTER_MANIFEST = OUT / "autocontract_h7e_adapter_manifest.json"
FREEZE = OUT / "autocontract_h7e_freeze.json"

HOOKS = frozenset(("__call__", "apply", "randomize_parameters"))
EXTERNAL_AUDIO_TOKENS = frozenset(
    (
        "audio_file",
        "audio_file_path",
        "load_audio",
        "load_sound_file",
        "sound_file_paths",
        "sounds_path",
    )
)
CLASSIFIED_REASONS = frozenset(
    ("unresolved_child_effect", "unresolved_user_callable", "execution_external_effect")
)
ADAPTER_RULES = (
    "Base waveform __call__ plus apply/randomize_parameters are execution hooks",
    "samples and sample_rate form a fixed two-field input scope and samples is the output field",
    "Python/NumPy random calls are direct RNG effects",
    "stored-callable invocation is unresolved user-callable delegation",
    "iteration and invocation over self.transforms is unresolved child-operator delegation",
    "file-path/audio-loader tokens denote a filesystem-backed external operand",
    "writes to self attributes during execution remain EffectV4 execution-state writes",
)


@dataclass(frozen=True)
class Unit:
    public_symbol: str
    expected: str
    coarse_reason: str

    @property
    def name(self) -> str:
        return self.public_symbol.rsplit(".", 1)[-1]


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


def protocol_units() -> list[Unit]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    return [Unit(**item) for item in protocol["sealed_units"]]


def symbol_bindings() -> dict[str, dict[str, object]]:
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    return {item["public_symbol"]: item for item in manifest["bindings"]}


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    files = {
        "effect_v4_sha256": Path(v4.__file__),
        "symbol_sealer_sha256": ROOT / "experiments" / "autocontract_symbol_origin.py",
        "adapter_sha256": Path(__file__),
        "adapter_manifest_sha256": ADAPTER_MANIFEST,
        "protocol_sha256": PROTOCOL,
        "symbol_manifest_sha256": SYMBOLS,
    }
    for key, path in files.items():
        actual = digest(path)
        if freeze[key] != actual:
            raise RuntimeError(f"H7E freeze violation for {key}: {actual}")
    actual_revision = repository_revision()
    if actual_revision != freeze["repository_commit"]:
        raise RuntimeError(f"H7E repository revision changed: {actual_revision}")
    for binding in symbol_bindings().values():
        path = REPO / str(binding["source_path"])
        actual = digest(path)
        if actual != binding["source_sha256"]:
            raise RuntimeError(f"H7E source hash changed: {binding['public_symbol']}")
    return freeze


def package_classes() -> tuple[dict[str, ast.ClassDef], set[str]]:
    candidates: dict[str, list[ast.ClassDef]] = {}
    for path in sorted((REPO / "audiomentations").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes, _ = v2.top_definitions(tree)
        for name, cls in classes.items():
            candidates.setdefault(name, []).append(cls)
    unique = {name: items[0] for name, items in candidates.items() if len(items) == 1}
    ambiguous = {name for name, items in candidates.items() if len(items) > 1}
    return unique, ambiguous


def target_class(unit: Unit, binding: dict[str, object]) -> ast.ClassDef | None:
    path = REPO / str(binding["source_path"])
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes, _ = v2.top_definitions(tree)
    return classes.get(str(binding["defining_name"]))


def construction_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    return [
        method
        for cls in v2.class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in v2.CONSTRUCTION_METHODS
    ]


def execution_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    nodes = h7.execution_nodes(root, classes, "__call__")
    if nodes:
        return nodes
    return [
        method
        for cls in v2.class_chain(root, classes)
        for name, method in v2.method_map(cls).items()
        if name in HOOKS
    ]


def assigned_callable_attrs(construction: list[ast.AST]) -> set[str]:
    attrs: set[str] = set()
    for node in construction:
        for child in ast.walk(node):
            if not isinstance(child, ast.Assign):
                continue
            if not isinstance(child.value, ast.Name):
                continue
            for target in child.targets:
                chain = v2.corpus_v1.attribute_chain(target)
                if chain == f"self.{child.value.id}":
                    attrs.add(child.value.id)
    return attrs


def invoked_self_attrs(execution: list[ast.AST]) -> set[str]:
    attrs: set[str] = set()
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            chain = v2.corpus_v1.attribute_chain(child.func)
            if chain.startswith("self.") and chain.count(".") == 1:
                attrs.add(chain.split(".", 1)[1])
    return attrs


def has_child_delegation(execution: list[ast.AST]) -> bool:
    for node in execution:
        for child in ast.walk(node):
            if not isinstance(child, ast.For):
                continue
            iterator = v2.corpus_v1.attribute_chain(child.iter)
            target = child.target.id if isinstance(child.target, ast.Name) else None
            if not target or iterator != "self.transforms":
                continue
            if any(
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id == target
                for item in ast.walk(child)
            ):
                return True
    rendered = "\n".join(ast.unparse(node) for node in execution)
    return "self.transforms" in rendered and "transform(" in rendered


def has_external_audio_operand(construction: list[ast.AST], execution: list[ast.AST]) -> bool:
    tokens = v2.corpus_v1.identifier_tokens(construction + execution)
    return bool(tokens & EXTERNAL_AUDIO_TOKENS)


def analyze_unit(
    unit: Unit,
    binding: dict[str, object],
    classes: dict[str, ast.ClassDef],
    ambiguous_classes: set[str],
) -> v4.AnalysisV4:
    root = target_class(unit, binding)
    if root is None:
        return v4.AnalysisV4(
            "unknown",
            v4.EffectV4(None, "unknown", "none"),
            ("sealed_definition_missing",),
            "audiomentations",
            (),
        )
    if any(base in ambiguous_classes for base in v2.base_names(root)):
        return v4.AnalysisV4(
            "unknown",
            v4.EffectV4(None, "unknown", "none"),
            ("ambiguous_base_class",),
            "audiomentations",
            (),
        )

    construction = construction_nodes(root, classes)
    execution = execution_nodes(root, classes)
    if not execution:
        return v4.AnalysisV4(
            "unknown",
            v4.EffectV4(None, "fixed_fields", "none"),
            ("missing_waveform_execution_hook",),
            "audiomentations",
            (),
        )

    callable_attrs = assigned_callable_attrs(construction) & invoked_self_attrs(execution)
    child_delegation = has_child_delegation(execution)
    if child_delegation:
        delegation: v4.DelegationKind = "child_operator"
    elif callable_attrs:
        delegation = "user_callable"
    else:
        delegation = "none"

    external = has_external_audio_operand(construction, execution)
    construction_reads, construction_writes = v2.external_effects(construction)
    execution_reads, execution_writes = v2.external_effects(execution)
    if external:
        execution_reads = execution_reads | frozenset(("filesystem",))
    stateful, state_attrs = h7.execution_state_writes(execution)
    base = h7.EffectV3(
        construction_reads,
        construction_writes,
        v2.self_state_write(construction),
        v2.rng_sources(construction),
        frozenset(("samples", "sample_rate")),
        frozenset(("samples",)),
        execution_reads,
        execution_writes,
        v2.rng_sources(execution),
        delegation != "none",
        "fixed",
        False,
        "one",
        "one",
        "preserve",
        stateful,
    )
    reasons: list[str] = []
    if delegation == "child_operator":
        reasons.append("unresolved_child_effect")
    elif delegation == "user_callable":
        reasons.append("unresolved_user_callable")
    status = "unknown" if reasons else "resolved"
    effect = v4.EffectV4(base, "fixed_fields", delegation)
    evidence = (
        "entrypoint:waveform-__call__->randomize_parameters/apply",
        "record_scope:fixed_fields:samples+sample_rate",
        f"delegation:{delegation}",
        f"external_audio_operand:{str(external).lower()}",
    ) + tuple(f"execution_state:{attr}" for attr in state_attrs)
    return v4.AnalysisV4(
        status, effect, tuple(reasons), "audiomentations", evidence
    )


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
    bindings = symbol_bindings()
    classes, ambiguous_classes = package_classes()
    rows: list[dict[str, object]] = []

    for unit in protocol_units():
        binding = bindings[unit.public_symbol]
        result = analyze_unit(unit, binding, classes, ambiguous_classes)
        reasons = v4.validator_v4(result)
        decision = "reject" if reasons else "admit"
        coarse_match = (
            not reasons
            if unit.coarse_reason == "none"
            else any(unit.coarse_reason in reason for reason in reasons)
        )
        classified = result.status == "resolved" or any(
            any(category in reason for category in CLASSIFIED_REASONS)
            for reason in reasons
        )
        state_attrs = [
            item.split(":", 1)[1]
            for item in result.evidence
            if item.startswith("execution_state:")
        ]
        rows.append(
            {
                "public_symbol": unit.public_symbol,
                "expected_decision": unit.expected,
                "actual_decision": decision,
                "decision_correct": decision == unit.expected,
                "expected_coarse_reason": unit.coarse_reason,
                "coarse_reason_match": coarse_match,
                "classified": classified,
                "status": result.status,
                "record_scope": result.effect.record_scope,
                "delegation_kind": result.effect.delegation_kind,
                "execution_state_attrs": ";".join(state_attrs) or "none",
                "validator_reasons": ";".join(reasons) or "none",
                "source_binding_sha256": binding["binding_sha256"],
                "evidence": ";".join(result.evidence) or "none",
            }
        )

    safe = [row for row in rows if row["expected_decision"] == "admit"]
    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    false_accepts = sum(row["actual_decision"] == "admit" for row in unsafe)
    safe_recall = sum(row["actual_decision"] == "admit" for row in safe) / len(safe)
    coarse_accuracy = sum(row["coarse_reason_match"] is True for row in rows) / len(rows)
    classified_coverage = sum(row["classified"] is True for row in rows) / len(rows)
    binding_integrity = sum(
        binding["status"] == "resolved" for binding in bindings.values()
    ) / len(bindings)
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
        "h7e_blind_gate_pass": passed,
        "adapter_sha256": freeze["adapter_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
        "symbol_manifest_sha256": freeze["symbol_manifest_sha256"],
    }
    write_csv(OUT / "autocontract_h7e_audiomentations.csv", rows)
    write_csv(OUT / "autocontract_h7e_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7E audiomentations holdout",
            "",
            f"Binding integrity: {binding_integrity:.1%}.",
            f"Decisions correct: {summary['decisions_correct']}/{len(rows)}.",
            f"Known-unsafe false accepts: {false_accepts}.",
            f"Supported-safe recall: {safe_recall:.1%}.",
            f"Coarse-reason accuracy: {coarse_accuracy:.1%}.",
            f"Classified coverage: {classified_coverage:.1%}.",
            f"H7E blind gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "| Symbol | Status | Expected | Actual | State | Reason |",
            "|---|---|---|---|---|---|",
            *[
                f"| `{row['public_symbol']}` | {row['status']} | {row['expected_decision']} | "
                f"{row['actual_decision']} | {row['execution_state_attrs']} | {row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "The protocol, symbol bindings, adapter, and thresholds were frozen before operator bodies were inspected by the adapter author.",
            "",
        ]
    )
    (OUT / "autocontract_h7e_audiomentations.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
