"""EffectV5 calibration on completed TorchIO and audiomentations corpora.

EffectV5 makes execution state configuration-aware.  It detects attribute,
subscript, and container-mutation paths; distinguishes replayable parameters
from cache/control state; records required runtime modes; and audits super()
hook resolution across the package class graph.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import autocontract_h6_effect_v2 as v2
import autocontract_h7d_effect_v4 as v4
import autocontract_h7e_audiomentations as h7e


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
StatePathKind = Literal["attribute", "subscript", "container_mutation"]
StateRole = Literal[
    "call_local", "replayable", "cache", "persistent_control", "unknown"
]
RequiredMode = Literal["parameters_unfrozen", "framework_specific", "unknown"]
SuperResolution = Literal["complete", "partial", "unknown"]
MUTATORS = frozenset(
    ("append", "clear", "extend", "insert", "pop", "remove", "setdefault", "update")
)
HOOKS = frozenset(("__call__", "apply", "randomize_parameters"))


@dataclass(frozen=True)
class StateAccess:
    path: str
    kind: StatePathKind


@dataclass(frozen=True)
class EffectV5:
    base: v4.EffectV4
    state_accesses: tuple[StateAccess, ...]
    state_roles: frozenset[StateRole]
    required_modes: frozenset[RequiredMode]
    refresh_before_use: bool
    super_resolution: SuperResolution


@dataclass(frozen=True)
class AnalysisV5:
    status: Literal["resolved", "unknown"]
    effect: EffectV5
    reasons: tuple[str, ...]
    adapter: str
    evidence: tuple[str, ...]


V5_RULES = (
    "state writes include self attributes, self-container subscripts, and container mutators",
    "self.parameters guarded by are_parameters_frozen is replayable state",
    "replayable state is admissible only when refresh-before-use and the required mode hold",
    "other indexed runtime state is cache/control state and remains fail-closed",
    "super() execution hooks must resolve across the package class graph",
    "mode guards are contract obligations, not undocumented evaluator assumptions",
)


def state_root(node: ast.AST) -> str:
    current = node
    while isinstance(current, ast.Subscript):
        current = current.value
    chain = v2.corpus_v1.attribute_chain(current)
    return chain if chain.startswith("self.") else ""


def state_accesses(nodes: list[ast.AST]) -> tuple[StateAccess, ...]:
    found: set[tuple[str, StatePathKind]] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Subscript):
                        if path := state_root(target):
                            found.add((path, "subscript"))
                    else:
                        chain = v2.corpus_v1.attribute_chain(target)
                        if chain.startswith("self."):
                            found.add((chain, "attribute"))
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                chain = v2.corpus_v1.attribute_chain(child.func)
                parts = chain.split(".")
                if len(parts) >= 3 and parts[0] == "self" and parts[-1] in MUTATORS:
                    found.add((".".join(parts[:-1]), "container_mutation"))
    return tuple(StateAccess(path, kind) for path, kind in sorted(found))


def all_hook_nodes(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.AST]:
    result: list[ast.AST] = []
    seen: set[int] = set()
    for cls in v2.class_chain(root, classes):
        for name, method in v2.method_map(cls).items():
            if name in HOOKS and id(method) not in seen:
                result.append(method)
                seen.add(id(method))
    return result


def has_parameter_mode_guard(nodes: list[ast.AST]) -> bool:
    for node in nodes:
        for child in ast.walk(node):
            if not isinstance(child, ast.If):
                continue
            condition = ast.unparse(child.test)
            if "are_parameters_frozen" not in condition:
                continue
            if any(
                isinstance(item, ast.Call)
                and v2.corpus_v1.simple_name(item.func) == "randomize_parameters"
                for statement in child.body
                for item in ast.walk(statement)
            ):
                return True
    return False


def super_resolution(
    root: ast.ClassDef, classes: dict[str, ast.ClassDef]
) -> SuperResolution:
    chain = v2.class_chain(root, classes)
    owner_index = {id(cls): index for index, cls in enumerate(chain)}
    saw_super = False
    for cls in chain:
        index = owner_index[id(cls)]
        ancestors = chain[index + 1 :]
        for name, method in v2.method_map(cls).items():
            if name not in HOOKS:
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
                saw_super = True
                target = child.func.attr
                if not any(target in v2.method_map(parent) for parent in ancestors):
                    return "partial"
    return "complete" if saw_super or chain else "unknown"


def classify_state(
    accesses: tuple[StateAccess, ...], mode_guard: bool
) -> tuple[frozenset[StateRole], frozenset[RequiredMode]]:
    paths = {item.path for item in accesses}
    roles: set[StateRole] = set()
    modes: set[RequiredMode] = set()
    if "self.parameters" in paths:
        if mode_guard:
            roles.add("replayable")
            modes.add("parameters_unfrozen")
        else:
            roles.add("unknown")
            modes.add("unknown")
    for path in paths - {"self.parameters"}:
        lowered = path.lower()
        if any(token in lowered for token in ("cache", "buffer", "history", "time_info")):
            roles.add("cache")
        else:
            roles.add("persistent_control")
    return frozenset(roles), frozenset(modes)


def infer_audiomentations_v5(
    unit: h7e.Unit,
    binding: dict[str, object],
    classes: dict[str, ast.ClassDef],
    ambiguous: set[str],
) -> AnalysisV5:
    prior = h7e.analyze_unit(unit, binding, classes, ambiguous)
    root = h7e.target_class(unit, binding)
    if root is None:
        effect = EffectV5(prior.effect, (), frozenset(("unknown",)), frozenset(("unknown",)), False, "unknown")
        return AnalysisV5("unknown", effect, prior.reasons, "audiomentations-v5", prior.evidence)

    nodes = all_hook_nodes(root, classes)
    accesses = state_accesses(nodes)
    guarded = has_parameter_mode_guard(nodes)
    roles, modes = classify_state(accesses, guarded)
    super_status = super_resolution(root, classes)
    base_v3 = prior.effect.base
    if base_v3 is not None:
        base_v3 = replace(base_v3, execution_state_writes=bool(accesses))
    base_v4 = replace(prior.effect, base=base_v3)
    reasons = list(prior.reasons)
    if super_status != "complete":
        reasons.append("partial_super_resolution")
    effect = EffectV5(
        base_v4,
        accesses,
        roles,
        modes,
        guarded,
        super_status,
    )
    status = "unknown" if reasons else "resolved"
    evidence = prior.evidence + (
        "state_paths:" + (",".join(f"{item.kind}:{item.path}" for item in accesses) or "none"),
        "state_roles:" + (",".join(sorted(roles)) or "none"),
        "required_modes:" + (",".join(sorted(modes)) or "none"),
        f"refresh_before_use:{str(guarded).lower()}",
        f"super_resolution:{super_status}",
    )
    return AnalysisV5(
        status,
        effect,
        tuple(dict.fromkeys(reasons)),
        "audiomentations-v5",
        evidence,
    )


def wrap_v4(result: v4.AnalysisV4) -> AnalysisV5:
    stateful = result.effect.base is not None and result.effect.base.execution_state_writes
    roles: frozenset[StateRole] = (
        frozenset(("persistent_control",)) if stateful else frozenset()
    )
    effect = EffectV5(
        result.effect,
        (),
        roles,
        frozenset(),
        False,
        "complete",
    )
    return AnalysisV5(result.status, effect, result.reasons, result.adapter, result.evidence)


def validator_v5(
    result: AnalysisV5, active_modes: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    reasons = list(result.reasons)
    base = result.effect.base.base
    if base is not None:
        if base.input_cardinality != "one" or base.output_cardinality != "one":
            reasons.append(
                f"unsupported_cardinality:{base.input_cardinality}->{base.output_cardinality}"
            )
        if base.sample_identity == "combine":
            reasons.append("combined_sample_identity")
        if base.execution_external_reads or base.execution_external_writes:
            reasons.append("execution_external_effect")

    roles = result.effect.state_roles
    if "cache" in roles:
        reasons.append("execution_cache_state")
    if "persistent_control" in roles:
        reasons.append("execution_control_state")
    if "unknown" in roles:
        reasons.append("unknown_state_semantics")
    if "replayable" in roles:
        required = set(result.effect.required_modes)
        if not result.effect.refresh_before_use or not required.issubset(active_modes):
            missing = "+".join(sorted(required - set(active_modes))) or "refresh_before_use"
            reasons.append("unsatisfied_mode_guard:" + missing)
    return tuple(dict.fromkeys(reasons))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows: list[dict[str, object]] = []

    torchio_protocol = v4.h7c.load_protocol()
    common = torchio_protocol["adapter_calibration"]["common_files"]
    for unit in v4.expected_units():
        prior = v4.infer_v4(unit["name"], unit["path"], common)
        result = wrap_v4(prior)
        reasons = validator_v5(result)
        decision = "reject" if reasons else "admit"
        reason_match = (
            not reasons
            if unit["reason"] == "none"
            else any(unit["reason"] in reason for reason in reasons)
        )
        rows.append(
            {
                "corpus": "TorchIO",
                "unit": unit["name"],
                "expected": unit["expected"],
                "actual": decision,
                "decision_correct": decision == unit["expected"],
                "reason_match": reason_match,
                "state_roles": ";".join(sorted(result.effect.state_roles)) or "none",
                "required_modes": "none",
                "super_resolution": result.effect.super_resolution,
                "reasons": ";".join(reasons) or "none",
            }
        )

    protocol = json.loads(h7e.PROTOCOL.read_text(encoding="utf-8"))
    bindings = h7e.symbol_bindings()
    classes, ambiguous = h7e.package_classes()
    active_modes = frozenset(("parameters_unfrozen",))
    state_oracle = {
        "audiomentations.Normalize": frozenset(("replayable",)),
        "audiomentations.PolarityInversion": frozenset(("replayable",)),
        "audiomentations.AddGaussianNoise": frozenset(("replayable",)),
        "audiomentations.Clip": frozenset(("replayable",)),
        "audiomentations.Lambda": frozenset(("replayable",)),
        "audiomentations.Compose": frozenset(),
        "audiomentations.AddBackgroundNoise": frozenset(("replayable", "cache")),
    }
    state_correct = 0
    for unit in h7e.protocol_units():
        result = infer_audiomentations_v5(unit, bindings[unit.public_symbol], classes, ambiguous)
        reasons = validator_v5(result, active_modes)
        decision = "reject" if reasons else "admit"
        reason_match = (
            not reasons
            if unit.coarse_reason == "none"
            else any(unit.coarse_reason in reason for reason in reasons)
        )
        oracle_match = result.effect.state_roles == state_oracle[unit.public_symbol]
        state_correct += oracle_match
        rows.append(
            {
                "corpus": "audiomentations",
                "unit": unit.public_symbol,
                "expected": unit.expected,
                "actual": decision,
                "decision_correct": decision == unit.expected,
                "reason_match": reason_match,
                "state_roles": ";".join(sorted(result.effect.state_roles)) or "none",
                "required_modes": ";".join(sorted(result.effect.required_modes)) or "none",
                "super_resolution": result.effect.super_resolution,
                "reasons": ";".join(reasons) or "none",
            }
        )

    write_csv(OUT / "autocontract_h7f_v5_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reason_correct = sum(row["reason_match"] is True for row in rows)
    super_complete = sum(row["super_resolution"] == "complete" for row in rows)
    ready = (
        correct == len(rows)
        and reason_correct == len(rows)
        and state_correct == len(state_oracle)
        and super_complete == len(rows)
    )
    summary = {
        "units": len(rows),
        "decisions_correct": correct,
        "reason_categories_correct": reason_correct,
        "audiomentations_state_roles_correct": state_correct,
        "super_resolution_complete": super_complete,
        "effect_v5_freeze_ready": ready,
    }
    write_csv(OUT / "autocontract_h7f_v5_summary.csv", [summary])
    manifest = {
        "schema": {
            "state_path_kinds": ["attribute", "subscript", "container_mutation"],
            "state_roles": [
                "call_local",
                "replayable",
                "cache",
                "persistent_control",
                "unknown",
            ],
            "required_modes": ["parameters_unfrozen", "framework_specific", "unknown"],
            "super_resolution": ["complete", "partial", "unknown"],
        },
        "rules": V5_RULES,
        "calibration_corpora": ["TorchIO", "audiomentations"],
        "active_calibration_modes": sorted(active_modes),
    }
    (OUT / "autocontract_h7f_v5_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    report = "\n".join(
        [
            "# AutoContract EffectV5 calibration",
            "",
            f"Decisions: {correct}/{len(rows)}; reason categories: {reason_correct}/{len(rows)}.",
            f"audiomentations state roles: {state_correct}/{len(state_oracle)}.",
            f"Complete super resolution: {super_complete}/{len(rows)}.",
            f"Freeze ready: **{'YES' if ready else 'NO'}**.",
            "",
            "| Corpus | Unit | State roles | Required modes | Decision | Reason |",
            "|---|---|---|---|---|---|",
            *[
                f"| {row['corpus']} | `{row['unit']}` | {row['state_roles']} | "
                f"{row['required_modes']} | {row['actual']} | {row['reasons']} |"
                for row in rows
            ],
            "",
        ]
    )
    (OUT / "autocontract_h7f_v5_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if not ready:
        raise RuntimeError("EffectV5 is not freeze-ready")


if __name__ == "__main__":
    main()
