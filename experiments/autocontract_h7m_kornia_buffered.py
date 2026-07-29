"""H7M real Kornia evaluation for signed Merkle batches and buffered release."""

from __future__ import annotations

import argparse
import base64
import copy
import csv
import sys
import threading
from dataclasses import asdict, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import torch  # noqa: E402
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_h7j_kornia_atomic as h7j_runtime  # noqa: E402
import autocontract_h7k_registered_executor as registered  # noqa: E402
import autocontract_h7l_provenance_token as h7l  # noqa: E402
import autocontract_h7m_batch_lease as batch  # noqa: E402
import autocontract_h7m_buffered_executor as buffered  # noqa: E402


def result(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def register_executor(
    source: object,
    input_value: torch.Tensor,
    params: object,
    leaf_policy: dict[str, lineage.Decision],
    proof_digest: str,
    sample_id: str,
    *,
    factory=pilot.build_pipeline,
) -> registered.RegisteredReplayExecutor:
    return registered.RegisteredReplayExecutor.register(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        source_operator=source,
        target_factory=factory,
        input_value=input_value,
        params=params,
        sample_id=sample_id,
        leaf_policy=leaf_policy,
        leaf_proof_set_sha256=proof_digest,
        pool_size=1,
        receipt_level="minimal",
    )


def expectations_for(
    inputs: tuple[torch.Tensor, ...],
    executors: tuple[registered.RegisteredReplayExecutor, ...],
    *,
    run_id: str = "h7m/run0",
) -> tuple[h7l.ProvenanceExpectation, ...]:
    records = {str(index): lineage.digest_payload(value) for index, value in enumerate(inputs)}
    manifest = h7l.dataset_manifest_digest(records)
    sampler_digest = lineage.digest_payload({"sampler": "batch-sequential", "epoch": 5, "size": len(inputs)})
    return tuple(
        h7l.ProvenanceExpectation(
            run_id=run_id,
            replay_sample_id=f"h7m/sample{index}",
            dataset_id="h7m-images",
            dataset_revision="sha256:h7m-rev0",
            split="train",
            dataset_manifest_sha256=manifest,
            epoch=5,
            sampler_context_sha256=sampler_digest,
            subjects=(h7l.SubjectClaim("primary", str(index), records[str(index)]),),
            operator_path="train/input/augment",
            registration_sha256=executor.registration_receipt.registration_sha256,
            input_content_sha256=records[str(index)],
        )
        for index, executor in enumerate(executors)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=4)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260805)

    inputs = tuple(torch.rand(1, 3, 64, 64) for _ in range(args.batch_size))
    sources: list[object] = []
    params: list[object] = []
    expected_outputs: list[torch.Tensor] = []
    for input_value in inputs:
        source = pilot.build_pipeline()
        with torch.no_grad():
            expected_output = source(input_value)
        sources.append(source)
        params.append(copy.deepcopy(source._params))
        expected_outputs.append(expected_output)
    proofs = auto.generate_leaf_proofs(sources[0])
    leaf_policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    executors = tuple(
        register_executor(source, input_value, parameter, leaf_policy, proof_digest, f"h7m/sample{index}")
        for index, (source, input_value, parameter) in enumerate(zip(sources, inputs, params))
    )
    policies = expectations_for(inputs, executors)
    authority = batch.BatchAuthority.generate()
    verifier = batch.BatchVerifier(authority.public_key_bytes())
    registry = batch.SqliteBatchRegistry(
        OUT / "autocontract_h7m_kornia_registry.sqlite",
        reset=True,
        persistent_connections=True,
    )
    secured = buffered.BufferedBatchExecutor(executors, verifier, registry, policies)

    tickets = authority.issue_batch(policies, batch_id="h7m/valid")
    registry.register(tickets[0].root)
    rng_before = torch.get_rng_state().clone()
    outputs, receipt = secured.apply_batch(inputs=inputs, tickets=tickets, worker_id="main/valid")
    rng_after = torch.get_rng_state().clone()
    tests: list[dict[str, object]] = [
        result(
            "heterogeneous_parameter_batch_output_trace",
            all(torch.equal(left, right) for left, right in zip(outputs, expected_outputs)),
            receipt.output_sha256,
        ),
        result(
            "batch_commit_before_release",
            receipt.commit.output_sha256 == receipt.output_sha256
            and registry.state("h7m/valid")["state"] == "committed",  # type: ignore[index]
            str(registry.state("h7m/valid")),
        ),
        result("batch_rng_unchanged", torch.equal(rng_before, rng_after), lineage.digest_payload(rng_before)),
        result("one_signature_verified_for_batch", verifier.signature_verifications == 1, str(verifier.signature_verifications)),
    ]

    before = secured.operator_invocations()
    try:
        secured.apply_batch(inputs=inputs, tickets=tickets, worker_id="main/duplicate")
        duplicate_ok, duplicate_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        duplicate_ok = secured.operator_invocations() == before and "batch_committed" in error.reasons
        duplicate_detail = ";".join(error.reasons)
    tests.append(result("duplicate_batch_zero_operator_calls", duplicate_ok, duplicate_detail))

    gradient_tickets = authority.issue_batch(policies, batch_id="h7m/gradient")
    registry.register(gradient_tickets[0].root)
    direct_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)
    bound_inputs = tuple(value.clone().requires_grad_(True) for value in inputs)
    direct_outputs = tuple(
        pilot.build_pipeline()(value, params=copy.deepcopy(parameter))
        for value, parameter in zip(direct_inputs, params)
    )
    batch_outputs, _ = secured.apply_batch(
        inputs=bound_inputs, tickets=gradient_tickets, worker_id="main/gradient",
    )
    direct_loss = sum((value * torch.linspace(0.5, 1.5, value.numel()).reshape_as(value)).sum() for value in direct_outputs)
    batch_loss = sum((value * torch.linspace(0.5, 1.5, value.numel()).reshape_as(value)).sum() for value in batch_outputs)
    direct_loss.backward()
    batch_loss.backward()
    tests.append(result(
        "buffered_batch_gradient_trace",
        all(torch.equal(left.grad, right.grad) for left, right in zip(direct_inputs, bound_inputs)),
        ",".join(lineage.digest_payload(value.grad) for value in bound_inputs),
    ))

    wrong_input_tickets = authority.issue_batch(policies, batch_id="h7m/wrong-input")
    registry.register(wrong_input_tickets[0].root)
    wrong_inputs = list(inputs)
    wrong_inputs[1] = wrong_inputs[1].clone()
    wrong_inputs[1].reshape(-1)[0] += 1.0
    before = secured.operator_invocations()
    try:
        secured.apply_batch(inputs=tuple(wrong_inputs), tickets=wrong_input_tickets, worker_id="attack/input")
        wrong_input_ok, wrong_input_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        wrong_input_ok = secured.operator_invocations() == before
        wrong_input_detail = ";".join(error.reasons)
    tests.append(result("wrong_input_zero_operator_calls", wrong_input_ok, wrong_input_detail))

    reorder_tickets = authority.issue_batch(policies, batch_id="h7m/reorder")
    registry.register(reorder_tickets[0].root)
    before = secured.operator_invocations()
    try:
        secured.apply_batch(inputs=inputs, tickets=tuple(reversed(reorder_tickets)), worker_id="attack/reorder")
        reorder_ok, reorder_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        reorder_ok = secured.operator_invocations() == before and "ticket_order_mismatch" in error.reasons
        reorder_detail = ";".join(error.reasons)
    tests.append(result("ticket_reorder_zero_operator_calls", reorder_ok, reorder_detail))

    proof_tickets = authority.issue_batch(policies, batch_id="h7m/proof")
    registry.register(proof_tickets[0].root)
    broken_node = replace(proof_tickets[0].proof[0], sha256="0" * 64)
    broken_ticket = replace(proof_tickets[0], proof=(broken_node,) + proof_tickets[0].proof[1:])
    broken_batch = (broken_ticket,) + proof_tickets[1:]
    before = secured.operator_invocations()
    try:
        secured.apply_batch(inputs=inputs, tickets=broken_batch, worker_id="attack/proof")
        proof_ok, proof_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        proof_ok = secured.operator_invocations() == before and "merkle_inclusion_mismatch" in error.reasons
        proof_detail = ";".join(error.reasons)
    tests.append(result("merkle_proof_tamper_zero_operator_calls", proof_ok, proof_detail))

    cache_tickets = authority.issue_batch(policies, batch_id="h7m/cache-alias")
    registry.register(cache_tickets[0].root)
    verifier.verify_batch(cache_tickets, policies)
    altered_statement = replace(cache_tickets[0].root.statement, batch_id="h7m/cache-forged")
    forged_root = replace(cache_tickets[0].root, statement=altered_statement)
    forged_tickets = tuple(replace(ticket, root=forged_root) for ticket in cache_tickets)
    before = secured.operator_invocations()
    try:
        secured.apply_batch(inputs=inputs, tickets=forged_tickets, worker_id="attack/cache")
        cache_ok, cache_detail = False, "not_rejected"
    except batch.BatchRejected as error:
        cache_ok = secured.operator_invocations() == before and "batch_attestation_digest_mismatch" in error.reasons
        cache_detail = ";".join(error.reasons)
    tests.append(result("cached_attestation_alias_tamper_rejected", cache_ok, cache_detail))

    concurrent_tickets = authority.issue_batch(policies, batch_id="h7m/concurrent")
    registry.register(concurrent_tickets[0].root)
    concurrent_success: list[str] = []
    concurrent_errors: list[str] = []
    list_lock = threading.Lock()
    before = secured.operator_invocations()

    def contender(index: int) -> None:
        try:
            values, call_receipt = secured.apply_batch(
                inputs=inputs,
                tickets=concurrent_tickets,
                worker_id=f"concurrent/{index}",
            )
            with list_lock:
                concurrent_success.append(lineage.digest_payload(values) + ":" + call_receipt.batch_id)
        except batch.BatchRejected as error:
            with list_lock:
                concurrent_errors.append(",".join(error.reasons))

    threads = [threading.Thread(target=contender, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    invocation_delta = secured.operator_invocations() - before
    tests.append(result(
        "four_way_batch_claim_one_release",
        len(concurrent_success) == 1 and len(concurrent_errors) == 3 and invocation_delta == args.batch_size,
        f"success={len(concurrent_success)},reject={len(concurrent_errors)},invocations={invocation_delta},reasons={concurrent_errors}",
    ))

    mutating_input = torch.rand(1, 3, 64, 64)
    mutating_source = h7j_runtime.build_mutating_pipeline()
    with torch.no_grad():
        mutating_source(mutating_input)
    mutating_params = copy.deepcopy(mutating_source._params)
    mutating_proofs = auto.generate_leaf_proofs(mutating_source)
    mutating_policy = auto.policy_from_proofs(mutating_proofs)
    mutating_executor = register_executor(
        mutating_source,
        mutating_input,
        mutating_params,
        mutating_policy,
        lineage.digest_payload([asdict(proof) for proof in mutating_proofs]),
        "h7m/sample0",
        factory=h7j_runtime.build_mutating_pipeline,
    )
    mutating_policies = expectations_for((mutating_input,), (mutating_executor,), run_id="h7m/mutating")
    mutating_tickets = authority.issue_batch(mutating_policies, batch_id="h7m/mutating")
    registry.register(mutating_tickets[0].root)
    mutating_buffered = buffered.BufferedBatchExecutor(
        (mutating_executor,), verifier, registry, mutating_policies,
    )
    try:
        mutating_buffered.apply_batch(
            inputs=(mutating_input,), tickets=mutating_tickets, worker_id="attack/operator-mutation",
        )
        mutation_ok, mutation_detail = False, "not_rejected"
    except registered.RegisteredReplayRejected as error:
        state = registry.state("h7m/mutating")
        mutation_ok = "operator_mutated_working_record" in error.receipt.reasons and state["state"] == "issued"  # type: ignore[index]
        mutation_detail = f"reasons={error.receipt.reasons},state={state}"
    tests.append(result("operator_failure_aborts_batch_without_release", mutation_ok, mutation_detail))

    write_csv(OUT / "autocontract_h7m_kornia_tests.csv", tests)
    passed = sum(item["passed"] is True for item in tests)
    report = "\n".join([
        "# AutoContract H7M buffered Merkle-batch Kornia replay",
        "",
        f"Correctness/security tests: {passed}/{len(tests)}; batch size: {args.batch_size}.",
        f"Root signature verifications performed: {verifier.signature_verifications} across multiple batches; each root is cached only after digest/schema/key authentication.",
        "",
        "| Test | Pass | Detail |",
        "|---|---|---|",
        *[f"| {item['test']} | {item['passed']} | {item['detail']} |" for item in tests],
        "",
        "Outputs remain buffered until the fenced lease commits. This provides batch authorization/commit safety, not optimizer-side-effect exactly-once.",
        "",
    ])
    (OUT / "autocontract_h7m_kornia_buffered.md").write_text(report, encoding="utf-8")
    print(report)
    registry.close()
    if passed != len(tests):
        raise RuntimeError("H7M Kornia evaluation failed")


if __name__ == "__main__":
    main()
