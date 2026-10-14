"""Build offline optimizer requests from comparable method predictions.

This development interface reads no oracle, imports no ML framework, and runs
no optimizer or workload. Its orders represent a method's recommendations,
not verified execution permissions. Runtime adapters must verify evidence and
premises independently using the existing capability/guard implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Literal


Method = Literal[
    "autocontract", "manual_hints", "static_only",
    "dynamic_output_only", "dynamic_stateful", "fail_closed",
]
Status = Literal["accept", "reject", "unknown", "error"]
Evidence = Literal["proof", "manual_claim", "finite_probe", "counterexample", "none"]
METHODS = {
    "autocontract", "manual_hints", "static_only",
    "dynamic_output_only", "dynamic_stateful", "fail_closed",
}
STATUSES = {"accept", "reject", "unknown", "error"}
EVIDENCE = {"proof", "manual_claim", "finite_probe", "counterexample", "none"}


def require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    position: int
    # Binds source/configuration/domain/RNG/runtime/observation AND the full
    # baseline pipeline context. A pair certificate alone is not this binding.
    context_sha256: str


@dataclass(frozen=True)
class Prediction:
    method: Method
    candidate_id: str
    context_sha256: str
    status: Status
    evidence: Evidence
    evidence_sha256: str | None
    reason: str


def build_optimizer_request(
    *,
    method: Method,
    pipeline_id: str,
    baseline_order: Iterable[str],
    candidates: Iterable[Candidate],
    predictions: Iterable[Prediction],
    cost_profile_sha256: str | None = None,
) -> dict:
    """Create a label-free, single-adjacent-swap planning request.

    Missing predictions remain visible as unknown outcomes. Invalid binding,
    duplicate/foreign predictions and invalid evidence fail the request. No
    combination of swaps is inferred, even for disjoint accepted pairs.
    """
    if method not in METHODS:
        raise ValueError("unsupported method; oracle upper bound is reveal-only")
    if not isinstance(pipeline_id, str) or not pipeline_id.strip():
        raise ValueError("pipeline_id must be nonempty")
    order = tuple(baseline_order)
    if not order or any(not isinstance(op, str) or not op.strip() for op in order):
        raise ValueError("baseline must contain nonempty operator occurrence IDs")
    if len(set(order)) != len(order):
        raise ValueError("baseline operator occurrence IDs must be unique")
    if cost_profile_sha256 is not None:
        require_digest(cost_profile_sha256, "cost_profile_sha256")

    catalog = tuple(candidates)
    by_id: dict[str, Candidate] = {}
    positions: set[int] = set()
    for candidate in catalog:
        if not isinstance(candidate.candidate_id, str) or not candidate.candidate_id.strip():
            raise ValueError("candidate_id must be nonempty")
        if candidate.candidate_id in by_id:
            raise ValueError("duplicate candidate_id")
        if type(candidate.position) is not int or not 0 <= candidate.position < len(order) - 1:
            raise ValueError("candidate must address an adjacent pair in baseline")
        if candidate.position in positions:
            raise ValueError("one context-bound candidate per baseline position is required")
        require_digest(candidate.context_sha256, "context_sha256")
        by_id[candidate.candidate_id] = candidate
        positions.add(candidate.position)

    by_prediction: dict[str, Prediction] = {}
    for prediction in predictions:
        if prediction.method != method:
            raise ValueError("mixed methods in one request")
        if prediction.candidate_id not in by_id:
            raise ValueError("prediction references a foreign candidate")
        if prediction.candidate_id in by_prediction:
            raise ValueError("duplicate prediction")
        if prediction.context_sha256 != by_id[prediction.candidate_id].context_sha256:
            raise ValueError("prediction context does not match candidate")
        if prediction.status not in STATUSES or prediction.evidence not in EVIDENCE:
            raise ValueError("invalid prediction status or evidence")
        if not isinstance(prediction.reason, str) or not prediction.reason.strip():
            raise ValueError("prediction must record a reason")
        if prediction.evidence == "none":
            if prediction.evidence_sha256 is not None:
                raise ValueError("no-evidence prediction cannot carry evidence digest")
        else:
            require_digest(prediction.evidence_sha256, "evidence_sha256")
        if prediction.status == "accept":
            if method == "fail_closed":
                raise ValueError("fail_closed cannot recommend a swap")
            if prediction.evidence in {"none", "counterexample"}:
                raise ValueError("accepted recommendation must carry positive evidence")
        if method.startswith("dynamic_") and prediction.evidence not in {
            "finite_probe", "counterexample", "none",
        }:
            raise ValueError("finite dynamic testing cannot claim proof or manual evidence")
        if method == "static_only" and prediction.evidence not in {
            "proof", "counterexample", "none",
        }:
            raise ValueError("static_only cannot consume finite probes or manual hints")
        if method == "manual_hints" and prediction.evidence == "finite_probe":
            raise ValueError("manual_hints cannot silently add a dynamic validator")
        if method == "autocontract" and prediction.status == "accept" and prediction.evidence != "proof":
            raise ValueError("strict autocontract acceptance must declare proof evidence")
        by_prediction[prediction.candidate_id] = prediction

    proposed_orders = [list(order)]
    outcomes = []
    for candidate in catalog:
        prediction = by_prediction.get(candidate.candidate_id)
        if prediction is None:
            prediction = Prediction(
                method, candidate.candidate_id, candidate.context_sha256,
                "unknown", "none", None, "missing_prediction",
            )
        proposed_order = None
        if prediction.status == "accept":
            swapped = list(order)
            index = candidate.position
            swapped[index], swapped[index + 1] = swapped[index + 1], swapped[index]
            proposed_order = swapped
            proposed_orders.append(swapped)
        outcomes.append({
            **asdict(prediction),
            "prediction_present": candidate.candidate_id in by_prediction,
            "position": candidate.position,
            "proposed_order": proposed_order,
        })

    return {
        "artifact_type": "offline_comparison_optimizer_request",
        "status": "development_draft",
        "scientific_evidence": False,
        "execution_authorized": False,
        "method": method,
        "pipeline_id": pipeline_id,
        "scope": "baseline_or_one_context_bound_adjacent_swap",
        "baseline_order": list(order),
        "cost_profile_sha256": cost_profile_sha256,
        "proposed_orders": proposed_orders,
        "candidate_outcomes": outcomes,
    }


def check_proposed_order(request: dict, selected_order: Iterable[str]) -> bool:
    """Check planner membership only; this is NOT an execution safety check."""
    return list(selected_order) in request["proposed_orders"]
