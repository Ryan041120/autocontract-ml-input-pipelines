"""Multi-seed, multi-shape robustness study for the H7I Kornia pilot."""

from __future__ import annotations

import argparse
import copy
import csv
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(REPO), str(ROOT / "experiments")]

import torch  # noqa: E402
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as cert  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402


PROFILES = ((1, 32), (4, 64), (8, 128))
SEEDS = (101, 211, 307, 401, 503)


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
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=15)
    args = parser.parse_args()
    torch.set_num_threads(1)
    rows: list[dict[str, object]] = []
    for batch, size in PROFILES:
        for seed in SEEDS:
            torch.manual_seed(seed)
            source = pilot.build_pipeline()
            target = pilot.build_pipeline()
            input_value = torch.rand(batch, 3, size, size)
            with torch.no_grad():
                source(input_value)
            params = copy.deepcopy(source._params)
            certificate = cert.create_certificate(
                framework="kornia",
                framework_version=kornia.__version__,
                repository_commit=pilot.COMMIT,
                operator=source,
                input_value=input_value,
                params=params,
                sample_id=f"profile/{batch}x{size}/seed/{seed}",
            )
            common = dict(
                framework="kornia",
                framework_version=kornia.__version__,
                repository_commit=pilot.COMMIT,
                operator=target,
                input_value=input_value,
                params=params,
                sample_id=f"profile/{batch}x{size}/seed/{seed}",
            )
            validation = cert.validate_certificate(certificate, **common)
            composition = cert.compose_child_contracts(target, params, pilot.LEAF_POLICY)
            if validation.decision != "admit" or composition.decision != "admit":
                raise RuntimeError(f"certificate/composition failed for {batch}x{size}, seed={seed}")
            with torch.no_grad():
                for _ in range(3):
                    source(input_value)
                    target(input_value, params=params)
                    cert.validate_certificate(certificate, **common)
                sample_ms = median_ms(lambda: source(input_value), args.iterations)
                replay_ms = median_ms(lambda: target(input_value, params=params), args.iterations)
                validate_ms = median_ms(lambda: cert.validate_certificate(certificate, **common), args.iterations)
            rows.append(
                {
                    "batch": batch,
                    "size": size,
                    "seed": seed,
                    "iterations": args.iterations,
                    "sample_apply_ms": sample_ms,
                    "replay_apply_ms": replay_ms,
                    "speedup": sample_ms / replay_ms,
                    "certificate_validate_ms": validate_ms,
                    "validation_over_replay": validate_ms / replay_ms,
                }
            )
    write_csv(OUT / "autocontract_h7i_scaling.csv", rows)
    summaries: list[dict[str, object]] = []
    for batch, size in PROFILES:
        selected = [row for row in rows if row["batch"] == batch and row["size"] == size]
        speedups = [float(row["speedup"]) for row in selected]
        validation_shares = [float(row["validation_over_replay"]) for row in selected]
        summaries.append(
            {
                "profile": f"B{batch}x3x{size}x{size}",
                "median_speedup": statistics.median(speedups),
                "min_speedup": min(speedups),
                "max_speedup": max(speedups),
                "speedup_trials": sum(value > 1.0 for value in speedups),
                "trials": len(speedups),
                "median_validation_share": statistics.median(validation_shares),
            }
        )
    write_csv(OUT / "autocontract_h7i_scaling_summary.csv", summaries)
    all_speedups = [float(row["speedup"]) for row in rows]
    report = "\n".join(
        [
            "# H7I Kornia scaling robustness",
            "",
            f"Profiles: {len(PROFILES)}; seeds per profile: {len(SEEDS)}; trials: {len(rows)}; iterations per timing median: {args.iterations}.",
            f"Replay faster trials: {sum(value > 1.0 for value in all_speedups)}/{len(all_speedups)}; overall median speedup: {statistics.median(all_speedups):.3f}x.",
            "",
            "| Profile | Median speedup | Range | Faster trials | Median validation/replay |",
            "|---|---:|---:|---:|---:|",
            *[
                f"| {row['profile']} | {row['median_speedup']:.3f}x | {row['min_speedup']:.3f}–{row['max_speedup']:.3f}x | "
                f"{row['speedup_trials']}/{row['trials']} | {row['median_validation_share']:.1%} |"
                for row in summaries
            ],
            "",
            "Performance is a secondary pilot outcome. Correctness and rejection of mismatched lineage remain the primary H7I outcomes.",
            "",
        ]
    )
    (OUT / "autocontract_h7i_scaling.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
