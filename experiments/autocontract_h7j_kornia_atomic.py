"""Runtime and concurrency evaluation of H7J atomic Kornia replay."""

from __future__ import annotations

import argparse
import copy
import csv
import statistics
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
import kornia.augmentation as K  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_atomic_replay as atomic  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402


class MutatingSequential(K.AugmentationSequential):
    def forward(self, *args, params=None, data_keys=None):
        output = super().forward(*args, params=params, data_keys=data_keys)
        if params is not None:
            with torch.no_grad():
                params[1].data["angle"][0] += 1.0
        return output


def build_mutating_pipeline():
    return MutatingSequential(
        K.RandomHorizontalFlip(p=0.5),
        K.RandomAffine(15.0, p=1.0),
        K.ColorJiggle(0.1, 0.1, 0.1, 0.1, p=1.0),
    )


def result_row(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"test": name, "passed": passed, "detail": detail}


def timed(callable_obj, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--calls-per-worker", type=int, default=25)
    parser.add_argument("--iterations", type=int, default=20)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260730)

    source = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    recorded_output = source(input_value)
    external_params = copy.deepcopy(source._params)
    baseline_params = copy.deepcopy(source._params)
    proofs = auto.generate_leaf_proofs(source)
    policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    sealed = atomic.SealedReplayRecord.seal(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=source,
        input_value=input_value,
        params=external_params,
        sample_id="atomic/sample0",
        leaf_policy=policy,
        leaf_proof_set_sha256=proof_digest,
    )
    target = pilot.build_pipeline()
    output, receipt = sealed.atomic_apply(operator=target, input_value=input_value, sample_id="atomic/sample0")
    tests: list[dict[str, object]] = [
        result_row("auto_leaf_proofs", auto.verify_leaf_proofs(proofs) and all(value == "admit" for value in policy.values()), proof_digest),
        result_row("atomic_output_trace", torch.equal(recorded_output, output), receipt.output_sha256),
        result_row("receipt_pre_post_binding", receipt.success and receipt.pre_params_sha256 == receipt.post_params_sha256 == sealed.certificate.params_sha256, receipt.pre_params_sha256),
        result_row("receipt_child_proof_binding", receipt.child_contract_sha256 not in ("", "none") and receipt.leaf_proof_set_sha256 == proof_digest, receipt.child_contract_sha256),
    ]

    with torch.no_grad():
        external_params[1].data["angle"][0] += 20.0
    after_external_mutation, _ = sealed.atomic_apply(operator=target, input_value=input_value, sample_id="atomic/sample0")
    tests.append(result_row("serial_original_mutation_isolated", torch.equal(recorded_output, after_external_mutation), lineage.digest_payload(after_external_mutation)))

    with torch.no_grad():
        target._params[1].data["angle"][0] += 30.0
    after_exposed_mutation, _ = sealed.atomic_apply(operator=target, input_value=input_value, sample_id="atomic/sample0")
    tests.append(result_row("target_exposed_params_do_not_poison_next_call", torch.equal(recorded_output, after_exposed_mutation), lineage.digest_payload(after_exposed_mutation)))

    hook_calls = {"count": 0}
    rejection_target = pilot.build_pipeline()
    hook = rejection_target.register_forward_pre_hook(lambda *_: hook_calls.__setitem__("count", hook_calls["count"] + 1))
    try:
        sealed.atomic_apply(operator=rejection_target, input_value=input_value, sample_id="atomic/wrong")
        wrong_sample_rejected = False
        rejection_detail = "not_rejected"
    except atomic.AtomicReplayRejected as error:
        wrong_sample_rejected = not error.receipt.operator_called and hook_calls["count"] == 0
        rejection_detail = ";".join(error.receipt.reasons)
    finally:
        hook.remove()
    tests.append(result_row("wrong_sample_zero_operator_calls", wrong_sample_rejected, rejection_detail))

    missing_policy = dict(policy)
    missing_policy.pop("kornia.augmentation._2d.geometric.affine.RandomAffine")
    incomplete = atomic.SealedReplayRecord.seal(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=source,
        input_value=input_value,
        params=baseline_params,
        sample_id="atomic/sample0",
        leaf_policy=missing_policy,
        leaf_proof_set_sha256=proof_digest,
    )
    incomplete_target = pilot.build_pipeline()
    incomplete_calls = {"count": 0}
    hook = incomplete_target.register_forward_pre_hook(lambda *_: incomplete_calls.__setitem__("count", incomplete_calls["count"] + 1))
    try:
        incomplete.atomic_apply(operator=incomplete_target, input_value=input_value, sample_id="atomic/sample0")
        incomplete_rejected = False
        incomplete_detail = "not_rejected"
    except atomic.AtomicReplayRejected as error:
        incomplete_rejected = not error.receipt.operator_called and incomplete_calls["count"] == 0
        incomplete_detail = ";".join(error.receipt.reasons)
    finally:
        hook.remove()
    tests.append(result_row("missing_child_proof_zero_operator_calls", incomplete_rejected, incomplete_detail))

    mutating_source = build_mutating_pipeline()
    mutating_source(input_value)
    mutating_params = copy.deepcopy(mutating_source._params)
    mutating_proofs = auto.generate_leaf_proofs(mutating_source)
    mutating_sealed = atomic.SealedReplayRecord.seal(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=mutating_source,
        input_value=input_value,
        params=mutating_params,
        sample_id="atomic/mutating",
        leaf_policy=auto.policy_from_proofs(mutating_proofs),
        leaf_proof_set_sha256=lineage.digest_payload([asdict(proof) for proof in mutating_proofs]),
    )
    try:
        mutating_sealed.atomic_apply(operator=build_mutating_pipeline(), input_value=input_value, sample_id="atomic/mutating")
        operator_mutation_rejected = False
        mutation_detail = "not_rejected"
    except atomic.AtomicReplayRejected as error:
        operator_mutation_rejected = error.receipt.operator_called and "operator_mutated_working_record" in error.receipt.reasons
        mutation_detail = ";".join(error.receipt.reasons)
    tests.append(result_row("operator_mutation_output_not_released", operator_mutation_rejected, mutation_detail))

    x_direct = input_value.clone().requires_grad_(True)
    x_atomic = input_value.clone().requires_grad_(True)
    direct_target = pilot.build_pipeline()
    atomic_target = pilot.build_pipeline()
    direct_output = direct_target(x_direct, params=copy.deepcopy(baseline_params))
    atomic_output, _ = sealed.atomic_apply(operator=atomic_target, input_value=x_atomic, sample_id="atomic/sample0")
    weight = torch.linspace(0.5, 1.5, direct_output.numel()).reshape_as(direct_output)
    (direct_output * weight).sum().backward(); (atomic_output * weight).sum().backward()
    tests.append(result_row("atomic_gradient_trace", torch.equal(x_direct.grad, x_atomic.grad), f"direct={lineage.digest_payload(x_direct.grad)},atomic={lineage.digest_payload(x_atomic.grad)}"))

    stop = threading.Event()
    concurrent_outputs: list[str] = []
    concurrent_receipts: list[str] = []
    concurrent_errors: list[str] = []
    list_lock = threading.Lock()
    shared_target = pilot.build_pipeline()

    def mutate_original() -> None:
        delta = 1.0
        while not stop.is_set():
            with torch.no_grad():
                external_params[1].data["angle"][0] += delta
            delta = -delta

    def worker() -> None:
        try:
            for _ in range(args.calls_per_worker):
                value, call_receipt = sealed.atomic_apply(operator=shared_target, input_value=input_value, sample_id="atomic/sample0")
                with list_lock:
                    concurrent_outputs.append(lineage.digest_payload(value))
                    concurrent_receipts.append(call_receipt.output_sha256)
        except Exception as error:  # diagnostic capture for the stress test
            with list_lock:
                concurrent_errors.append(type(error).__name__ + ":" + str(error))

    rng_before = torch.get_rng_state().clone()
    mutator = threading.Thread(target=mutate_original, daemon=True)
    workers = [threading.Thread(target=worker) for _ in range(args.workers)]
    mutator.start()
    for thread in workers: thread.start()
    for thread in workers: thread.join()
    stop.set(); mutator.join(timeout=2.0)
    rng_after = torch.get_rng_state().clone()
    expected_digest = lineage.digest_payload(recorded_output)
    expected_calls = args.workers * args.calls_per_worker
    concurrency_ok = (
        not concurrent_errors
        and len(concurrent_outputs) == expected_calls
        and set(concurrent_outputs) == {expected_digest}
        and set(concurrent_receipts) == {expected_digest}
    )
    tests.append(result_row("concurrent_original_mutation_isolated", concurrency_ok, f"calls={len(concurrent_outputs)}/{expected_calls},errors={concurrent_errors}"))
    tests.append(result_row("concurrent_replay_rng_unchanged", torch.equal(rng_before, rng_after), lineage.digest_payload(rng_before)))

    for _ in range(5):
        target(input_value, params=copy.deepcopy(baseline_params))
        sealed.atomic_apply(operator=target, input_value=input_value, sample_id="atomic/sample0")
    with torch.no_grad():
        direct_ms = timed(lambda: target(input_value, params=copy.deepcopy(baseline_params)), args.iterations)
        atomic_ms = timed(lambda: sealed.atomic_apply(operator=target, input_value=input_value, sample_id="atomic/sample0"), args.iterations)
    performance = [
        {"operation": "direct_replay_with_copy", "median_ms": direct_ms, "iterations": args.iterations},
        {"operation": "sealed_atomic_replay", "median_ms": atomic_ms, "iterations": args.iterations},
    ]
    write_csv(OUT / "autocontract_h7j_runtime_tests.csv", tests)
    write_csv(OUT / "autocontract_h7j_performance.csv", performance)
    passed = sum(row["passed"] is True for row in tests)
    report = "\n".join(
        [
            "# AutoContract H7J sealed atomic Kornia replay",
            "",
            f"Correctness/security tests: {passed}/{len(tests)}.",
            f"Concurrent calls: {len(concurrent_outputs)}/{expected_calls}; errors: {len(concurrent_errors)}.",
            f"Direct replay+copy median: {direct_ms:.3f} ms; sealed atomic median: {atomic_ms:.3f} ms; overhead: {(atomic_ms / direct_ms - 1):.1%}.",
            "",
            "| Test | Pass | Detail |",
            "|---|---|---|",
            *[f"| {row['test']} | {row['passed']} | {row['detail']} |" for row in tests],
            "",
            "The executor protects against mutation of the original record and stale exposed target state. "
            "It is not a sandbox against reflection or monkey patching of the sealed object itself.",
            "",
        ]
    )
    (OUT / "autocontract_h7j_kornia_atomic.md").write_text(report, encoding="utf-8")
    print(report)
    if passed != len(tests):
        raise RuntimeError("H7J runtime evaluation failed")


if __name__ == "__main__":
    main()
