"""Randomized paired performance study for H7J atomic versus direct replay."""

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
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_atomic_replay as atomic  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402


PROFILES = ((1, 32), (4, 64), (8, 128))


def median_ms(callable_obj, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    torch.set_num_threads(1)
    rng = random.Random(20260730)
    rows: list[dict[str, object]] = []
    for batch, size in PROFILES:
        torch.manual_seed(1000 + batch + size)
        source = pilot.build_pipeline()
        direct_target = pilot.build_pipeline()
        atomic_target = pilot.build_pipeline()
        input_value = torch.rand(batch, 3, size, size)
        with torch.no_grad():
            source(input_value)
        params = copy.deepcopy(source._params)
        proofs = auto.generate_leaf_proofs(source)
        sealed = atomic.SealedReplayRecord.seal(
            framework="kornia",
            framework_version=kornia.__version__,
            repository_commit=pilot.COMMIT,
            operator=source,
            input_value=input_value,
            params=params,
            sample_id=f"paired/B{batch}S{size}",
            leaf_policy=auto.policy_from_proofs(proofs),
            leaf_proof_set_sha256=lineage.digest_payload([asdict(proof) for proof in proofs]),
        )
        direct = lambda: direct_target(input_value, params=copy.deepcopy(params))
        atomic_call = lambda: sealed.atomic_apply(operator=atomic_target, input_value=input_value, sample_id=f"paired/B{batch}S{size}")
        with torch.no_grad():
            for _ in range(5):
                direct(); atomic_call()
            for round_index in range(args.rounds):
                order = ["direct", "atomic"]
                rng.shuffle(order)
                timings: dict[str, float] = {}
                for operation in order:
                    timings[operation] = median_ms(direct if operation == "direct" else atomic_call, args.iterations)
                rows.append(
                    {
                        "batch": batch,
                        "size": size,
                        "round": round_index,
                        "order": "->".join(order),
                        "iterations": args.iterations,
                        "direct_copy_ms": timings["direct"],
                        "atomic_ms": timings["atomic"],
                        "atomic_over_direct": timings["atomic"] / timings["direct"],
                    }
                )
    write_csv(OUT / "autocontract_h7j_paired_performance.csv", rows)
    summaries: list[dict[str, object]] = []
    for batch, size in PROFILES:
        selected = [row for row in rows if row["batch"] == batch and row["size"] == size]
        ratios = [float(row["atomic_over_direct"]) for row in selected]
        summaries.append(
            {
                "profile": f"B{batch}x3x{size}x{size}",
                "median_atomic_over_direct": statistics.median(ratios),
                "min_ratio": min(ratios),
                "max_ratio": max(ratios),
                "atomic_faster_rounds": sum(value < 1.0 for value in ratios),
                "rounds": len(ratios),
            }
        )
    write_csv(OUT / "autocontract_h7j_paired_performance_summary.csv", summaries)
    all_ratios = [float(row["atomic_over_direct"]) for row in rows]
    report = "\n".join(
        [
            "# H7J randomized paired performance",
            "",
            f"Profiles: {len(PROFILES)}; paired rounds per profile: {args.rounds}; iterations per within-round median: {args.iterations}.",
            f"Overall median atomic/direct ratio: {statistics.median(all_ratios):.3f}x; atomic faster rounds: {sum(value < 1.0 for value in all_ratios)}/{len(all_ratios)}.",
            "",
            "| Profile | Median atomic/direct | Range | Atomic faster rounds |",
            "|---|---:|---:|---:|",
            *[
                f"| {row['profile']} | {row['median_atomic_over_direct']:.3f}x | {row['min_ratio']:.3f}–{row['max_ratio']:.3f}x | "
                f"{row['atomic_faster_rounds']}/{row['rounds']} |"
                for row in summaries
            ],
            "",
            "Randomized order reduces systematic warmup/order bias but does not remove OS scheduling and CPU-frequency noise. "
            "Security/correctness remains the primary H7J endpoint.",
            "",
        ]
    )
    (OUT / "autocontract_h7j_paired_performance.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
