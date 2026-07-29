"""Randomized CPU target-pool scaling study for H7K registered replay."""

from __future__ import annotations

import argparse
import copy
import csv
import random
import statistics
import sys
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
import autocontract_h7k_kornia_registered as runtime  # noqa: E402
import autocontract_h7k_registered_executor as registered  # noqa: E402


POOL_SIZES = (1, 2, 4)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--calls-per-worker", type=int, default=25)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(20260801)
    rng = random.Random(20260801)

    source = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    with torch.no_grad():
        expected = source(input_value)
    params = copy.deepcopy(source._params)
    proofs = auto.generate_leaf_proofs(source)
    policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    expected_digest = lineage.digest_payload(expected)
    executors: dict[int, registered.RegisteredReplayExecutor] = {}
    for pool_size in POOL_SIZES:
        executors[pool_size] = runtime.make_executor(
            source,
            input_value,
            params,
            policy,
            proof_digest,
            pool_size=pool_size,
            receipt_level="minimal",
        )

    expected_calls = args.workers * args.calls_per_worker
    rows: list[dict[str, object]] = []
    with torch.no_grad():
        for executor in executors.values():
            runtime.concurrent_run(executor, input_value, workers=args.workers, calls_per_worker=2)
        for round_index in range(args.rounds):
            order = list(POOL_SIZES)
            rng.shuffle(order)
            for pool_size in order:
                rng_before = torch.get_rng_state().clone()
                elapsed_ms, outputs, slots, errors = runtime.concurrent_run(
                    executors[pool_size],
                    input_value,
                    workers=args.workers,
                    calls_per_worker=args.calls_per_worker,
                )
                rng_after = torch.get_rng_state().clone()
                correct = (
                    len(outputs) == expected_calls
                    and not errors
                    and set(outputs) == {expected_digest}
                    and torch.equal(rng_before, rng_after)
                )
                rows.append({
                    "round": round_index,
                    "order": "->".join(map(str, order)),
                    "pool_size": pool_size,
                    "workers": args.workers,
                    "calls": expected_calls,
                    "elapsed_ms": elapsed_ms,
                    "calls_per_second": expected_calls / (elapsed_ms / 1000.0),
                    "observed_slots": ",".join(map(str, sorted(set(slots)))),
                    "correct": correct,
                    "error_count": len(errors),
                })
    write_csv(OUT / "autocontract_h7k_pool_scaling.csv", rows)

    summaries: list[dict[str, object]] = []
    baseline = statistics.median(
        float(item["calls_per_second"]) for item in rows if item["pool_size"] == 1
    )
    for pool_size in POOL_SIZES:
        selected = [item for item in rows if item["pool_size"] == pool_size]
        throughput = [float(item["calls_per_second"]) for item in selected]
        summaries.append({
            "pool_size": pool_size,
            "median_calls_per_second": statistics.median(throughput),
            "min_calls_per_second": min(throughput),
            "max_calls_per_second": max(throughput),
            "speedup_over_pool1": statistics.median(throughput) / baseline,
            "correct_rounds": sum(item["correct"] is True for item in selected),
            "rounds": len(selected),
        })
    write_csv(OUT / "autocontract_h7k_pool_scaling_summary.csv", summaries)
    report = "\n".join([
        "# H7K target-pool scaling on CPU",
        "",
        f"Workload: B4x3x64x64, {args.workers} client threads, {args.calls_per_worker} calls/thread, {args.rounds} randomized rounds.",
        "",
        "| Pool size | Median calls/s | Range | Speedup vs pool=1 | Correct rounds |",
        "|---:|---:|---:|---:|---:|",
        *[
            f"| {item['pool_size']} | {item['median_calls_per_second']:.1f} | "
            f"{item['min_calls_per_second']:.1f}-{item['max_calls_per_second']:.1f} | "
            f"{item['speedup_over_pool1']:.3f}x | {item['correct_rounds']}/{item['rounds']} |"
            for item in summaries
        ],
        "",
        "The pool is required for owned-target isolation under concurrent callers. Throughput scaling is an empirical property, not a safety guarantee.",
        "",
    ])
    (OUT / "autocontract_h7k_pool_scaling.md").write_text(report, encoding="utf-8")
    print(report)
    if not all(item["correct_rounds"] == item["rounds"] for item in summaries):
        raise RuntimeError("H7K pool scaling correctness failed")


if __name__ == "__main__":
    main()
