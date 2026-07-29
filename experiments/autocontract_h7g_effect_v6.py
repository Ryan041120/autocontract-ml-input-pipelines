"""EffectV6 calibration on TorchIO, audiomentations, and imgaug.

V6 adds delegated object mutation, constructor-to-super callable provenance,
and named mode obligations.  It is calibrated only on completed corpora and
does not modify any frozen H7E/H7F result.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import autocontract_h7d_effect_v4 as v4
import autocontract_h7e_audiomentations as h7e
import autocontract_h7f_effect_v5 as v5
import autocontract_h7f_imgaug as h7f
import autocontract_h7f_posthoc_callable_origin as origin


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
StatePathKindV6 = Literal[
    "attribute", "subscript", "container_mutation", "delegated_mutation"
]
CallableOrigin = Literal[
    "module_bound",
    "public_input",
    "public_input_derived",
    "child_operator",
    "external_dynamic",
    "unknown",
]
ModeRelation = Literal["required", "ensured"]
GuardKind = Literal["refresh_before_use", "conditional_restore", "intrinsic", "unknown"]


@dataclass(frozen=True)
class StateAccessV6:
    path: str
    kind: StatePathKindV6


@dataclass(frozen=True)
class CallableBinding:
    attribute: str
    origin: CallableOrigin


@dataclass(frozen=True)
class ModeObligation:
    name: str
    relation: ModeRelation
    guard_kind: GuardKind


@dataclass(frozen=True)
class EffectV6:
    base: v5.EffectV5
    state_accesses: tuple[StateAccessV6, ...]
    callable_bindings: tuple[CallableBinding, ...]
    mode_obligations: tuple[ModeObligation, ...]


@dataclass(frozen=True)
class AnalysisV6:
    status: Literal["resolved", "unknown"]
    effect: EffectV6
    reasons: tuple[str, ...]
    adapter: str
    evidence: tuple[str, ...]


V6_RULES = (
    "method calls that advance a stored RNG are delegated_mutation, not container mutation",
    "callable provenance propagates from public constructor parameters through local assignments and super().__init__",
    "module-bound callables may be analyzed further; public-input and public-input-derived callables fail closed",
    "mode obligations use stable framework-qualified names rather than the framework_specific placeholder",
    "required modes must be supplied by the rewrite context; ensured modes are discharged by the operator itself",
    "cache, control, unknown state, child delegation, and external effects remain fail closed",
)


def state_accesses_v6(base: v5.EffectV5) -> tuple[StateAccessV6, ...]:
    result: list[StateAccessV6] = []
    for item in base.state_accesses:
        kind: StatePathKindV6 = item.kind
        if item.path == "self.random_state" and item.kind == "container_mutation":
            kind = "delegated_mutation"
        result.append(StateAccessV6(item.path, kind))
    return tuple(result)


def named_obligations(base: v5.EffectV5, framework: str) -> tuple[ModeObligation, ...]:
    if "replayable" not in base.state_roles:
        return ()
    if framework == "imgaug":
        return (ModeObligation("imgaug.deterministic", "required", "conditional_restore"),)
    if framework == "audiomentations":
        return (
            ModeObligation(
                "audiomentations.parameters_unfrozen",
                "required",
                "refresh_before_use",
            ),
        )
    return ()


def callable_bindings_imgaug(
    binding: dict[str, object], classes: dict[str, ast.ClassDef]
) -> tuple[CallableBinding, ...]:
    root = h7f.target_class(binding)
    if root is None:
        return (CallableBinding("<missing>", "unknown"),)
    functions = origin.module_functions()
    attrs = origin.constructor_origins(root, {**classes, root.name: root}, functions)
    invoked = h7f.invoked_self_attrs(h7f.execution_nodes(root, classes))
    candidates = sorted(
        attr
        for attr in invoked & set(attrs)
        if any(token in attr.lower() for token in h7f.CALLABLE_PARAM_TOKENS)
    )
    mapping: dict[str, CallableOrigin] = {
        "module_symbol": "module_bound",
        "user_input": "public_input",
        "user_derived": "public_input_derived",
        "internal": "module_bound",
        "unknown": "unknown",
    }
    return tuple(CallableBinding(attr, mapping[attrs[attr]]) for attr in candidates)


def infer_imgaug_v6(
    binding: dict[str, object], classes: dict[str, ast.ClassDef]
) -> AnalysisV6:
    prior = h7f.analyze(binding, classes)
    callables = callable_bindings_imgaug(binding, classes)
    dynamic = any(
        item.origin in ("public_input", "public_input_derived", "external_dynamic", "unknown")
        for item in callables
    )
    reasons = list(prior.reasons)
    if "unresolved_user_callable" in reasons and not dynamic and callables:
        reasons.remove("unresolved_user_callable")
    if dynamic and "unresolved_user_callable" not in reasons:
        reasons.append("unresolved_user_callable")
    effect = EffectV6(
        prior.effect,
        state_accesses_v6(prior.effect),
        callables,
        named_obligations(prior.effect, "imgaug"),
    )
    evidence = prior.evidence + (
        "callable_origins:"
        + (",".join(f"{item.attribute}={item.origin}" for item in callables) or "none"),
        "named_modes:"
        + (",".join(item.name for item in effect.mode_obligations) or "none"),
    )
    return AnalysisV6(
        "unknown" if reasons else "resolved",
        effect,
        tuple(dict.fromkeys(reasons)),
        "imgaug-v6",
        evidence,
    )


def wrap_v5(prior: v5.AnalysisV5, framework: str) -> AnalysisV6:
    effect = EffectV6(
        prior.effect,
        state_accesses_v6(prior.effect),
        (),
        named_obligations(prior.effect, framework),
    )
    return AnalysisV6(prior.status, effect, prior.reasons, prior.adapter + "-v6", prior.evidence)


def validator_v6(
    result: AnalysisV6,
    active_named_modes: frozenset[str] = frozenset(),
    active_legacy_modes: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    # AnalysisV5 carries reasons outside EffectV5, so rebuild a view with the V6 reasons.
    base_view = v5.AnalysisV5(
        "unknown" if result.reasons else "resolved",
        result.effect.base,
        result.reasons,
        result.adapter,
        result.evidence,
    )
    reasons = list(v5.validator_v5(base_view, active_legacy_modes))
    for obligation in result.effect.mode_obligations:
        if obligation.relation == "required" and obligation.name not in active_named_modes:
            reasons.append("unsatisfied_named_mode:" + obligation.name)
    if "replayable" in result.effect.base.state_roles and not result.effect.mode_obligations:
        reasons.append("missing_named_mode_obligation")
    for binding in result.effect.callable_bindings:
        if binding.origin in (
            "public_input",
            "public_input_derived",
            "external_dynamic",
            "unknown",
        ):
            reasons.append("unresolved_callable_origin:" + binding.origin)
    return tuple(dict.fromkeys(reasons))


def reason_match(expected: str, reasons: tuple[str, ...]) -> bool:
    return not reasons if expected == "none" else any(expected in item for item in reasons)


def row_for(
    corpus: str,
    symbol: str,
    expected: str,
    expected_reason: str,
    result: AnalysisV6,
    active_named: frozenset[str],
    active_legacy: frozenset[str],
) -> dict[str, object]:
    reasons = validator_v6(result, active_named, active_legacy)
    decision = "reject" if reasons else "admit"
    return {
        "corpus": corpus,
        "unit": symbol,
        "expected": expected,
        "actual": decision,
        "decision_correct": decision == expected,
        "reason_match": reason_match(expected_reason, reasons),
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
        "reasons": ";".join(reasons) or "none",
    }


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
        prior = v5.wrap_v4(v4.infer_v4(unit["name"], unit["path"], common))
        result = wrap_v5(prior, "torchio")
        rows.append(
            row_for(
                "TorchIO",
                unit["name"],
                unit["expected"],
                unit["reason"],
                result,
                frozenset(),
                frozenset(),
            )
        )

    bindings = h7e.symbol_bindings()
    audio_classes, ambiguous = h7e.package_classes()
    for unit in h7e.protocol_units():
        prior = v5.infer_audiomentations_v5(
            unit, bindings[unit.public_symbol], audio_classes, ambiguous
        )
        result = wrap_v5(prior, "audiomentations")
        rows.append(
            row_for(
                "audiomentations",
                unit.public_symbol,
                unit.expected,
                unit.coarse_reason,
                result,
                frozenset(("audiomentations.parameters_unfrozen",)),
                frozenset(("parameters_unfrozen",)),
            )
        )

    imgaug_classes = h7f.package_classes()
    imgaug_units = [h7f.Unit(*item) for item in h7f.CALIBRATION_UNITS]
    imgaug_units.extend(h7f.protocol_units())
    formal_bindings = {
        item["public_symbol"]: item
        for item in json.loads(h7f.SYMBOLS.read_text(encoding="utf-8"))["bindings"]
    }
    for unit in imgaug_units:
        binding = formal_bindings.get(unit.public_symbol) or h7f.public_binding(unit.public_symbol)
        result = infer_imgaug_v6(binding, imgaug_classes)
        rows.append(
            row_for(
                "imgaug",
                unit.public_symbol,
                unit.expected,
                unit.coarse_reason,
                result,
                frozenset(("imgaug.deterministic",)),
                frozenset(("framework_specific",)),
            )
        )

    write_csv(OUT / "autocontract_h7g_v6_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reason_correct = sum(row["reason_match"] is True for row in rows)
    linear = next(row for row in rows if row["unit"].endswith("LinearContrast"))
    lambda_rows = [row for row in rows if row["unit"].endswith(("Lambda", "AssertLambda"))]
    delegated = [
        row for row in rows if "delegated_mutation:self.random_state" in row["state_accesses"]
    ]
    named = [row for row in rows if row["named_modes"] != "none"]
    ready = (
        correct == len(rows)
        and reason_correct == len(rows)
        and linear["callable_origins"] == "func=module_bound"
        and linear["actual"] == "admit"
        and all(row["actual"] == "reject" for row in lambda_rows)
        and bool(delegated)
        and bool(named)
    )
    summary = {
        "units": len(rows),
        "decisions_correct": correct,
        "reason_categories_correct": reason_correct,
        "delegated_mutation_units": len(delegated),
        "named_mode_units": len(named),
        "linear_contrast_origin": linear["callable_origins"],
        "effect_v6_freeze_ready": ready,
    }
    write_csv(OUT / "autocontract_h7g_v6_summary.csv", [summary])
    manifest = {
        "schema": {
            "state_path_kinds": [
                "attribute",
                "subscript",
                "container_mutation",
                "delegated_mutation",
            ],
            "callable_origins": [
                "module_bound",
                "public_input",
                "public_input_derived",
                "child_operator",
                "external_dynamic",
                "unknown",
            ],
            "mode_relations": ["required", "ensured"],
            "guard_kinds": [
                "refresh_before_use",
                "conditional_restore",
                "intrinsic",
                "unknown",
            ],
        },
        "rules": V6_RULES,
        "calibration_corpora": ["TorchIO", "audiomentations", "imgaug"],
    }
    (OUT / "autocontract_h7g_v6_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    report = "\n".join(
        [
            "# AutoContract EffectV6 calibration",
            "",
            f"Decisions: {correct}/{len(rows)}; reason categories: {reason_correct}/{len(rows)}.",
            f"Delegated-mutation units: {len(delegated)}; named-mode units: {len(named)}.",
            f"LinearContrast origin: `{linear['callable_origins']}`; decision: {linear['actual']}.",
            f"Freeze ready: **{'YES' if ready else 'NO'}**.",
            "",
            "| Corpus | Unit | State | Callable | Mode | Decision | Reason |",
            "|---|---|---|---|---|---|---|",
            *[
                f"| {row['corpus']} | `{row['unit']}` | {row['state_accesses']} | "
                f"{row['callable_origins']} | {row['named_modes']} | {row['actual']} | "
                f"{row['reasons']} |"
                for row in rows
            ],
            "",
        ]
    )
    (OUT / "autocontract_h7g_v6_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if not ready:
        raise RuntimeError("EffectV6 is not freeze-ready")


if __name__ == "__main__":
    main()
