"""H8A: drive a real horizon-aware optimizer decision from EffectV7 proofs.

The candidate preserves the already-established supplied-parameter semantics:
replace per-call H7J atomic replay with H7K registered replay. It does *not*
claim that fresh parameter sampling can be replaced with replay.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import autocontract_h7h_effect_v7 as v7  # noqa: E402
import autocontract_h7h_kornia as h7h  # noqa: E402
import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_optimizer_boundary as boundary  # noqa: E402


PROFILE_ROWS = OUT / "autocontract_h7k_paired_performance.csv"
PROFILE_SUMMARY = OUT / "autocontract_h7k_paired_performance_summary.csv"
HORIZONS = (1, 10)


@dataclass(frozen=True)
class EffectV7LeafVerdict:
    module_path: str
    public_symbol: str
    configuration: str
    phase: str
    admitted: bool
    reasons: tuple[str, ...]
    analysis_sha256: str
    proof_sha256: str


@dataclass(frozen=True)
class Profile:
    profile_id: str
    h7j_atomic_ms: float
    h7k_registered_ms: float
    registration_ms: float
    measured_break_even_calls: float

    @property
    def saving_per_call_ms(self) -> float:
        return self.h7j_atomic_ms - self.h7k_registered_ms

    def net_benefit_ms(self, calls: int) -> float:
        return calls * self.saving_per_call_ms - self.registration_ms


@dataclass(frozen=True)
class ProfiledPlanDecision:
    candidate: boundary.RewriteCandidate
    contract: boundary.ContractVerdict
    profile: Profile
    expected_calls: int
    semantic_eligible: bool
    cost_eligible: bool
    selected: bool
    decision_reasons: tuple[str, ...]


def analysis_payload(
    symbol: str,
    binding: dict[str, object],
    analysis: v7.AnalysisV7,
    freeze: dict[str, object],
) -> dict[str, object]:
    reachable = analysis.effect.reachable
    return {
        "schema": "autocontract.effect-v7-verdict.v0",
        "public_symbol": symbol,
        "binding_sha256": str(binding.get("binding_sha256") or ""),
        "source_sha256": str(binding.get("source_sha256") or ""),
        "repository_commit": str(freeze["repository_commit"]),
        "effect_v7_sha256": str(freeze["effect_v7_sha256"]),
        "adapter_sha256": str(freeze["adapter_sha256"]),
        "status": analysis.status,
        "configuration": reachable.context.configuration,
        "phase": reachable.context.phase,
        "context_values": list(reachable.context.values),
        "reachable_methods": list(reachable.methods),
        "guards": list(reachable.guards),
        "state_accesses": [
            {"kind": item.kind, "path": item.path}
            for item in reachable.state_accesses
        ],
        "callable_bindings": [
            {"attribute": item.attribute, "origin": item.origin}
            for item in reachable.callable_bindings
        ],
        "rng_paths": list(reachable.rng_paths),
        "sampling_rng": reachable.sampling_rng,
        "delegation": reachable.delegation,
        "unresolved_dispatch": list(reachable.unresolved_dispatch),
        "inherited_reasons": list(analysis.inherited_reasons),
        "evidence": list(analysis.evidence),
    }


def effect_v7_verdict(
    *,
    module_path: str,
    module: object,
    classes: dict[str, object],
    freeze: dict[str, object],
    proof: auto.LeafReplayProof,
    configuration: str,
) -> EffectV7LeafVerdict:
    symbol = auto.type_name(module)
    binding = h7h.public_binding(symbol)
    if binding.get("status") != "resolved":
        reasons = ("unresolved_symbol_binding",)
        payload = {
            "schema": "autocontract.effect-v7-verdict.v0",
            "public_symbol": symbol,
            "binding_status": binding.get("status"),
            "configuration": configuration,
        }
        phase = "replay_apply" if configuration == "kornia.params_provided" else "sample_apply"
    else:
        analysis = h7h.analyze(binding, classes, configuration)  # type: ignore[arg-type]
        reasons = v7.validator_v7(analysis)
        payload = analysis_payload(symbol, binding, analysis, freeze)
        phase = analysis.effect.reachable.context.phase

    proof_reasons: list[str] = []
    if proof.public_symbol != symbol or proof.module_path != module_path:
        proof_reasons.append("leaf_proof_subject_mismatch")
    if proof.configuration != configuration:
        proof_reasons.append("leaf_proof_configuration_mismatch")
    if proof.repository_commit != freeze["repository_commit"]:
        proof_reasons.append("leaf_proof_repository_mismatch")
    if proof.effect_v7_sha256 != freeze["effect_v7_sha256"]:
        proof_reasons.append("leaf_proof_analyzer_mismatch")
    if proof.adapter_sha256 != freeze["adapter_sha256"]:
        proof_reasons.append("leaf_proof_adapter_mismatch")
    if proof.binding_sha256 != str(binding.get("binding_sha256") or ""):
        proof_reasons.append("leaf_proof_binding_mismatch")
    if proof.source_sha256 != str(binding.get("source_sha256") or ""):
        proof_reasons.append("leaf_proof_source_mismatch")
    if proof.proof_sha256 != auto._proof_digest(proof):
        proof_reasons.append("leaf_proof_digest_mismatch")
    if proof.decision != ("reject" if reasons else "admit"):
        proof_reasons.append("leaf_proof_decision_mismatch")
    combined = tuple(dict.fromkeys((*reasons, *proof_reasons)))
    payload["leaf_proof_sha256"] = proof.proof_sha256
    payload["validator_reasons"] = list(reasons)
    payload["proof_reasons"] = proof_reasons
    return EffectV7LeafVerdict(
        module_path=module_path,
        public_symbol=symbol,
        configuration=configuration,
        phase=phase,
        admitted=not combined,
        reasons=combined,
        analysis_sha256=boundary.digest(payload),
        proof_sha256=proof.proof_sha256,
    )


def compose_pipeline_contract(
    leaves: tuple[EffectV7LeafVerdict, ...], freeze: dict[str, object]
) -> boundary.ContractVerdict:
    reasons: list[str] = []
    if not leaves:
        reasons.append("empty_leaf_contract_set")
    for leaf in leaves:
        if not leaf.admitted:
            reasons.extend(f"{leaf.module_path}:{reason}" for reason in leaf.reasons)
    payload = {
        "schema": "autocontract.effect-v7-composite-verdict.v0",
        "configuration": "kornia.params_provided",
        "phase": "replay_apply",
        "repository_commit": freeze["repository_commit"],
        "effect_v7_sha256": freeze["effect_v7_sha256"],
        "adapter_sha256": freeze["adapter_sha256"],
        "leaves": [asdict(leaf) for leaf in leaves],
    }
    return boundary.ContractVerdict(
        policy="effect_v7",
        admitted=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        contract_sha256=boundary.digest(payload),
        evidence_class="frozen_effect_v7_plus_bound_leaf_proofs",
    )


def read_profiles() -> list[Profile]:
    with PROFILE_ROWS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    with PROFILE_SUMMARY.open(encoding="utf-8", newline="") as handle:
        summaries = {row["profile"]: row for row in csv.DictReader(handle)}
    profiles: list[Profile] = []
    keys = sorted({(int(row["batch"]), int(row["size"])) for row in rows})
    for batch, size in keys:
        selected = [row for row in rows if int(row["batch"]) == batch and int(row["size"]) == size]
        profile_id = f"B{batch}x3x{size}x{size}"
        h7j_ms = statistics.median(float(row["h7j_atomic_ms"]) for row in selected)
        h7k_ms = statistics.median(float(row["h7k_minimal_ms"]) for row in selected)
        summary = summaries[profile_id]
        profiles.append(
            Profile(
                profile_id=profile_id,
                h7j_atomic_ms=h7j_ms,
                h7k_registered_ms=h7k_ms,
                registration_ms=float(summary["registration_ms"]),
                measured_break_even_calls=float(summary["break_even_calls_vs_h7j"]),
            )
        )
    return profiles


def decide(
    profile: Profile,
    expected_calls: int,
    contract: boundary.ContractVerdict,
    operator_symbols: tuple[str, ...],
) -> ProfiledPlanDecision:
    net = profile.net_benefit_ms(expected_calls)
    candidate = boundary.RewriteCandidate(
        candidate_id=f"registered-replay:{profile.profile_id}:h{expected_calls}",
        rewrite_kind="registered_parameter_replay",
        pipeline_id="kornia-h7i-pilot",
        position=0,
        operators=operator_symbols,
        context_id=f"kornia.params_provided/replay_apply/{profile.profile_id}",
        optimizer_score=net,
    )
    semantic_eligible = contract.admitted
    cost_eligible = net > 0
    reasons: list[str] = []
    if not semantic_eligible:
        reasons.extend(contract.reasons or ("semantic_contract_rejected",))
    if not cost_eligible:
        reasons.append("non_positive_amortized_benefit")
    return ProfiledPlanDecision(
        candidate=candidate,
        contract=contract,
        profile=profile,
        expected_calls=expected_calls,
        semantic_eligible=semantic_eligible,
        cost_eligible=cost_eligible,
        selected=semantic_eligible and cost_eligible,
        decision_reasons=tuple(reasons),
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizons", type=int, nargs="+", default=list(HORIZONS))
    args = parser.parse_args()

    freeze = h7h.verify_freeze()
    pipeline = auto.build_pilot_pipeline()
    proofs = auto.generate_leaf_proofs(pipeline)
    proof_map = {(proof.module_path, proof.public_symbol): proof for proof in proofs}
    classes = h7h.package_classes()
    replay_leaves: list[EffectV7LeafVerdict] = []
    sample_leaves: list[EffectV7LeafVerdict] = []
    modules = list(auto.leaf_modules(pipeline))
    for path, module in modules:
        symbol = auto.type_name(module)
        proof = proof_map[(path, symbol)]
        replay_leaves.append(
            effect_v7_verdict(
                module_path=path,
                module=module,
                classes=classes,
                freeze=freeze,
                proof=proof,
                configuration="kornia.params_provided",
            )
        )
        # A supplied-params proof must not silently authorize the sampling path.
        sample_leaves.append(
            effect_v7_verdict(
                module_path=path,
                module=module,
                classes=classes,
                freeze=freeze,
                proof=proof,
                configuration="kornia.params_absent",
            )
        )

    replay_tuple = tuple(replay_leaves)
    contract = compose_pipeline_contract(replay_tuple, freeze)
    operator_symbols = tuple(leaf.public_symbol for leaf in replay_tuple)
    profiles = read_profiles()
    decisions = [
        decide(profile, horizon, contract, operator_symbols)
        for profile in profiles
        for horizon in args.horizons
    ]

    tampered_proof = replace(proofs[0], proof_sha256="0" * 64)
    tampered_leaf = effect_v7_verdict(
        module_path=modules[0][0],
        module=modules[0][1],
        classes=classes,
        freeze=freeze,
        proof=tampered_proof,
        configuration="kornia.params_provided",
    )
    rejected_contract = replace(
        contract,
        admitted=False,
        reasons=("test_semantic_reject",),
        contract_sha256=boundary.digest("test_semantic_reject"),
    )
    bypass_probe = decide(profiles[0], 1_000_000, rejected_contract, operator_symbols)

    checks = {
        "h7h_freeze_verified": bool(freeze),
        "leaf_proof_set_valid": auto.verify_leaf_proofs(proofs),
        "three_leaf_analyses_bound": len(replay_tuple) == 3,
        "replay_context_all_admitted": all(leaf.admitted for leaf in replay_tuple),
        "sample_context_all_rejected": all(not leaf.admitted for leaf in sample_leaves),
        "sample_rejection_mentions_sampling_or_proof_context": all(
            any("sampling" in reason or "configuration" in reason for reason in leaf.reasons)
            for leaf in sample_leaves
        ),
        "composite_contract_admitted": contract.admitted,
        "composite_contract_digest_bound": len(contract.contract_sha256) == 64,
        "tampered_leaf_proof_rejected": not tampered_leaf.admitted
        and "leaf_proof_digest_mismatch" in tampered_leaf.reasons,
        "three_real_profiles_loaded": len(profiles) == 3,
        "profile_savings_positive": all(profile.saving_per_call_ms > 0 for profile in profiles),
        "one_call_horizon_rejected_by_cost": all(
            not decision.selected
            for decision in decisions
            if decision.expected_calls == 1
        ),
        "ten_call_horizon_selected": all(
            decision.selected
            for decision in decisions
            if decision.expected_calls == 10
        ),
        "semantic_reject_cannot_be_bypassed_by_large_benefit": not bypass_probe.selected,
    }
    all_checks_pass = all(checks.values())

    leaf_rows: list[dict[str, object]] = []
    for context, leaves in (("replay", replay_leaves), ("sample", sample_leaves)):
        for leaf in leaves:
            leaf_rows.append(
                {
                    "context": context,
                    **asdict(leaf),
                    "reasons": ";".join(leaf.reasons) or "none",
                }
            )
    decision_rows = [
        {
            "candidate_id": item.candidate.candidate_id,
            "rewrite_kind": item.candidate.rewrite_kind,
            "profile": item.profile.profile_id,
            "expected_calls": item.expected_calls,
            "h7j_atomic_median_ms": item.profile.h7j_atomic_ms,
            "h7k_registered_median_ms": item.profile.h7k_registered_ms,
            "saving_per_call_ms": item.profile.saving_per_call_ms,
            "registration_ms": item.profile.registration_ms,
            "measured_break_even_calls": item.profile.measured_break_even_calls,
            "amortized_net_benefit_ms": item.candidate.optimizer_score,
            "semantic_eligible": item.semantic_eligible,
            "cost_eligible": item.cost_eligible,
            "selected": item.selected,
            "decision_reasons": ";".join(item.decision_reasons) or "none",
            "contract_sha256": item.contract.contract_sha256,
            "profile_rows_sha256": "",
        }
        for item in decisions
    ]
    # boundary has a canonical digest helper but no file helper; use a direct
    # content digest consistently in every row.
    profile_digest = hashlib.sha256(PROFILE_ROWS.read_bytes()).hexdigest()
    for row in decision_rows:
        row["profile_rows_sha256"] = profile_digest

    write_csv(OUT / "autocontract_h8a_effect_v7_leaves.csv", leaf_rows)
    write_csv(OUT / "autocontract_h8a_optimizer_decisions.csv", decision_rows)
    selftest = {
        "protocol": "AutoContract H8A EffectV7-to-optimizer integration pilot",
        "claim_boundary": "mechanism/runtime integration; not a new blind holdout",
        "candidate_semantics": "H7J atomic replay to H7K registered replay under supplied compatible params",
        "contract_sha256": contract.contract_sha256,
        "profile_rows_sha256": profile_digest,
        "checks": checks,
        "all_checks_pass": all_checks_pass,
    }
    (OUT / "autocontract_h8a_selftest.json").write_text(
        json.dumps(selftest, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# AutoContract H8A EffectV7 optimizer integration",
        "",
        "> Scope: mechanism/runtime integration on the completed Kornia calibration pipeline. This is not a new blind holdout. The candidate preserves supplied-parameter replay semantics; it does not replace fresh sampling with replay.",
        "",
        f"EffectV7 leaf contracts: {sum(leaf.admitted for leaf in replay_leaves)}/{len(replay_leaves)} admitted in replay context; {sum(leaf.admitted for leaf in sample_leaves)}/{len(sample_leaves)} admitted in sampling context.",
        f"Composite contract: **{'ADMIT' if contract.admitted else 'REJECT'}**; digest `{contract.contract_sha256}`.",
        "",
        "| Profile | Horizon | H7J atomic | H7K registered | Saving/call | Registration | Net benefit | Decision |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in decisions:
        lines.append(
            f"| {item.profile.profile_id} | {item.expected_calls} | {item.profile.h7j_atomic_ms:.3f} ms | "
            f"{item.profile.h7k_registered_ms:.3f} ms | {item.profile.saving_per_call_ms:.3f} ms | "
            f"{item.profile.registration_ms:.3f} ms | {item.candidate.optimizer_score:.3f} ms | "
            f"{'SELECT' if item.selected else 'REJECT'} |"
        )
    lines.extend(
        [
            "",
            "## Safety and integration checks",
            "",
            *[f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in checks.items()],
            "",
            f"Overall H8A integration gate: **{'PASS' if all_checks_pass else 'FAIL'}**.",
            "",
            "## Interpretation",
            "",
            "- EffectV7 and the bound leaf proofs authorize only `kornia.params_provided/replay_apply`; the same leaf operators fail closed on the fresh-sampling path.",
            "- The profiler independently decides amortization: one call does not repay registration, while ten calls do for all three measured profiles.",
            "- A large positive benefit cannot revive a semantic reject, preserving the optimizer-boundary invariant.",
            "- The next independent work item is a real `cache_prefix` candidate, because registered replay improves safety-path amortization but does not yet establish end-to-end input-pipeline throughput gain.",
            "",
        ]
    )
    report = "\n".join(lines)
    (OUT / "autocontract_h8a_effect_v7_optimizer.md").write_text(report, encoding="utf-8")
    print(report)
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
