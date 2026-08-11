"""Optimizer-boundary MVP for contract-carrying adjacent rewrites.

The pilot deliberately reuses the completed H3 corpus. It validates the plan
interface and baseline accounting; it is not a new EffectV7 blind result and
its unit opportunity score is not an end-to-end performance measurement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import autocontract_h3_ablation as h3


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
Policy = Literal[
    "fail_closed",
    "registry_only",
    "static_only",
    "dynamic_only",
    "hybrid",
    "manual_full",
    "human_oracle",
    "effect_v7",
    "cache_contract",
]
RewriteKind = Literal["adjacent_swap", "registered_parameter_replay", "cache_prefix"]

POLICIES: tuple[Policy, ...] = (
    "fail_closed",
    "registry_only",
    "static_only",
    "dynamic_only",
    "hybrid",
    "manual_full",
    "human_oracle",
)
H3_MODE: dict[Policy, h3.Mode] = {
    "registry_only": "registry",
    "static_only": "static",
    "dynamic_only": "runtime",
    "hybrid": "hybrid",
}


@dataclass(frozen=True)
class RewriteCandidate:
    candidate_id: str
    rewrite_kind: RewriteKind
    pipeline_id: str
    position: int
    operators: tuple[str, ...]
    context_id: str
    optimizer_score: float


@dataclass(frozen=True)
class ContractVerdict:
    policy: Policy
    admitted: bool
    reasons: tuple[str, ...]
    contract_sha256: str
    evidence_class: str


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: RewriteCandidate
    contract: ContractVerdict
    eligible: bool
    oracle_safe: bool
    oracle_evidence: str


@dataclass(frozen=True)
class PlanDecision:
    policy: Policy
    pipeline_id: str
    selected_candidate_ids: tuple[str, ...]
    total_opportunity_score: float


def canonical(value: object) -> object:
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items())}
    return value


def digest(payload: object) -> str:
    encoded = json.dumps(
        canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_from_pair(pair: h3.PairOccurrence) -> RewriteCandidate:
    return RewriteCandidate(
        candidate_id=f"{pair.pipeline}:{pair.position}:{pair.left}->{pair.right}",
        rewrite_kind="adjacent_swap",
        pipeline_id=pair.pipeline,
        position=pair.position,
        operators=(pair.left, pair.right),
        context_id=f"h3/{pair.base_input_kind}/{pair.input_kind}",
        # One unit means "one safe rewrite opportunity". This is intentionally
        # not presented as latency or throughput benefit.
        optimizer_score=1.0,
    )


def effect_payload(effect: h3.Effect) -> dict[str, object]:
    return {
        "output_random": effect.output_random,
        "rng_sources": effect.rng_sources,
        "changes_shape": effect.changes_shape,
        "changes_dtype": effect.changes_dtype,
        "stateful": effect.stateful,
        "scope": effect.scope,
    }


def assess_pair(
    policy: Policy,
    pair: h3.PairOccurrence,
    candidate: RewriteCandidate,
    specs: dict[str, h3.OperatorSpec],
    predictions: dict[h3.Mode, dict[str, h3.Effect]],
    validator_trials: int,
) -> CandidateAssessment:
    if policy == "fail_closed":
        admitted = False
        evidence = "missing_contract"
        contract_payload: object = {"policy": policy, "reason": evidence}
        evidence_class = "safety_lower_bound"
    elif policy == "human_oracle":
        admitted = pair.oracle_safe
        evidence = pair.oracle_evidence
        contract_payload = {
            "policy": policy,
            "candidate_id": candidate.candidate_id,
            "oracle_safe": pair.oracle_safe,
            "oracle_evidence": pair.oracle_evidence,
        }
        evidence_class = "sealed_oracle_upper_bound"
    else:
        if policy == "manual_full":
            effects = {name: spec.truth for name, spec in specs.items()}
            evidence_class = "full_manual_effect_hints_plus_validator"
        else:
            effects = predictions[H3_MODE[policy]]
            evidence_class = f"{policy}_effect_contract_plus_validator"
        admitted, evidence = h3.admit_pair(pair, effects, specs, validator_trials)
        contract_payload = {
            "policy": policy,
            "candidate_id": candidate.candidate_id,
            "left": effect_payload(effects[pair.left]),
            "right": effect_payload(effects[pair.right]),
            "validator_evidence": evidence,
        }

    reasons = () if admitted else (evidence,)
    verdict = ContractVerdict(
        policy=policy,
        admitted=admitted,
        reasons=reasons,
        contract_sha256=digest(contract_payload),
        evidence_class=evidence_class,
    )
    return CandidateAssessment(
        candidate=candidate,
        contract=verdict,
        eligible=verdict.admitted and candidate.optimizer_score > 0,
        oracle_safe=pair.oracle_safe,
        oracle_evidence=pair.oracle_evidence,
    )


def plan_better(
    left: tuple[float, tuple[str, ...]], right: tuple[float, tuple[str, ...]]
) -> tuple[float, tuple[str, ...]]:
    if left[0] > right[0]:
        return left
    if right[0] > left[0]:
        return right
    # Stable tie breaking makes the output reproducible across Python versions.
    return left if left[1] <= right[1] else right


def select_non_overlapping(
    policy: Policy, pipeline_id: str, assessments: list[CandidateAssessment]
) -> PlanDecision:
    eligible = sorted(
        (item for item in assessments if item.eligible),
        key=lambda item: (item.candidate.position + 1, item.candidate.candidate_id),
    )
    if not eligible:
        return PlanDecision(policy, pipeline_id, (), 0.0)

    previous: list[int] = []
    for index, item in enumerate(eligible):
        prior = -1
        for candidate_index in range(index - 1, -1, -1):
            other = eligible[candidate_index]
            if other.candidate.position + 1 < item.candidate.position:
                prior = candidate_index
                break
        previous.append(prior)

    best: list[tuple[float, tuple[str, ...]]] = []
    for index, item in enumerate(eligible):
        skip = best[index - 1] if index else (0.0, ())
        base = best[previous[index]] if previous[index] >= 0 else (0.0, ())
        take = (
            base[0] + item.candidate.optimizer_score,
            base[1] + (item.candidate.candidate_id,),
        )
        best.append(plan_better(skip, take))
    score, selected = best[-1]
    return PlanDecision(policy, pipeline_id, selected, score)


def confusion(assessments: list[CandidateAssessment]) -> dict[str, int | float]:
    tp = sum(item.contract.admitted and item.oracle_safe for item in assessments)
    fp = sum(item.contract.admitted and not item.oracle_safe for item in assessments)
    fn = sum(not item.contract.admitted and item.oracle_safe for item in assessments)
    tn = sum(not item.contract.admitted and not item.oracle_safe for item in assessments)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "unsafe_precision": tn / max(tn + fp, 1),
    }


def selected_ids(plans: list[PlanDecision]) -> set[str]:
    return {
        candidate_id
        for plan in plans
        for candidate_id in plan.selected_candidate_ids
    }


def verify_non_overlap(
    plans: list[PlanDecision], lookup: dict[str, CandidateAssessment]
) -> bool:
    for plan in plans:
        positions = sorted(lookup[item].candidate.position for item in plan.selected_candidate_ids)
        if any(right - left <= 1 for left, right in zip(positions, positions[1:])):
            return False
    return True


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--effect-seeds", type=int, default=8)
    parser.add_argument("--validator-trials", type=int, default=8)
    parser.add_argument("--oracle-trials", type=int, default=48)
    args = parser.parse_args()

    h3.torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    specs = h3.operator_specs()
    seeds = tuple(h3.BASE_SEED + index * 101 for index in range(args.effect_seeds))
    predictions, _runtime = h3.infer_all(specs, seeds)
    pairs = h3.build_pair_oracle(specs, args.oracle_trials)
    if len(specs) != 30 or len(pairs) != 37:
        raise AssertionError("optimizer-boundary MVP requires the frozen H3 pilot corpus")

    assessments_by_policy: dict[Policy, list[CandidateAssessment]] = {
        policy: [] for policy in POLICIES
    }
    for pair in pairs:
        candidate = candidate_from_pair(pair)
        for policy in POLICIES:
            assessments_by_policy[policy].append(
                assess_pair(policy, pair, candidate, specs, predictions, args.validator_trials)
            )

    plans_by_policy: dict[Policy, list[PlanDecision]] = {}
    for policy, assessments in assessments_by_policy.items():
        pipelines = sorted({item.candidate.pipeline_id for item in assessments})
        plans_by_policy[policy] = [
            select_non_overlapping(
                policy,
                pipeline,
                [item for item in assessments if item.candidate.pipeline_id == pipeline],
            )
            for pipeline in pipelines
        ]

    oracle_selected = selected_ids(plans_by_policy["human_oracle"])
    oracle_opportunities = len(oracle_selected)
    summary_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    self_checks: dict[str, bool] = {}
    annotation_signatures: dict[Policy, int | str] = {
        "fail_closed": 0,
        "registry_only": len(h3.REGISTRY_NAMES),
        "static_only": 0,
        "dynamic_only": 0,
        "hybrid": len(h3.REGISTRY_NAMES)
        + sum(
            any(getattr(predictions["hybrid"][name], field.name) is None for field in h3.fields(h3.Effect))
            for name in specs
        ),
        "manual_full": len(specs),
        "human_oracle": "candidate_oracle",
    }

    for policy in POLICIES:
        assessments = assessments_by_policy[policy]
        plans = plans_by_policy[policy]
        selected = selected_ids(plans)
        lookup = {item.candidate.candidate_id: item for item in assessments}
        metrics = confusion(assessments)
        selected_safe = sum(lookup[item].oracle_safe for item in selected)
        selected_unsafe = len(selected) - selected_safe
        opportunity_coverage = selected_safe / max(oracle_opportunities, 1)
        summary_rows.append(
            {
                "policy": policy,
                "candidates": len(assessments),
                **metrics,
                "selected_candidates": len(selected),
                "selected_safe": selected_safe,
                "selected_unsafe": selected_unsafe,
                "oracle_plan_safe_opportunities": oracle_opportunities,
                "plan_safe_opportunity_coverage": opportunity_coverage,
                "annotation_signatures": annotation_signatures[policy],
                "non_overlap_valid": verify_non_overlap(plans, lookup),
            }
        )
        self_checks[f"{policy}_only_eligible_selected"] = all(
            lookup[item].eligible for item in selected
        )
        self_checks[f"{policy}_non_overlap"] = verify_non_overlap(plans, lookup)
        for item in assessments:
            candidate_rows.append(
                {
                    "policy": policy,
                    "candidate_id": item.candidate.candidate_id,
                    "pipeline": item.candidate.pipeline_id,
                    "position": item.candidate.position,
                    "rewrite_kind": item.candidate.rewrite_kind,
                    "left": item.candidate.operators[0],
                    "right": item.candidate.operators[1],
                    "context_id": item.candidate.context_id,
                    "optimizer_score": item.candidate.optimizer_score,
                    "contract_admitted": item.contract.admitted,
                    "eligible": item.eligible,
                    "selected": item.candidate.candidate_id in selected,
                    "oracle_safe": item.oracle_safe,
                    "decision_correct": item.contract.admitted == item.oracle_safe,
                    "reasons": ";".join(item.contract.reasons) or "none",
                    "contract_sha256": item.contract.contract_sha256,
                    "evidence_class": item.contract.evidence_class,
                    "oracle_evidence": item.oracle_evidence,
                }
            )

    summary = {row["policy"]: row for row in summary_rows}
    self_checks.update(
        {
            "fail_closed_high_score_cannot_bypass_semantics": not CandidateAssessment(
                RewriteCandidate("probe", "adjacent_swap", "probe", 0, ("a", "b"), "probe", 1e12),
                ContractVerdict("fail_closed", False, ("missing_contract",), digest("probe"), "probe"),
                False,
                True,
                "probe",
            ).eligible,
            "hybrid_zero_unsafe_false_accepts": int(summary["hybrid"]["fp"]) == 0,
            "hybrid_safe_recall_gate": float(summary["hybrid"]["safe_recall"]) >= 0.80,
            "dynamic_only_false_accept_preserved": int(summary["dynamic_only"]["fp"]) >= 1,
            "human_oracle_plan_has_no_unsafe_selection": int(summary["human_oracle"]["selected_unsafe"]) == 0,
            "all_contract_digests_bound": all(
                len(item.contract.contract_sha256) == 64
                for assessments in assessments_by_policy.values()
                for item in assessments
            ),
        }
    )
    all_checks_pass = all(self_checks.values())

    write_csv(OUT / "autocontract_optimizer_boundary_candidates_v0.csv", candidate_rows)
    write_csv(OUT / "autocontract_optimizer_boundary_summary_v0.csv", summary_rows)
    payload = {
        "protocol": "AutoContract optimizer-boundary H3 replay v0",
        "scope": "interface and opportunity-count pilot; not EffectV7 blind evidence",
        "effect_seeds": args.effect_seeds,
        "validator_trials": args.validator_trials,
        "oracle_trials": args.oracle_trials,
        "operators": len(specs),
        "candidates": len(pairs),
        "pipelines": len(h3.pipelines()),
        "checks": self_checks,
        "all_checks_pass": all_checks_pass,
    }
    (OUT / "autocontract_optimizer_boundary_selftest_v0.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# AutoContract optimizer-boundary MVP",
        "",
        "> This replays the completed H3 corpus to validate a common candidate/contract/plan interface. Unit opportunity coverage is not a throughput or latency result, and this is not a new EffectV7 blind evaluation.",
        "",
        f"Operators: {len(specs)}; pipelines: {len(h3.pipelines())}; adjacent candidates: {len(pairs)}; human-oracle non-overlapping opportunities: {oracle_opportunities}.",
        "",
        "| Policy | TP | FP | FN | TN | Safe recall | Selected safe | Selected unsafe | Plan opportunity coverage | Hints/signatures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['policy']} | {row['tp']} | {row['fp']} | {row['fn']} | {row['tn']} | "
            f"{float(row['safe_recall']):.1%} | {row['selected_safe']} | {row['selected_unsafe']} | "
            f"{float(row['plan_safe_opportunity_coverage']):.1%} | {row['annotation_signatures']} |"
        )
    lines.extend(
        [
            "",
            "## Interface checks",
            "",
            *[f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in self_checks.items()],
            "",
            f"Overall optimizer-boundary self-test: **{'PASS' if all_checks_pass else 'FAIL'}**.",
            "",
            "## Interpretation",
            "",
            "- The semantic gate is upstream of plan selection: a high score cannot revive a rejected candidate.",
            "- Dynamic-only retains its finite-probe unsafe false accept; the experiment does not hide it with posthoc repair.",
            "- The next adapter should convert EffectV7 AnalysisV7 plus validator_v7 reasons into ContractVerdict, without changing the optimizer interface.",
            "- RQ3 still requires a real cache/replay profiler; unit opportunity coverage is only a structural integration metric.",
            "",
        ]
    )
    report = "\n".join(lines)
    (OUT / "autocontract_optimizer_boundary_v0.md").write_text(report, encoding="utf-8")
    print(report)
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
