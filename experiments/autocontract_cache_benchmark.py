"""Cache-placement benchmark for AutoContract's RNG semantics.

The deterministic prefix contains a fixed-sigma GaussianBlur.  In torchvision
v2 it produces deterministic values but still advances the global torch RNG.
Caching that prefix therefore changes downstream random augmentation traces if
the pipeline relies on one shared global RNG.  Per-sample, per-operator seeds
make prefix caching trace-preserving, while caching the random suffix still
freezes augmentation diversity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
BASE_SEED = 20260726

RngMode = Literal["global", "operator_keyed", "torch_keyed"]
CacheMode = Literal["none", "prefix", "full"]


@dataclass(frozen=True)
class RunResult:
    policy: str
    rng_mode: RngMode
    cache_mode: CacheMode
    median_runtime_s: float
    samples_per_s: float
    digests: dict[tuple[int, int], str]
    unique_outputs_per_sample: float


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def operator_seed(epoch: int, sample_id: int, operator_name: str) -> int:
    operator_key = zlib.crc32(operator_name.encode("utf-8"))
    mixed = (
        BASE_SEED * 1_000_003
        + epoch * 97_409
        + sample_id * 65_537
        + operator_key
    )
    return mixed % (2**31 - 1)


def make_images(count: int, height: int = 127, width: int = 151) -> list[Tensor]:
    images: list[Tensor] = []
    for sample_id in range(count):
        generator = torch.Generator().manual_seed(90_001 + sample_id)
        noise = torch.rand((3, height, width), generator=generator) * 0.08
        y = torch.linspace(0.0, 1.0, height).view(1, height, 1)
        x = torch.linspace(0.0, 1.0, width).view(1, 1, width)
        base = torch.cat(
            (
                0.7 * x + 0.3 * y,
                0.2 * x + 0.8 * y,
                x * y,
            ),
            dim=0,
        )
        image = torch.clamp(base + noise, 0.0, 1.0)
        patch = 5 + sample_id % 9
        image[:, patch : patch + 11, 2 * patch : 2 * patch + 13] *= 0.1
        images.append(image)
    return images


def build_operators() -> tuple[list[tuple[str, object]], list[tuple[str, object]]]:
    prefix = [
        ("fixed_gaussian_blur", v2.GaussianBlur(9, sigma=(1.4, 1.4))),
        ("resize", v2.Resize((96, 104), antialias=True)),
    ]
    suffix = [
        ("random_hflip", v2.RandomHorizontalFlip(p=0.5)),
        ("random_crop", v2.RandomCrop((88, 92))),
        (
            "color_jitter",
            v2.ColorJitter(
                brightness=0.25, contrast=0.20, saturation=0.15, hue=0.03
            ),
        ),
    ]
    return prefix, suffix


def tensor_digest(value: Tensor) -> str:
    array = value.detach().contiguous().cpu().numpy()
    return hashlib.blake2b(array.tobytes(), digest_size=12).hexdigest()


def apply_operators(
    value: Tensor,
    operators: list[tuple[str, object]],
    rng_mode: RngMode,
    epoch: int,
    sample_id: int,
) -> Tensor:
    for name, operator in operators:
        if rng_mode == "operator_keyed":
            seed_everything(operator_seed(epoch, sample_id, name))
        elif rng_mode == "torch_keyed":
            # torchvision v2 operators in this benchmark consume torch RNG
            # only.  A real effect system should infer the RNG source and
            # avoid resetting unrelated Python/NumPy generators.
            torch.manual_seed(operator_seed(epoch, sample_id, name))
        value = operator(value)
    return value


def execute_once(
    images: list[Tensor],
    epochs: int,
    rng_mode: RngMode,
    cache_mode: CacheMode,
) -> tuple[float, dict[tuple[int, int], str]]:
    prefix, suffix = build_operators()
    prefix_cache: dict[int, Tensor] = {}
    full_cache: dict[int, Tensor] = {}
    digests: dict[tuple[int, int], str] = {}
    seed_everything(BASE_SEED)

    started = time.perf_counter()
    with torch.inference_mode():
        for epoch in range(epochs):
            for sample_id, image in enumerate(images):
                if cache_mode == "full" and sample_id in full_cache:
                    output = full_cache[sample_id]
                else:
                    if cache_mode in ("prefix", "full") and sample_id in prefix_cache:
                        value = prefix_cache[sample_id]
                    else:
                        value = apply_operators(
                            image.clone(),
                            prefix,
                            rng_mode,
                            epoch,
                            sample_id,
                        )
                        if cache_mode in ("prefix", "full"):
                            prefix_cache[sample_id] = value.clone()

                    output = apply_operators(
                        value.clone(), suffix, rng_mode, epoch, sample_id
                    )
                    if cache_mode == "full":
                        full_cache[sample_id] = output.clone()

                digests[(epoch, sample_id)] = tensor_digest(output)
    runtime_s = time.perf_counter() - started
    return runtime_s, digests


def run_policy(
    images: list[Tensor],
    epochs: int,
    repeats: int,
    rng_mode: RngMode,
    cache_mode: CacheMode,
) -> RunResult:
    runtimes: list[float] = []
    selected_digests: dict[tuple[int, int], str] = {}
    for repeat in range(repeats):
        runtime_s, digests = execute_once(images, epochs, rng_mode, cache_mode)
        runtimes.append(runtime_s)
        if repeat == 0:
            selected_digests = digests

    median_runtime = statistics.median(runtimes)
    unique_counts = []
    for sample_id in range(len(images)):
        unique_counts.append(
            len({selected_digests[(epoch, sample_id)] for epoch in range(epochs)})
        )
    policy = f"{rng_mode}:{cache_mode}"
    return RunResult(
        policy=policy,
        rng_mode=rng_mode,
        cache_mode=cache_mode,
        median_runtime_s=median_runtime,
        samples_per_s=len(images) * epochs / median_runtime,
        digests=selected_digests,
        unique_outputs_per_sample=statistics.mean(unique_counts),
    )


def trace_match(reference: RunResult, candidate: RunResult, first_epoch: bool) -> float:
    keys = sorted(reference.digests)
    if not first_epoch:
        keys = [key for key in keys if key[0] > 0]
    matches = sum(reference.digests[key] == candidate.digests[key] for key in keys)
    return matches / max(len(keys), 1)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    images = make_images(args.samples)

    results: list[RunResult] = []
    for rng_mode in ("global", "operator_keyed", "torch_keyed"):
        for cache_mode in ("none", "prefix", "full"):
            results.append(
                run_policy(
                    images,
                    args.epochs,
                    args.repeats,
                    rng_mode,
                    cache_mode,
                )
            )

    by_policy = {result.policy: result for result in results}
    global_baseline = by_policy["global:none"]
    rows: list[dict[str, object]] = []
    for result in results:
        baseline = by_policy[f"{result.rng_mode}:none"]
        rows.append(
            {
                "policy": result.policy,
                "rng_mode": result.rng_mode,
                "cache_mode": result.cache_mode,
                "median_runtime_s": result.median_runtime_s,
                "samples_per_s": result.samples_per_s,
                "speedup_vs_same_rng_no_cache": (
                    baseline.median_runtime_s / result.median_runtime_s
                ),
                "runtime_ratio_vs_global_no_cache": (
                    result.median_runtime_s / global_baseline.median_runtime_s
                ),
                "trace_match_all": trace_match(baseline, result, True),
                "trace_match_after_epoch0": trace_match(baseline, result, False),
                "mean_unique_outputs_per_sample": (
                    result.unique_outputs_per_sample
                ),
            }
        )

    write_csv(OUT / "autocontract_cache_benchmark.csv", rows)

    lines = [
        "# AutoContract cache-placement benchmark",
        "",
        f"Synthetic images: {args.samples}; epochs: {args.epochs}; repeats: {args.repeats}.",
        "Timings include first-epoch cache construction and output hashing.",
        "",
        "| Policy | Runtime (s) | Same-RNG speedup | Vs global baseline | Trace match after epoch 0 | Mean unique outputs |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['policy']} | {row['median_runtime_s']:.4f} | "
            f"{row['speedup_vs_same_rng_no_cache']:.2f}x | "
            f"{row['runtime_ratio_vs_global_no_cache']:.2f}x | "
            f"{row['trace_match_after_epoch0']:.3f} | "
            f"{row['mean_unique_outputs_per_sample']:.2f} |"
        )

    global_prefix = next(row for row in rows if row["policy"] == "global:prefix")
    keyed_prefix = next(
        row for row in rows if row["policy"] == "operator_keyed:prefix"
    )
    torch_keyed_prefix = next(
        row for row in rows if row["policy"] == "torch_keyed:prefix"
    )
    keyed_full = next(
        row for row in rows if row["policy"] == "operator_keyed:full"
    )
    lines.extend(
        (
            "",
            "## Interpretation",
            "",
            f"- Global-RNG prefix caching trace match after epoch 0: "
            f"{global_prefix['trace_match_after_epoch0']:.3f}.",
            f"- Operator-keyed prefix caching trace match after epoch 0: "
            f"{keyed_prefix['trace_match_after_epoch0']:.3f}.",
            f"- Torch-source-keyed prefix caching trace match after epoch 0: "
            f"{torch_keyed_prefix['trace_match_after_epoch0']:.3f}.",
            f"- Operator-keyed full caching leaves only "
            f"{keyed_full['mean_unique_outputs_per_sample']:.2f} unique outputs per sample "
            f"across {args.epochs} epochs.",
            "",
            "Prefix caching is therefore trace-preserving only under an RNG contract that "
            "decouples stochastic operators from skipped deterministic RNG consumers. Full "
            "caching remains semantically unsafe for augmentation diversity.",
            "",
        )
    )
    report = "\n".join(lines)
    (OUT / "autocontract_cache_benchmark.md").write_text(report, encoding="utf-8")
    print(json.dumps(rows, indent=2))
    print(report)


if __name__ == "__main__":
    main()
