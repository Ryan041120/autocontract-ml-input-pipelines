"""Randomized end-to-end Kornia comparison: H7K vs H7L vs H7M batch replay."""

from __future__ import annotations

import argparse
import copy
import csv
import random
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import torch  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_h7l_bound_executor as h7l_bound  # noqa: E402
import autocontract_h7l_provenance_token as h7l  # noqa: E402
import autocontract_h7m_batch_lease as h7m  # noqa: E402
import autocontract_h7m_buffered_executor as h7m_buffered  # noqa: E402
import autocontract_h7m_kornia_buffered as runtime  # noqa: E402


def elapsed_median(callable_obj, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def make_executors(sources, inputs, params, leaf_policy, proof_digest):
    return tuple(
        runtime.register_executor(
            source, input_value, parameter, leaf_policy, proof_digest, f"h7m/sample{index}",
        )
        for index, (source, input_value, parameter) in enumerate(zip(sources, inputs, params))
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260806)
    rng = random.Random(20260806)

    inputs = tuple(torch.rand(1, 3, 64, 64) for _ in range(args.batch_size))
    sources: list[object] = []
    params: list[object] = []
    expected_outputs: list[torch.Tensor] = []
    for input_value in inputs:
        source = pilot.build_pipeline()
        with torch.no_grad():
            output = source(input_value)
        sources.append(source)
        params.append(copy.deepcopy(source._params))
        expected_outputs.append(output)
    proofs = auto.generate_leaf_proofs(sources[0])
    leaf_policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])

    h7k_executors = make_executors(sources, inputs, params, leaf_policy, proof_digest)
    h7l_executors = make_executors(sources, inputs, params, leaf_policy, proof_digest)
    h7m_executors = make_executors(sources, inputs, params, leaf_policy, proof_digest)
    h7l_policies = runtime.expectations_for(inputs, h7l_executors, run_id="paired/h7l")
    h7m_policies = runtime.expectations_for(inputs, h7m_executors, run_id="paired/h7m")

    h7l_registry = h7l.SqliteReplayRegistry(
        OUT / "autocontract_h7m_paired_h7l.sqlite", reset=True, persistent_connections=True,
    )
    h7l_authority = h7l.ProvenanceAuthority.generate(h7l_registry)
    h7l_verifier = h7l.ProvenanceVerifier(h7l_authority.public_key_bytes(), h7l_registry)
    h7l_wrappers = tuple(
        h7l_bound.ProvenanceBoundExecutor(executor, h7l_verifier, policy)
        for executor, policy in zip(h7l_executors, h7l_policies)
    )
    h7m_registry = h7m.SqliteBatchRegistry(
        OUT / "autocontract_h7m_paired_batch.sqlite", reset=True, persistent_connections=True,
    )
    h7m_authority = h7m.BatchAuthority.generate()
    h7m_verifier = h7m.BatchVerifier(h7m_authority.public_key_bytes())
    h7m_wrapper = h7m_buffered.BufferedBatchExecutor(
        h7m_executors, h7m_verifier, h7m_registry, h7m_policies,
    )

    call_count = 5 + args.rounds * args.iterations
    h7l_token_batches = []
    h7m_ticket_batches = []
    for index in range(call_count):
        h7l_token_batches.append(tuple(h7l_authority.issue(policy) for policy in h7l_policies))
        tickets = h7m_authority.issue_batch(h7m_policies, batch_id=f"paired/h7m/{index}")
        h7m_registry.register(tickets[0].root)
        h7m_ticket_batches.append(tickets)
    h7l_tokens = iter(h7l_token_batches)
    h7m_tickets = iter(h7m_ticket_batches)
    h7l_call_index = 0
    h7m_call_index = 0

    def h7k_call():
        return tuple(
            executor.apply(input_value=input_value, sample_id=f"h7m/sample{index}")[0]
            for index, (executor, input_value) in enumerate(zip(h7k_executors, inputs))
        )

    def h7l_call():
        nonlocal h7l_call_index
        tokens = next(h7l_tokens)
        h7l_call_index += 1
        return tuple(
            wrapper.apply(
                input_value=input_value,
                token=token,
                consumer_id=f"paired/h7l/{h7l_call_index}/{index}",
            )[0]
            for index, (wrapper, input_value, token) in enumerate(zip(h7l_wrappers, inputs, tokens))
        )

    def h7m_call():
        nonlocal h7m_call_index
        tickets = next(h7m_tickets)
        h7m_call_index += 1
        return h7m_wrapper.apply_batch(
            inputs=inputs, tickets=tickets, worker_id=f"paired/h7m/{h7m_call_index}",
        )[0]

    with torch.no_grad():
        for _ in range(5):
            for callable_obj in (h7k_call, h7l_call, h7m_call):
                outputs = callable_obj()
                if not all(torch.equal(left, right) for left, right in zip(outputs, expected_outputs)):
                    raise RuntimeError("paired output mismatch")
        rows: list[dict[str, object]] = []
        operations = {"h7k": h7k_call, "h7l": h7l_call, "h7m": h7m_call}
        for round_index in range(args.rounds):
            order = list(operations)
            rng.shuffle(order)
            timings: dict[str, float] = {}
            for operation in order:
                timings[operation] = elapsed_median(operations[operation], args.iterations)
            rows.append({
                "round": round_index,
                "order": "->".join(order),
                "batch_size": args.batch_size,
                "iterations": args.iterations,
                "h7k_ms": timings["h7k"],
                "h7l_ms": timings["h7l"],
                "h7m_ms": timings["h7m"],
                "h7l_over_h7k": timings["h7l"] / timings["h7k"],
                "h7m_over_h7k": timings["h7m"] / timings["h7k"],
                "h7m_over_h7l": timings["h7m"] / timings["h7l"],
            })

    with (OUT / "autocontract_h7m_kornia_paired_performance.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    h7l_h7k = [float(item["h7l_over_h7k"]) for item in rows]
    h7m_h7k = [float(item["h7m_over_h7k"]) for item in rows]
    h7m_h7l = [float(item["h7m_over_h7l"]) for item in rows]
    input_snapshot_bytes = sum(value.numel() * value.element_size() for value in inputs)
    buffered_output_bytes = sum(value.numel() * value.element_size() for value in expected_outputs)
    report = "\n".join([
        "# H7M randomized end-to-end Kornia batch performance",
        "",
        f"Batch size: {args.batch_size}; rounds: {args.rounds}; calls per within-round median: {args.iterations}.",
        "Issuer work (signing and registry registration) is precomputed and excluded from all three consumer paths.",
        f"Median H7L/H7K: {statistics.median(h7l_h7k):.3f}x.",
        f"Median H7M/H7K: {statistics.median(h7m_h7k):.3f}x.",
        f"Median H7M/H7L: {statistics.median(h7m_h7l):.3f}x; H7M faster rounds: {sum(value < 1.0 for value in h7m_h7l)}/{len(h7m_h7l)}.",
        f"Minimum tensor buffering for this batch: {input_snapshot_bytes} input bytes + {buffered_output_bytes} output bytes (excluding framework/intermediate overhead).",
        "",
        "| Round | Order | H7K ms | H7L ms | H7M ms | H7M/H7L |",
        "|---:|---|---:|---:|---:|---:|",
        *[
            f"| {item['round']} | {item['order']} | {item['h7k_ms']:.3f} | {item['h7l_ms']:.3f} | "
            f"{item['h7m_ms']:.3f} | {item['h7m_over_h7l']:.3f}x |"
            for item in rows
        ],
        "",
        "H7M buffers the full batch until commit, trading additional latency/memory for stale-worker fencing and a single release boundary.",
        "",
    ])
    (OUT / "autocontract_h7m_kornia_paired_performance.md").write_text(report, encoding="utf-8")
    print(report)
    h7l_registry.close()
    h7m_registry.close()


if __name__ == "__main__":
    main()
