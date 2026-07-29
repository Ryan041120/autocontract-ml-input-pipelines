"""Buffered batch replay: validate, fence, apply, commit, then release outputs."""

from __future__ import annotations

from dataclasses import dataclass, replace

import autocontract_h7i_lineage_certificate as lineage
import autocontract_h7k_registered_executor as registered
import autocontract_h7l_bound_executor as h7l_bound
import autocontract_h7l_provenance_token as h7l
import autocontract_h7m_batch_lease as batch


@dataclass(frozen=True)
class BufferedBatchReceipt:
    batch_id: str
    attestation_sha256: str
    lease: batch.BatchLease
    commit: batch.BatchCommitReceipt
    output_sha256: str
    apply_receipts: tuple[registered.RegisteredApplyReceipt, ...]


class BufferedBatchExecutor:
    def __init__(
        self,
        executors: tuple[registered.RegisteredReplayExecutor, ...],
        verifier: batch.BatchVerifier,
        registry: batch.SqliteBatchRegistry,
        policies: tuple[h7l.ProvenanceExpectation, ...],
    ) -> None:
        if not executors or len(executors) != len(policies):
            raise batch.BatchRejected(("executor_policy_length_mismatch",))
        for executor, policy in zip(executors, policies):
            if executor.registration_receipt.registration_sha256 != policy.registration_sha256:
                raise batch.BatchRejected(("policy_registration_mismatch",))
        self._executors = executors
        self._verifier = verifier
        self._registry = registry
        self._policies = policies

    @property
    def executors(self) -> tuple[registered.RegisteredReplayExecutor, ...]:
        return self._executors

    def operator_invocations(self) -> int:
        return sum(executor.stats().operator_invocations for executor in self._executors)

    def apply_batch(
        self,
        *,
        inputs: tuple[object, ...],
        tickets: tuple[batch.BatchTicket, ...],
        worker_id: str,
    ) -> tuple[tuple[object, ...], BufferedBatchReceipt]:
        if len(inputs) != len(self._executors):
            raise batch.BatchRejected(("input_batch_length_mismatch",))
        consumed_inputs = tuple(h7l_bound.seal_input(value) for value in inputs)
        dynamic_policies = tuple(
            replace(policy, input_content_sha256=lineage.digest_payload(value))
            for policy, value in zip(self._policies, consumed_inputs)
        )
        root = self._verifier.verify_batch(tickets, dynamic_policies)
        lease = self._registry.claim(root.statement.batch_id, worker_id)
        outputs: list[object] = []
        receipts: list[registered.RegisteredApplyReceipt] = []
        try:
            for executor, policy, value in zip(self._executors, dynamic_policies, consumed_inputs):
                output, receipt = executor.apply(
                    input_value=value,
                    sample_id=policy.replay_sample_id,
                )
                outputs.append(output)
                receipts.append(receipt)
            output_digest = lineage.digest_payload(outputs)
            commit = self._registry.commit(lease, output_digest)
        except Exception:
            state = self._registry.state(lease.batch_id)
            if state is not None and state["state"] == "leased":
                self._registry.abort(lease)
            raise
        result = tuple(outputs)
        return result, BufferedBatchReceipt(
            batch_id=root.statement.batch_id,
            attestation_sha256=root.attestation_sha256,
            lease=lease,
            commit=commit,
            output_sha256=output_digest,
            apply_receipts=tuple(receipts),
        )
