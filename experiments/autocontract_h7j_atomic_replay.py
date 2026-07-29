"""Sealed replay records with an atomic validate-compose-apply boundary."""

from __future__ import annotations

import argparse
import copy
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import autocontract_h7i_lineage_certificate as lineage


@dataclass(frozen=True)
class AtomicApplyReceipt:
    success: bool
    sample_id: str
    certificate_sha256: str
    pre_params_sha256: str
    post_params_sha256: str
    child_contract_sha256: str
    leaf_proof_set_sha256: str
    output_sha256: str
    operator_called: bool
    reasons: tuple[str, ...]


class AtomicReplayRejected(RuntimeError):
    def __init__(self, receipt: AtomicApplyReceipt) -> None:
        super().__init__("atomic replay rejected: " + (",".join(receipt.reasons) or "unknown"))
        self.receipt = receipt


class SealedReplayRecord:
    """Own a private parameter snapshot and never pass that snapshot to an operator."""

    __slots__ = (
        "_certificate",
        "_leaf_policy",
        "_leaf_proof_set_sha256",
        "_lock",
        "_snapshot",
    )

    def __init__(
        self,
        certificate: lineage.ReplayLineageCertificate,
        snapshot: object,
        leaf_policy: Mapping[str, lineage.Decision],
        leaf_proof_set_sha256: str,
    ) -> None:
        self._certificate = certificate
        self._snapshot = copy.deepcopy(snapshot)
        self._leaf_policy = dict(leaf_policy)
        self._leaf_proof_set_sha256 = leaf_proof_set_sha256
        self._lock = threading.RLock()

    @classmethod
    def seal(
        cls,
        *,
        framework: str,
        framework_version: str,
        repository_commit: str,
        operator: object,
        input_value: object,
        params: object,
        sample_id: str,
        leaf_policy: Mapping[str, lineage.Decision] | None = None,
        leaf_proof_set_sha256: str = "none",
    ) -> "SealedReplayRecord":
        snapshot = copy.deepcopy(params)
        certificate = lineage.create_certificate(
            framework=framework,
            framework_version=framework_version,
            repository_commit=repository_commit,
            operator=operator,
            input_value=input_value,
            params=snapshot,
            sample_id=sample_id,
        )
        return cls(certificate, snapshot, leaf_policy or {}, leaf_proof_set_sha256)

    @property
    def certificate(self) -> lineage.ReplayLineageCertificate:
        return self._certificate

    def _receipt(
        self,
        *,
        success: bool,
        sample_id: str,
        pre_digest: str,
        post_digest: str = "",
        child_digest: str = "",
        output_digest: str = "",
        operator_called: bool = False,
        reasons: tuple[str, ...] = (),
    ) -> AtomicApplyReceipt:
        return AtomicApplyReceipt(
            success=success,
            sample_id=sample_id,
            certificate_sha256=self._certificate.certificate_sha256,
            pre_params_sha256=pre_digest,
            post_params_sha256=post_digest,
            child_contract_sha256=child_digest,
            leaf_proof_set_sha256=self._leaf_proof_set_sha256,
            output_sha256=output_digest,
            operator_called=operator_called,
            reasons=reasons,
        )

    def atomic_apply(
        self,
        *,
        operator: object,
        input_value: object,
        sample_id: str,
    ) -> tuple[object, AtomicApplyReceipt]:
        """Return output only after preconditions and the post-use digest pass."""
        with self._lock:
            working = copy.deepcopy(self._snapshot)
            pre_digest = lineage.digest_payload(working)
            validation = lineage.validate_certificate(
                self._certificate,
                framework=self._certificate.framework,
                framework_version=self._certificate.framework_version,
                repository_commit=self._certificate.repository_commit,
                operator=operator,
                input_value=input_value,
                params=working,
                sample_id=sample_id,
            )
            if validation.decision == "reject":
                receipt = self._receipt(
                    success=False,
                    sample_id=sample_id,
                    pre_digest=pre_digest,
                    reasons=validation.reasons,
                )
                raise AtomicReplayRejected(receipt)

            child_digest = "none"
            sequence = lineage.child_sequence(working)
            if sequence:
                if not self._leaf_policy or self._leaf_proof_set_sha256 in ("", "none"):
                    receipt = self._receipt(
                        success=False,
                        sample_id=sample_id,
                        pre_digest=pre_digest,
                        reasons=("missing_leaf_proof_policy",),
                    )
                    raise AtomicReplayRejected(receipt)
                composite = lineage.compose_child_contracts(operator, working, self._leaf_policy)
                child_digest = lineage.digest_payload(composite)
                if composite.decision == "reject":
                    receipt = self._receipt(
                        success=False,
                        sample_id=sample_id,
                        pre_digest=pre_digest,
                        child_digest=child_digest,
                        reasons=composite.reasons,
                    )
                    raise AtomicReplayRejected(receipt)

            output = operator(input_value, params=working)  # type: ignore[operator]
            post_digest = lineage.digest_payload(working)
            if post_digest != pre_digest or post_digest != self._certificate.params_sha256:
                receipt = self._receipt(
                    success=False,
                    sample_id=sample_id,
                    pre_digest=pre_digest,
                    post_digest=post_digest,
                    child_digest=child_digest,
                    operator_called=True,
                    reasons=("operator_mutated_working_record",),
                )
                raise AtomicReplayRejected(receipt)
            receipt = self._receipt(
                success=True,
                sample_id=sample_id,
                pre_digest=pre_digest,
                post_digest=post_digest,
                child_digest=child_digest,
                output_digest=lineage.digest_payload(output),
                operator_called=True,
            )
            return output, receipt


class _FakeOperator:
    def __init__(self, *, mutate: bool = False) -> None:
        self.mutate = mutate
        self.calls = 0

    def __repr__(self) -> str:
        return f"FakeOperator(mutate={self.mutate})"

    def named_modules(self):
        yield "", self

    def named_children(self):
        return iter(())

    def __call__(self, input_value, *, params):
        self.calls += 1
        result = (input_value, params["gain"])
        if self.mutate:
            params["gain"] += 1
        return result


def self_test() -> dict[str, bool]:
    source = _FakeOperator()
    sealed = SealedReplayRecord.seal(
        framework="fake",
        framework_version="1",
        repository_commit="abc",
        operator=source,
        input_value="x",
        params={"gain": 2},
        sample_id="s0",
    )
    target = _FakeOperator()
    output, receipt = sealed.atomic_apply(operator=target, input_value="x", sample_id="s0")
    wrong_target = _FakeOperator()
    try:
        sealed.atomic_apply(operator=wrong_target, input_value="x", sample_id="s1")
        wrong_rejected = False
    except AtomicReplayRejected as error:
        wrong_rejected = not error.receipt.operator_called and wrong_target.calls == 0

    mutating_source = _FakeOperator(mutate=True)
    mutating = SealedReplayRecord.seal(
        framework="fake",
        framework_version="1",
        repository_commit="abc",
        operator=mutating_source,
        input_value="x",
        params={"gain": 2},
        sample_id="s0",
    )
    mutating_target = _FakeOperator(mutate=True)
    try:
        mutating.atomic_apply(operator=mutating_target, input_value="x", sample_id="s0")
        mutation_rejected = False
    except AtomicReplayRejected as error:
        mutation_rejected = error.receipt.operator_called and "operator_mutated_working_record" in error.receipt.reasons
    return {
        "valid_apply": output == ("x", 2) and receipt.success,
        "receipt_binds_output": receipt.output_sha256 == lineage.digest_payload(output),
        "precondition_zero_call": wrong_rejected,
        "operator_mutation_no_output": mutation_rejected,
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
