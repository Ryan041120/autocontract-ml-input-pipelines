"""H7K runtime evaluation: registered replay with a private Kornia target pool."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import threading
import time
from dataclasses import asdict
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


SAMPLE_ID = "registered/sample0"


def row(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_executor(
    source: object,
    input_value: torch.Tensor,
    params: object,
    policy: dict[str, lineage.Decision],
    proof_digest: str,
    *,
    pool_size: int,
    receipt_level: registered.ReceiptLevel,
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
        sample_id=SAMPLE_ID,
        leaf_policy=policy,
        leaf_proof_set_sha256=proof_digest,
        pool_size=pool_size,
        receipt_level=receipt_level,
    )


def concurrent_run(
    executor: registered.RegisteredReplayExecutor,
    input_value: torch.Tensor,
    *,
    workers: int,
    calls_per_worker: int,
) -> tuple[float, list[str], list[int], list[str]]:
    outputs: list[str] = []
    slots: list[int] = []
    errors: list[str] = []
    result_lock = threading.Lock()

    def worker() -> None:
        try:
            local_outputs: list[str] = []
            local_slots: list[int] = []
            for _ in range(calls_per_worker):
                value, receipt = executor.apply(input_value=input_value, sample_id=SAMPLE_ID)
                local_outputs.append(lineage.digest_payload(value))
                local_slots.append(receipt.target_slot)
            with result_lock:
                outputs.extend(local_outputs)
                slots.extend(local_slots)
        except Exception as error:  # stress-test diagnostic capture
            with result_lock:
                errors.append(type(error).__name__ + ":" + str(error))

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    start = time.perf_counter_ns()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_ms = (time.perf_counter_ns() - start) / 1e6
    return elapsed_ms, outputs, slots, errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--calls-per-worker", type=int, default=25)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260731)

    source = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    recorded_output = source(input_value)
    external_params = copy.deepcopy(source._params)
    pristine_params = copy.deepcopy(source._params)
    proofs = auto.generate_leaf_proofs(source)
    policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])

    minimal = make_executor(
        source, input_value, external_params, policy, proof_digest,
        pool_size=args.workers, receipt_level="minimal",
    )
    audit = make_executor(
        source, input_value, pristine_params, policy, proof_digest,
        pool_size=1, receipt_level="audit",
    )
    minimal_output, minimal_receipt = minimal.apply(input_value=input_value, sample_id=SAMPLE_ID)
    audit_output, audit_receipt = audit.apply(input_value=input_value, sample_id=SAMPLE_ID)
    registration = minimal.registration_receipt
    tests: list[dict[str, object]] = [
        row(
            "auto_leaf_proofs",
            auto.verify_leaf_proofs(proofs) and all(value == "admit" for value in policy.values()),
            proof_digest,
        ),
        row(
            "registration_binds_pool_and_child_proofs",
            registration.success
            and registration.pool_size == args.workers
            and registration.leaf_proof_set_sha256 == proof_digest
            and len(set(registration.target_graph_sha256)) == 1
            and all(value not in ("", "none") for value in registration.child_contract_sha256),
            registration.registration_sha256,
        ),
        row(
            "minimal_output_trace_without_output_digest",
            torch.equal(recorded_output, minimal_output) and minimal_receipt.output_sha256 == "",
            lineage.digest_payload(minimal_output),
        ),
        row(
            "audit_output_trace_with_output_digest",
            torch.equal(recorded_output, audit_output)
            and audit_receipt.output_sha256 == lineage.digest_payload(audit_output),
            audit_receipt.output_sha256,
        ),
    ]

    before = minimal.stats()
    try:
        minimal.apply(input_value=input_value, sample_id="registered/wrong")
        wrong_sample_ok, wrong_sample_detail = False, "not_rejected"
    except registered.RegisteredReplayRejected as error:
        after = minimal.stats()
        wrong_sample_ok = after.operator_invocations == before.operator_invocations
        wrong_sample_detail = ";".join(error.receipt.reasons)
    tests.append(row("wrong_sample_zero_operator_calls", wrong_sample_ok, wrong_sample_detail))

    before = minimal.stats()
    try:
        minimal.apply(input_value=torch.rand(4, 3, 32, 32), sample_id=SAMPLE_ID)
        wrong_schema_ok, wrong_schema_detail = False, "not_rejected"
    except registered.RegisteredReplayRejected as error:
        after = minimal.stats()
        wrong_schema_ok = after.operator_invocations == before.operator_invocations
        wrong_schema_detail = ";".join(error.receipt.reasons)
    tests.append(row("wrong_input_schema_zero_operator_calls", wrong_schema_ok, wrong_schema_detail))

    with torch.no_grad():
        external_params[1].data["angle"][0] += 20.0
    isolated_output, _ = minimal.apply(input_value=input_value, sample_id=SAMPLE_ID)
    tests.append(row(
        "original_record_mutation_isolated",
        torch.equal(recorded_output, isolated_output),
        lineage.digest_payload(isolated_output),
    ))

    x_direct = input_value.clone().requires_grad_(True)
    x_registered = input_value.clone().requires_grad_(True)
    direct_output = pilot.build_pipeline()(x_direct, params=copy.deepcopy(pristine_params))
    registered_output, _ = minimal.apply(input_value=x_registered, sample_id=SAMPLE_ID)
    weight = torch.linspace(0.5, 1.5, direct_output.numel()).reshape_as(direct_output)
    (direct_output * weight).sum().backward()
    (registered_output * weight).sum().backward()
    tests.append(row(
        "registered_gradient_trace",
        torch.equal(x_direct.grad, x_registered.grad),
        f"direct={lineage.digest_payload(x_direct.grad)},registered={lineage.digest_payload(x_registered.grad)}",
    ))

    try:
        make_executor(
            source, input_value, pristine_params, policy, proof_digest,
            pool_size=1, receipt_level="minimal",
            factory=lambda: pilot.build_pipeline(affine_degrees=30.0),
        )
        changed_target_ok, changed_target_detail = False, "not_rejected"
    except registered.RegistrationRejected as error:
        changed_target_ok, changed_target_detail = True, ";".join(error.reasons)
    tests.append(row("changed_target_rejected_at_registration", changed_target_ok, changed_target_detail))

    missing_policy = dict(policy)
    missing_policy.pop("kornia.augmentation._2d.geometric.affine.RandomAffine")
    try:
        make_executor(
            source, input_value, pristine_params, missing_policy, proof_digest,
            pool_size=1, receipt_level="minimal",
        )
        missing_proof_ok, missing_proof_detail = False, "not_rejected"
    except registered.RegistrationRejected as error:
        missing_proof_ok, missing_proof_detail = True, ";".join(error.reasons)
    tests.append(row("missing_child_proof_rejected_at_registration", missing_proof_ok, missing_proof_detail))

    mutating_source = h7j_runtime.build_mutating_pipeline()
    mutating_source(input_value)
    mutating_params = copy.deepcopy(mutating_source._params)
    mutating_proofs = auto.generate_leaf_proofs(mutating_source)
    mutating_policy = auto.policy_from_proofs(mutating_proofs)
    mutating_digest = lineage.digest_payload([asdict(proof) for proof in mutating_proofs])
    mutating_executor = make_executor(
        mutating_source, input_value, mutating_params, mutating_policy, mutating_digest,
        pool_size=1, receipt_level="minimal", factory=h7j_runtime.build_mutating_pipeline,
    )
    try:
        mutating_executor.apply(input_value=input_value, sample_id=SAMPLE_ID)
        mutation_ok, mutation_detail = False, "not_rejected"
    except registered.RegisteredReplayRejected as error:
        mutation_ok = "operator_mutated_working_record" in error.receipt.reasons
        mutation_detail = ";".join(error.receipt.reasons)
    tests.append(row("operator_mutation_output_not_released", mutation_ok, mutation_detail))

    stop = threading.Event()

    def mutate_original() -> None:
        delta = 1.0
        while not stop.is_set():
            with torch.no_grad():
                external_params[1].data["angle"][0] += delta
            delta = -delta

    rng_before = torch.get_rng_state().clone()
    mutator = threading.Thread(target=mutate_original, daemon=True)
    mutator.start()
    elapsed_ms, outputs, slots, errors = concurrent_run(
        minimal, input_value, workers=args.workers, calls_per_worker=args.calls_per_worker,
    )
    stop.set()
    mutator.join(timeout=2.0)
    rng_after = torch.get_rng_state().clone()
    expected_calls = args.workers * args.calls_per_worker
    expected_digest = lineage.digest_payload(recorded_output)
    tests.append(row(
        "private_pool_concurrent_correctness",
        len(outputs) == expected_calls and not errors and set(outputs) == {expected_digest},
        f"calls={len(outputs)}/{expected_calls},errors={errors},slots={sorted(set(slots))}",
    ))
    tests.append(row(
        "concurrent_replay_rng_unchanged",
        torch.equal(rng_before, rng_after),
        lineage.digest_payload(rng_before),
    ))
    stats = minimal.stats()
    tests.append(row(
        "executor_accounting",
        stats.successful_calls == expected_calls + 3
        and stats.rejected_calls == 2
        and stats.operator_invocations == stats.successful_calls,
        json.dumps(asdict(stats), sort_keys=True),
    ))

    throughput = expected_calls / (elapsed_ms / 1000.0)
    performance = [{
        "pool_size": args.workers,
        "workers": args.workers,
        "calls": expected_calls,
        "elapsed_ms": elapsed_ms,
        "calls_per_second": throughput,
        "registration_ms": registration.registration_ms,
    }]
    write_csv(OUT / "autocontract_h7k_runtime_tests.csv", tests)
    write_csv(OUT / "autocontract_h7k_pool_performance.csv", performance)
    (OUT / "autocontract_h7k_registration_receipt.json").write_text(
        json.dumps(asdict(registration), indent=2), encoding="utf-8",
    )
    passed = sum(item["passed"] is True for item in tests)
    report = "\n".join([
        "# AutoContract H7K registered Kornia replay",
        "",
        f"Correctness/security tests: {passed}/{len(tests)}.",
        f"Registration: {registration.registration_ms:.3f} ms for pool size {args.workers}.",
        f"Concurrent minimal receipts: {len(outputs)}/{expected_calls} correct calls in {elapsed_ms:.3f} ms ({throughput:.1f} calls/s).",
        f"Target slots observed: {sorted(set(slots))}; errors: {len(errors)}.",
        "",
        "| Test | Pass | Detail |",
        "|---|---|---|",
        *[f"| {item['test']} | {item['passed']} | {item['detail']} |" for item in tests],
        "",
        "Static graph, version, leaf-proof, and child-composition checks are cached at registration. "
        "Each call still verifies sample lineage and input schema, copies the private parameter snapshot, "
        "leases an owned target, and checks the post-use parameter digest before releasing output.",
        "",
    ])
    (OUT / "autocontract_h7k_kornia_registered.md").write_text(report, encoding="utf-8")
    print(report)
    if passed != len(tests):
        raise RuntimeError("H7K runtime evaluation failed")


if __name__ == "__main__":
    main()
