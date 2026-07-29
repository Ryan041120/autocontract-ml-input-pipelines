"""Randomized paired performance study for H7K registered replay."""

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
import autocontract_h7k_registered_executor as registered  # noqa: E402


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
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    torch.set_num_threads(1)
    rng = random.Random(20260731)
    rows: list[dict[str, object]] = []
    registration_rows: list[dict[str, object]] = []

    for batch, size in PROFILES:
        torch.manual_seed(2000 + batch + size)
        source = pilot.build_pipeline()
        direct_target = pilot.build_pipeline()
        atomic_target = pilot.build_pipeline()
        input_value = torch.rand(batch, 3, size, size)
        sample_id = f"paired-h7k/B{batch}S{size}"
        with torch.no_grad():
            source(input_value)
        params = copy.deepcopy(source._params)
        proofs = auto.generate_leaf_proofs(source)
        policy = auto.policy_from_proofs(proofs)
        proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
        sealed = atomic.SealedReplayRecord.seal(
            framework="kornia",
            framework_version=kornia.__version__,
            repository_commit=pilot.COMMIT,
            operator=source,
            input_value=input_value,
            params=params,
            sample_id=sample_id,
            leaf_policy=policy,
            leaf_proof_set_sha256=proof_digest,
        )

        def register(level: registered.ReceiptLevel) -> registered.RegisteredReplayExecutor:
            return registered.RegisteredReplayExecutor.register(
                framework="kornia",
                framework_version=kornia.__version__,
                repository_commit=pilot.COMMIT,
                source_operator=source,
                target_factory=pilot.build_pipeline,
                input_value=input_value,
                params=params,
                sample_id=sample_id,
                leaf_policy=policy,
                leaf_proof_set_sha256=proof_digest,
                pool_size=1,
                receipt_level=level,
            )

        minimal = register("minimal")
        audit = register("audit")
        registration_rows.extend([
            {
                "profile": f"B{batch}x3x{size}x{size}",
                "receipt_level": "minimal",
                "registration_ms": minimal.registration_receipt.registration_ms,
            },
            {
                "profile": f"B{batch}x3x{size}x{size}",
                "receipt_level": "audit",
                "registration_ms": audit.registration_receipt.registration_ms,
            },
        ])

        direct = lambda: direct_target(input_value, params=copy.deepcopy(params))
        h7j = lambda: sealed.atomic_apply(
            operator=atomic_target, input_value=input_value, sample_id=sample_id,
        )
        h7k_minimal = lambda: minimal.apply(input_value=input_value, sample_id=sample_id)
        h7k_audit = lambda: audit.apply(input_value=input_value, sample_id=sample_id)
        operations = {
            "direct": direct,
            "h7j": h7j,
            "h7k_minimal": h7k_minimal,
            "h7k_audit": h7k_audit,
        }
        with torch.no_grad():
            for _ in range(5):
                for callable_obj in operations.values():
                    callable_obj()
            for round_index in range(args.rounds):
                order = list(operations)
                rng.shuffle(order)
                timings: dict[str, float] = {}
                for operation in order:
                    timings[operation] = median_ms(operations[operation], args.iterations)
                rows.append({
                    "batch": batch,
                    "size": size,
                    "round": round_index,
                    "order": "->".join(order),
                    "iterations": args.iterations,
                    "direct_copy_ms": timings["direct"],
                    "h7j_atomic_ms": timings["h7j"],
                    "h7k_minimal_ms": timings["h7k_minimal"],
                    "h7k_audit_ms": timings["h7k_audit"],
                    "minimal_over_h7j": timings["h7k_minimal"] / timings["h7j"],
                    "audit_over_h7j": timings["h7k_audit"] / timings["h7j"],
                    "minimal_over_direct": timings["h7k_minimal"] / timings["direct"],
                    "audit_over_minimal": timings["h7k_audit"] / timings["h7k_minimal"],
                })

    write_csv(OUT / "autocontract_h7k_paired_performance.csv", rows)
    write_csv(OUT / "autocontract_h7k_registration_cost.csv", registration_rows)
    summaries: list[dict[str, object]] = []
    for batch, size in PROFILES:
        selected = [item for item in rows if item["batch"] == batch and item["size"] == size]
        minimal_h7j = [float(item["minimal_over_h7j"]) for item in selected]
        audit_h7j = [float(item["audit_over_h7j"]) for item in selected]
        minimal_direct = [float(item["minimal_over_direct"]) for item in selected]
        audit_minimal = [float(item["audit_over_minimal"]) for item in selected]
        h7j_ms = statistics.median(float(item["h7j_atomic_ms"]) for item in selected)
        minimal_ms = statistics.median(float(item["h7k_minimal_ms"]) for item in selected)
        registration_ms = next(
            float(item["registration_ms"])
            for item in registration_rows
            if item["profile"] == f"B{batch}x3x{size}x{size}" and item["receipt_level"] == "minimal"
        )
        saving_ms = h7j_ms - minimal_ms
        break_even_calls: float | str = registration_ms / saving_ms if saving_ms > 0 else "none"
        summaries.append({
            "profile": f"B{batch}x3x{size}x{size}",
            "median_minimal_over_h7j": statistics.median(minimal_h7j),
            "median_audit_over_h7j": statistics.median(audit_h7j),
            "median_minimal_over_direct": statistics.median(minimal_direct),
            "median_audit_over_minimal": statistics.median(audit_minimal),
            "minimal_faster_than_h7j_rounds": sum(value < 1.0 for value in minimal_h7j),
            "rounds": len(selected),
            "registration_ms": registration_ms,
            "break_even_calls_vs_h7j": break_even_calls,
        })
    write_csv(OUT / "autocontract_h7k_paired_performance_summary.csv", summaries)

    all_minimal_h7j = [float(item["minimal_over_h7j"]) for item in rows]
    all_audit_h7j = [float(item["audit_over_h7j"]) for item in rows]
    all_minimal_direct = [float(item["minimal_over_direct"]) for item in rows]
    all_audit_minimal = [float(item["audit_over_minimal"]) for item in rows]
    report = "\n".join([
        "# H7K randomized paired performance",
        "",
        f"Profiles: {len(PROFILES)}; paired rounds per profile: {args.rounds}; iterations per within-round median: {args.iterations}.",
        f"Overall median H7K-minimal/H7J ratio: {statistics.median(all_minimal_h7j):.3f}x; "
        f"H7K-minimal faster rounds: {sum(value < 1.0 for value in all_minimal_h7j)}/{len(all_minimal_h7j)}.",
        f"Overall median H7K-audit/H7J ratio: {statistics.median(all_audit_h7j):.3f}x.",
        f"Overall median H7K-minimal/direct+copy ratio: {statistics.median(all_minimal_direct):.3f}x.",
        f"Output auditing multiplier over minimal receipt: {statistics.median(all_audit_minimal):.3f}x.",
        "",
        "| Profile | Minimal/H7J | Audit/H7J | Minimal/direct | Minimal faster rounds | Registration | Break-even vs H7J |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[
            f"| {item['profile']} | {item['median_minimal_over_h7j']:.3f}x | "
            f"{item['median_audit_over_h7j']:.3f}x | {item['median_minimal_over_direct']:.3f}x | "
            f"{item['minimal_faster_than_h7j_rounds']}/{item['rounds']} | {item['registration_ms']:.3f} ms | "
            + (
                f"{item['break_even_calls_vs_h7j']:.1f} calls |"
                if isinstance(item["break_even_calls_vs_h7j"], float)
                else "none |"
            )
            for item in summaries
        ],
        "",
        "Break-even conservatively charges the full H7K registration cost but does not charge H7J sealing cost. "
        "Randomized within-round order reduces warmup/order bias; it does not eliminate OS scheduling or CPU-frequency noise.",
        "",
    ])
    (OUT / "autocontract_h7k_paired_performance.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
