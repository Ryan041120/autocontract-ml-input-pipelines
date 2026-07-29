"""Bind H7K registered replay to an H7L signed provenance token."""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace

import autocontract_h7i_lineage_certificate as lineage
import autocontract_h7k_registered_executor as registered
import autocontract_h7l_provenance_token as provenance


def seal_input(value: object) -> object:
    """Create consumed bytes before hashing; tensor clone preserves autograd linkage."""
    module = value.__class__.__module__
    if module.startswith("torch") and hasattr(value, "clone"):
        return value.clone()  # type: ignore[no-any-return,attr-defined]
    if isinstance(value, dict):
        return {key: seal_input(item) for key, item in value.items()}
    if isinstance(value, list):
        return [seal_input(item) for item in value]
    if isinstance(value, tuple):
        return tuple(seal_input(item) for item in value)
    return copy.deepcopy(value)


@dataclass(frozen=True)
class ProvenanceBoundReceipt:
    token_sha256: str
    provenance_payload_sha256: str
    consumer_id: str
    apply_receipt: registered.RegisteredApplyReceipt


class ProvenanceBoundExecutor:
    def __init__(
        self,
        executor: registered.RegisteredReplayExecutor,
        verifier: provenance.ProvenanceVerifier,
        policy: provenance.ProvenanceExpectation,
    ) -> None:
        if policy.registration_sha256 != executor.registration_receipt.registration_sha256:
            raise provenance.ProvenanceRejected(("policy_registration_mismatch",))
        self._executor = executor
        self._verifier = verifier
        self._policy = policy

    @property
    def executor(self) -> registered.RegisteredReplayExecutor:
        return self._executor

    def apply(
        self,
        *,
        input_value: object,
        token: provenance.SignedProvenanceToken,
        consumer_id: str,
    ) -> tuple[object, ProvenanceBoundReceipt]:
        consumed_input = seal_input(input_value)
        dynamic_expectation = replace(
            self._policy,
            input_content_sha256=lineage.digest_payload(consumed_input),
        )
        verified = self._verifier.verify_and_consume(
            token,
            dynamic_expectation,
            consumer_id=consumer_id,
        )
        output, apply_receipt = self._executor.apply(
            input_value=consumed_input,
            sample_id=dynamic_expectation.replay_sample_id,
        )
        return output, ProvenanceBoundReceipt(
            token_sha256=verified.token_sha256,
            provenance_payload_sha256=verified.payload_sha256,
            consumer_id=consumer_id,
            apply_receipt=apply_receipt,
        )
