"""EffectV4 calibration from the completed H7C TorchIO corpus.

EffectV4 adds record scope and delegation kind without modifying any frozen
H7/H7C analyzer.  The rules are structural rather than operator-name labels.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import autocontract_h7_adapters as h7
import autocontract_h7c_torchio as h7c


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
RecordScope = Literal["whole_record", "typed_subrecord", "fixed_fields", "unknown"]
DelegationKind = Literal[
    "none", "child_operator", "user_callable", "framework_bridge", "backend_graph"
]


@dataclass(frozen=True)
class EffectV4:
    base: h7.EffectV3 | None
    record_scope: RecordScope
    delegation_kind: DelegationKind


@dataclass(frozen=True)
class AnalysisV4:
    status: Literal["resolved", "unknown"]
    effect: EffectV4
    reasons: tuple[str, ...]
    adapter: str
    evidence: tuple[str, ...]


V4_RULES = (
    "whole-record and typed-subrecord scopes are closed rewrite domains",
    "dynamic fields without a framework record summary remain unknown scope",
    "iteration over stored transforms denotes child-operator delegation",
    "stored arbitrary callable invocation denotes user-callable delegation",
    "framework loader plus wrapped transform invocation denotes framework bridge",
    "backend graph construction denotes backend-graph delegation",
)


def source_features(source: str) -> tuple[set[str], str]:
    tree = ast.parse(source)
    tokens = h7.v2.corpus_v1.identifier_tokens([tree])
    rendered = ast.unparse(tree)
    return tokens, rendered


def structural_delegation(source: str) -> DelegationKind:
    tokens, rendered = source_features(source)
    child_storage = "self.transforms" in rendered or "self.transforms_dict" in rendered
    child_call = "transform(subject)" in rendered
    if child_storage and child_call:
        return "child_operator"

    framework_loader = bool(tokens & {"get_monai", "get_tensorflow", "get_dali"})
    wrapped_transform = bool(tokens & {"monai_transform", "framework_transform"})
    if framework_loader and wrapped_transform:
        return "framework_bridge"

    callable_storage = bool(tokens & {"function", "callable", "fn"})
    callable_invocation = (
        "self.function(" in rendered
        or "self.fn(" in rendered
        or "self.callable(" in rendered
    )
    if callable_storage and callable_invocation:
        return "user_callable"

    backend_tokens = {"define_graph", "build_graph", "executor", "backend"}
    if tokens & backend_tokens:
        return "backend_graph"
    return "none"


def structural_record_scope(source: str, prior: h7.AnalysisResult) -> RecordScope:
    _, rendered = source_features(source)
    if any("record_scope:typed-subrecord" in item for item in prior.evidence):
        return "typed_subrecord"
    if any("record_scope:whole-record" in item for item in prior.evidence):
        return "whole_record"
    if "Subject" in rendered and (
        "subject.get_images" in rendered
        or "subject.get_images_dict" in rendered
        or "transform(subject)" in rendered
    ):
        return "typed_subrecord"
    if "sample[" in rendered or "results[" in rendered:
        return "fixed_fields"
    return "unknown"


def infer_v4(name: str, path: str, common: list[str]) -> AnalysisV4:
    source = h7c.read_source(path)
    prior = h7c.infer_torchio(name, path, common)
    delegation = structural_delegation(source)
    scope = structural_record_scope(source, prior)
    effect = EffectV4(prior.effect, scope, delegation)
    reasons: list[str] = []
    if scope == "unknown":
        reasons.append("unknown_record_scope")
    if delegation != "none":
        reasons.append(
            {
                "child_operator": "unresolved_child_effect",
                "user_callable": "unresolved_user_callable",
                "framework_bridge": "external_framework_delegation",
                "backend_graph": "unsupported_backend_graph",
            }[delegation]
        )
    if prior.status == "unknown" and delegation == "none":
        reasons.extend(prior.reasons)
    status = "unknown" if reasons else "resolved"
    return AnalysisV4(
        status, effect, tuple(dict.fromkeys(reasons)), "torchio",
        prior.evidence + (f"record_scope:{scope}", f"delegation:{delegation}"),
    )


def validator_v4(result: AnalysisV4) -> tuple[str, ...]:
    reasons = list(result.reasons)
    if result.effect.base is not None:
        # Reuse all base safety obligations except the old parametric-target
        # shortcut; V4 record_scope now carries that proof obligation.
        base = result.effect.base
        if base.input_cardinality != "one" or base.output_cardinality != "one":
            reasons.append(f"unsupported_cardinality:{base.input_cardinality}->{base.output_cardinality}")
        if base.sample_identity == "combine":
            reasons.append("combined_sample_identity")
        if base.execution_state_writes:
            reasons.append("execution_state_write")
        if base.execution_external_reads or base.execution_external_writes:
            reasons.append("execution_external_effect")
    return tuple(dict.fromkeys(reasons))


def expected_units() -> list[dict[str, str]]:
    protocol = h7c.load_protocol()
    units = list(protocol["adapter_calibration"]["units"])
    units.extend(protocol["sealed_operator_holdout"])
    return units


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    protocol = h7c.load_protocol()
    common = protocol["adapter_calibration"]["common_files"]
    rows: list[dict[str, object]] = []
    for unit in expected_units():
        result = infer_v4(unit["name"], unit["path"], common)
        reasons = validator_v4(result)
        decision = "reject" if reasons else "admit"
        reason_match = (
            not reasons if unit["reason"] == "none"
            else any(unit["reason"] in reason for reason in reasons)
        )
        rows.append(
            {
                "unit": unit["name"],
                "expected_decision": unit["expected"],
                "actual_decision": decision,
                "decision_correct": decision == unit["expected"],
                "expected_reason": unit["reason"],
                "reason_match": reason_match,
                "status": result.status,
                "record_scope": result.effect.record_scope,
                "delegation_kind": result.effect.delegation_kind,
                "validator_reasons": ";".join(reasons) or "none",
            }
        )
    write_csv(OUT / "autocontract_h7d_v4_calibration.csv", rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reason_correct = sum(row["reason_match"] is True for row in rows)
    ready = correct == len(rows) and reason_correct == len(rows)
    summary = {
        "units": len(rows),
        "decisions_correct": correct,
        "reason_categories_correct": reason_correct,
        "effect_v4_freeze_ready": ready,
    }
    write_csv(OUT / "autocontract_h7d_v4_summary.csv", [summary])
    manifest = {
        "schema": {
            "record_scope": ["whole_record", "typed_subrecord", "fixed_fields", "unknown"],
            "delegation_kind": [
                "none", "child_operator", "user_callable", "framework_bridge", "backend_graph"
            ],
        },
        "rules": V4_RULES,
        "calibration_framework": "TorchIO",
        "calibration_units": [row["unit"] for row in rows],
    }
    (OUT / "autocontract_h7d_v4_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    report = "\n".join(
        [
            "# AutoContract EffectV4 calibration",
            "",
            f"Decisions: {correct}/{len(rows)}; reason categories: {reason_correct}/{len(rows)}.",
            f"Freeze ready: **{'YES' if ready else 'NO'}**.",
            "",
            "| Unit | Scope | Delegation | Decision | Reason |",
            "|---|---|---|---|---|",
            *[
                f"| `{row['unit']}` | {row['record_scope']} | {row['delegation_kind']} | "
                f"{row['actual_decision']} | {row['validator_reasons']} |"
                for row in rows
            ],
            "",
        ]
    )
    (OUT / "autocontract_h7d_v4_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if not ready:
        raise RuntimeError("EffectV4 is not freeze-ready")


if __name__ == "__main__":
    main()
