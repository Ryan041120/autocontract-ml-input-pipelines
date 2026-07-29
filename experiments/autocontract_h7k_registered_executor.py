"""Registered/owned target executor with cached static replay proofs."""

from __future__ import annotations

import argparse
import copy
import json
import queue
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping

import autocontract_h7i_lineage_certificate as lineage


ReceiptLevel = Literal["minimal", "audit"]


@dataclass(frozen=True)
class RegistrationReceipt:
    success: bool
    registration_sha256: str
    certificate_sha256: str
    leaf_proof_set_sha256: str
    target_graph_sha256: tuple[str, ...]
    child_contract_sha256: tuple[str, ...]
    pool_size: int
    receipt_level: ReceiptLevel
    registration_ms: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RegisteredApplyReceipt:
    success: bool
    registration_sha256: str
    certificate_sha256: str
    sample_id: str
    target_slot: int
    post_params_sha256: str
    output_sha256: str
    receipt_level: ReceiptLevel
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExecutorStats:
    successful_calls: int
    rejected_calls: int
    operator_invocations: int


class RegistrationRejected(RuntimeError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("registration rejected: " + ",".join(reasons))
        self.reasons = reasons


class RegisteredReplayRejected(RuntimeError):
    def __init__(self, receipt: RegisteredApplyReceipt) -> None:
        super().__init__("registered replay rejected: " + ",".join(receipt.reasons))
        self.receipt = receipt


class RegisteredReplayExecutor:
    """Cache static validation for a private target pool; retain dynamic checks."""

    __slots__ = (
        "_certificate",
        "_leaf_policy",
        "_pool",
        "_receipt_level",
        "_registration",
        "_snapshot",
        "_stats",
        "_stats_lock",
        "_targets",
    )

    def __init__(
        self,
        *,
        certificate: lineage.ReplayLineageCertificate,
        snapshot: object,
        targets: list[object],
        leaf_policy: Mapping[str, lineage.Decision],
        registration: RegistrationReceipt,
        receipt_level: ReceiptLevel,
    ) -> None:
        self._certificate = certificate
        self._snapshot = copy.deepcopy(snapshot)
        self._targets = targets
        self._leaf_policy = dict(leaf_policy)
        self._registration = registration
        self._receipt_level = receipt_level
        self._pool: queue.Queue[tuple[int, object]] = queue.Queue(maxsize=len(targets))
        for index, target in enumerate(targets):
            self._pool.put((index, target))
        self._stats = [0, 0, 0]
        self._stats_lock = threading.Lock()

    @classmethod
    def register(
        cls,
        *,
        framework: str,
        framework_version: str,
        repository_commit: str,
        source_operator: object,
        target_factory: Callable[[], object],
        input_value: object,
        params: object,
        sample_id: str,
        leaf_policy: Mapping[str, lineage.Decision] | None = None,
        leaf_proof_set_sha256: str = "none",
        pool_size: int = 1,
        receipt_level: ReceiptLevel = "minimal",
    ) -> "RegisteredReplayExecutor":
        start = time.perf_counter_ns()
        if pool_size < 1:
            raise RegistrationRejected(("invalid_pool_size",))
        if receipt_level not in ("minimal", "audit"):
            raise RegistrationRejected(("invalid_receipt_level",))
        snapshot = copy.deepcopy(params)
        certificate = lineage.create_certificate(
            framework=framework,
            framework_version=framework_version,
            repository_commit=repository_commit,
            operator=source_operator,
            input_value=input_value,
            params=snapshot,
            sample_id=sample_id,
        )
        policy = dict(leaf_policy or {})
        sequence = lineage.child_sequence(snapshot)
        if sequence and (not policy or leaf_proof_set_sha256 in ("", "none")):
            raise RegistrationRejected(("missing_leaf_proof_policy",))
        targets: list[object] = []
        target_graphs: list[str] = []
        child_digests: list[str] = []
        reasons: list[str] = []
        for index in range(pool_size):
            target = target_factory()
            validation = lineage.validate_certificate(
                certificate,
                framework=framework,
                framework_version=framework_version,
                repository_commit=repository_commit,
                operator=target,
                input_value=input_value,
                params=snapshot,
                sample_id=sample_id,
            )
            if validation.decision == "reject":
                reasons.extend(f"target[{index}]:{reason}" for reason in validation.reasons)
            target_graphs.append(lineage.digest_payload(lineage.operator_graph(target)))
            if sequence:
                composite = lineage.compose_child_contracts(target, snapshot, policy)
                child_digests.append(lineage.digest_payload(composite))
                if composite.decision == "reject":
                    reasons.extend(f"target[{index}]:{reason}" for reason in composite.reasons)
            else:
                child_digests.append("none")
            targets.append(target)
        if reasons:
            raise RegistrationRejected(tuple(dict.fromkeys(reasons)))
        registration_payload = {
            "certificate_sha256": certificate.certificate_sha256,
            "leaf_proof_set_sha256": leaf_proof_set_sha256,
            "target_graph_sha256": target_graphs,
            "child_contract_sha256": child_digests,
            "pool_size": pool_size,
            "receipt_level": receipt_level,
        }
        registration_sha = lineage.digest_payload(registration_payload)
        registration_ms = (time.perf_counter_ns() - start) / 1e6
        registration = RegistrationReceipt(
            success=True,
            registration_sha256=registration_sha,
            certificate_sha256=certificate.certificate_sha256,
            leaf_proof_set_sha256=leaf_proof_set_sha256,
            target_graph_sha256=tuple(target_graphs),
            child_contract_sha256=tuple(child_digests),
            pool_size=pool_size,
            receipt_level=receipt_level,
            registration_ms=registration_ms,
            reasons=(),
        )
        return cls(
            certificate=certificate,
            snapshot=snapshot,
            targets=targets,
            leaf_policy=policy,
            registration=registration,
            receipt_level=receipt_level,
        )

    @property
    def registration_receipt(self) -> RegistrationReceipt:
        return self._registration

    def stats(self) -> ExecutorStats:
        with self._stats_lock:
            return ExecutorStats(*self._stats)

    def _increment(self, index: int) -> None:
        with self._stats_lock:
            self._stats[index] += 1

    def _reject(self, sample_id: str, reason: str) -> RegisteredReplayRejected:
        self._increment(1)
        return RegisteredReplayRejected(
            RegisteredApplyReceipt(
                success=False,
                registration_sha256=self._registration.registration_sha256,
                certificate_sha256=self._certificate.certificate_sha256,
                sample_id=sample_id,
                target_slot=-1,
                post_params_sha256="",
                output_sha256="",
                receipt_level=self._receipt_level,
                reasons=(reason,),
            )
        )

    def apply(self, *, input_value: object, sample_id: str) -> tuple[object, RegisteredApplyReceipt]:
        if sample_id != self._certificate.sample_id:
            raise self._reject(sample_id, "sample_lineage_mismatch")
        if lineage.digest_payload(lineage.input_schema(input_value)) != self._certificate.input_schema_sha256:
            raise self._reject(sample_id, "input_schema_mismatch")
        working = copy.deepcopy(self._snapshot)
        slot, target = self._pool.get()
        try:
            self._increment(2)
            output = target(input_value, params=working)  # type: ignore[operator]
            post_digest = lineage.digest_payload(working)
            if post_digest != self._certificate.params_sha256:
                self._increment(1)
                receipt = RegisteredApplyReceipt(
                    success=False,
                    registration_sha256=self._registration.registration_sha256,
                    certificate_sha256=self._certificate.certificate_sha256,
                    sample_id=sample_id,
                    target_slot=slot,
                    post_params_sha256=post_digest,
                    output_sha256="",
                    receipt_level=self._receipt_level,
                    reasons=("operator_mutated_working_record",),
                )
                raise RegisteredReplayRejected(receipt)
            output_digest = lineage.digest_payload(output) if self._receipt_level == "audit" else ""
            receipt = RegisteredApplyReceipt(
                success=True,
                registration_sha256=self._registration.registration_sha256,
                certificate_sha256=self._certificate.certificate_sha256,
                sample_id=sample_id,
                target_slot=slot,
                post_params_sha256=post_digest,
                output_sha256=output_digest,
                receipt_level=self._receipt_level,
                reasons=(),
            )
            self._increment(0)
            return output, receipt
        finally:
            self._pool.put((slot, target))


class _FakeOperator:
    def __init__(self, config: str = "a", mutate: bool = False) -> None:
        self.config, self.mutate, self.calls = config, mutate, 0

    def __repr__(self) -> str:
        return f"FakeOperator(config={self.config},mutate={self.mutate})"

    def named_modules(self): yield "", self
    def named_children(self): return iter(())

    def __call__(self, input_value, *, params):
        self.calls += 1
        output = (input_value, params["gain"])
        if self.mutate: params["gain"] += 1
        return output


def self_test() -> dict[str, bool]:
    minimal = RegisteredReplayExecutor.register(
        framework="fake", framework_version="1", repository_commit="abc",
        source_operator=_FakeOperator(), target_factory=lambda: _FakeOperator(),
        input_value="x", params={"gain": 2}, sample_id="s0", pool_size=2,
        receipt_level="minimal",
    )
    output, receipt = minimal.apply(input_value="x", sample_id="s0")
    before = minimal.stats()
    try:
        minimal.apply(input_value="x", sample_id="wrong")
        zero_call_reject = False
    except RegisteredReplayRejected:
        after = minimal.stats()
        zero_call_reject = after.operator_invocations == before.operator_invocations
    audit = RegisteredReplayExecutor.register(
        framework="fake", framework_version="1", repository_commit="abc",
        source_operator=_FakeOperator(), target_factory=lambda: _FakeOperator(),
        input_value="x", params={"gain": 2}, sample_id="s0", receipt_level="audit",
    )
    audit_output, audit_receipt = audit.apply(input_value="x", sample_id="s0")
    try:
        RegisteredReplayExecutor.register(
            framework="fake", framework_version="1", repository_commit="abc",
            source_operator=_FakeOperator("a"), target_factory=lambda: _FakeOperator("b"),
            input_value="x", params={"gain": 2}, sample_id="s0",
        )
        changed_rejected = False
    except RegistrationRejected:
        changed_rejected = True
    mutating = RegisteredReplayExecutor.register(
        framework="fake", framework_version="1", repository_commit="abc",
        source_operator=_FakeOperator(mutate=True), target_factory=lambda: _FakeOperator(mutate=True),
        input_value="x", params={"gain": 2}, sample_id="s0",
    )
    try:
        mutating.apply(input_value="x", sample_id="s0")
        mutation_rejected = False
    except RegisteredReplayRejected as error:
        mutation_rejected = "operator_mutated_working_record" in error.receipt.reasons
    return {
        "minimal_apply": output == ("x", 2) and receipt.output_sha256 == "",
        "audit_output_digest": audit_receipt.output_sha256 == lineage.digest_payload(audit_output),
        "dynamic_reject_zero_call": zero_call_reject,
        "changed_target_registration_reject": changed_rejected,
        "operator_mutation_reject": mutation_rejected,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    tests = self_test()
    payload = {"tests": tests, "passed": sum(tests.values()), "total": len(tests), "all_passed": all(tests.values())}
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
