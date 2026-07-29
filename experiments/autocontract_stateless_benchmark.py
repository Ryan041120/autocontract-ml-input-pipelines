"""Test the H4 gate for AutoContract with functional, stateless randomness.

The benchmark compares native torchvision v2 transforms, which draw from the
global torch RNG, with functional wrappers whose decisions are addressed by
``(base_seed, epoch, sample_id, stable_operator_id, draw_index)``.  The latter
uses SplitMix64 only as a small, deterministic counter-based prototype; it is
not intended as a cryptographic generator.

The experiment tests four claims:

1. stateless execution adds at most 5% runtime over native torchvision;
2. deterministic-prefix caching preserves every post-epoch-0 output trace;
3. full-pipeline caching destroys epoch-level augmentation diversity;
4. stable operator identities preserve selected commutative reorderings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import statistics
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2
from torchvision.transforms.v2 import functional as F


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
BASE_SEED = 20260727
MASK64 = (1 << 64) - 1
GOLDEN64 = 0x9E3779B97F4A7C15
EPOCH_MIX = 0xD1B54A32D192ED03
SAMPLE_MIX = 0x94D049BB133111EB

CacheMode = Literal["none", "prefix", "full"]


def splitmix64(value: int) -> int:
    """Map a 64-bit counter to a deterministic, well-scrambled 64-bit word."""

    value = (value + GOLDEN64) & MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    return (value ^ (value >> 31)) & MASK64


def stable_operator_key(operator_id: str) -> int:
    """Return a process-independent key for an explicit stable operator ID."""

    low = zlib.crc32(operator_id.encode("utf-8"))
    high = zlib.crc32(operator_id[::-1].encode("utf-8"))
    return ((high << 32) | low) & MASK64


OP_KEYS = {
    name: stable_operator_key(name)
    for name in (
        "fixed_gaussian_blur",
        "resize",
        "random_hflip",
        "random_vflip",
        "random_crop",
        "color_jitter",
    )
}


def counter_key(epoch: int, sample_id: int, operator_id: str) -> int:
    return (
        BASE_SEED
        ^ ((epoch + 1) * EPOCH_MIX)
        ^ ((sample_id + 1) * SAMPLE_MIX)
        ^ OP_KEYS[operator_id]
    ) & MASK64


def uniform01(key: int, draw_index: int) -> float:
    """Generate one IEEE-754-friendly uniform value in [0, 1)."""

    word = splitmix64((key + draw_index * GOLDEN64) & MASK64)
    return (word >> 11) * (1.0 / (1 << 53))


def uniform(key: int, draw_index: int, low: float, high: float) -> float:
    return low + (high - low) * uniform01(key, draw_index)


def randint(key: int, draw_index: int, high_exclusive: int) -> int:
    if high_exclusive <= 0:
        raise ValueError("high_exclusive must be positive")
    return min(int(uniform01(key, draw_index) * high_exclusive), high_exclusive - 1)


def make_images(count: int, height: int = 127, width: int = 151) -> list[Tensor]:
    images: list[Tensor] = []
    for sample_id in range(count):
        generator = torch.Generator().manual_seed(90_001 + sample_id)
        noise = torch.rand((3, height, width), generator=generator) * 0.08
        y = torch.linspace(0.0, 1.0, height).view(1, height, 1)
        x = torch.linspace(0.0, 1.0, width).view(1, 1, width)
        base = torch.cat((0.7 * x + 0.3 * y, 0.2 * x + 0.8 * y, x * y), dim=0)
        image = torch.clamp(base + noise, 0.0, 1.0)
        patch = 5 + sample_id % 9
        image[:, patch : patch + 11, 2 * patch : 2 * patch + 13] *= 0.1
        images.append(image)
    return images


def native_operators() -> tuple[list[Callable[[Tensor], Tensor]], list[Callable[[Tensor], Tensor]]]:
    prefix = [
        v2.GaussianBlur(9, sigma=(1.4, 1.4)),
        v2.Resize((96, 104), antialias=True),
    ]
    suffix = [
        v2.RandomHorizontalFlip(p=0.5),
        v2.RandomCrop((88, 92)),
        v2.ColorJitter(brightness=0.25, contrast=0.20, saturation=0.15, hue=0.03),
    ]
    return prefix, suffix


def apply_native(value: Tensor, operators: list[Callable[[Tensor], Tensor]]) -> Tensor:
    for operator in operators:
        value = operator(value)
    return value


def stateless_prefix(value: Tensor) -> Tensor:
    value = F.gaussian_blur(value, kernel_size=[9, 9], sigma=[1.4, 1.4])
    return F.resize(value, size=[96, 104], antialias=True)


def stateless_hflip(value: Tensor, epoch: int, sample_id: int) -> Tensor:
    key = counter_key(epoch, sample_id, "random_hflip")
    return F.horizontal_flip(value) if uniform01(key, 0) < 0.5 else value


def stateless_vflip(value: Tensor, epoch: int, sample_id: int) -> Tensor:
    key = counter_key(epoch, sample_id, "random_vflip")
    return F.vertical_flip(value) if uniform01(key, 0) < 0.5 else value


def stateless_crop(
    value: Tensor,
    epoch: int,
    sample_id: int,
    height: int = 88,
    width: int = 92,
) -> Tensor:
    key = counter_key(epoch, sample_id, "random_crop")
    source_height, source_width = value.shape[-2:]
    top = randint(key, 0, source_height - height + 1)
    left = randint(key, 1, source_width - width + 1)
    return F.crop(value, top=top, left=left, height=height, width=width)


def random_order(key: int) -> list[int]:
    """Uniform Fisher-Yates permutation, separate from the four factor draws."""

    order = [0, 1, 2, 3]
    for index in range(3, 0, -1):
        swap = randint(key, 4 + (3 - index), index + 1)
        order[index], order[swap] = order[swap], order[index]
    return order


def stateless_color_jitter(value: Tensor, epoch: int, sample_id: int) -> Tensor:
    key = counter_key(epoch, sample_id, "color_jitter")
    factors = (
        uniform(key, 0, 0.75, 1.25),
        uniform(key, 1, 0.80, 1.20),
        uniform(key, 2, 0.85, 1.15),
        uniform(key, 3, -0.03, 0.03),
    )
    functions = (
        F.adjust_brightness,
        F.adjust_contrast,
        F.adjust_saturation,
        F.adjust_hue,
    )
    for function_id in random_order(key):
        value = functions[function_id](value, factors[function_id])
    return value


def stateless_suffix(value: Tensor, epoch: int, sample_id: int) -> Tensor:
    value = stateless_hflip(value, epoch, sample_id)
    value = stateless_crop(value, epoch, sample_id)
    return stateless_color_jitter(value, epoch, sample_id)


def tensor_digest(value: Tensor) -> str:
    array = value.detach().contiguous().cpu().numpy()
    return hashlib.blake2b(array.tobytes(), digest_size=12).hexdigest()


@dataclass(frozen=True)
class RunResult:
    policy: str
    median_runtime_s: float
    runtime_q1_s: float
    runtime_q3_s: float
    samples_per_s: float
    digests: dict[tuple[int, int], str]
    unique_outputs_per_sample: float


def execute_native(images: list[Tensor], epochs: int) -> tuple[float, dict[tuple[int, int], str]]:
    prefix, suffix = native_operators()
    digests: dict[tuple[int, int], str] = {}
    torch.manual_seed(BASE_SEED)
    started = time.perf_counter()
    with torch.inference_mode():
        for epoch in range(epochs):
            for sample_id, image in enumerate(images):
                value = apply_native(image.clone(), prefix)
                output = apply_native(value, suffix)
                digests[(epoch, sample_id)] = tensor_digest(output)
    return time.perf_counter() - started, digests


def execute_native_suffix(
    prefixed_images: list[Tensor], epochs: int
) -> tuple[float, dict[tuple[int, int], str]]:
    suffix = native_operators()[1]
    digests: dict[tuple[int, int], str] = {}
    torch.manual_seed(BASE_SEED)
    started = time.perf_counter()
    with torch.inference_mode():
        for epoch in range(epochs):
            for sample_id, image in enumerate(prefixed_images):
                output = apply_native(image.clone(), suffix)
                digests[(epoch, sample_id)] = tensor_digest(output)
    return time.perf_counter() - started, digests


def execute_stateless_suffix(
    prefixed_images: list[Tensor], epochs: int
) -> tuple[float, dict[tuple[int, int], str]]:
    digests: dict[tuple[int, int], str] = {}
    started = time.perf_counter()
    with torch.inference_mode():
        for epoch in range(epochs):
            for sample_id, image in enumerate(prefixed_images):
                output = stateless_suffix(image.clone(), epoch, sample_id)
                digests[(epoch, sample_id)] = tensor_digest(output)
    return time.perf_counter() - started, digests


def execute_stateless(
    images: list[Tensor], epochs: int, cache_mode: CacheMode
) -> tuple[float, dict[tuple[int, int], str]]:
    prefix_cache: dict[int, Tensor] = {}
    full_cache: dict[int, Tensor] = {}
    digests: dict[tuple[int, int], str] = {}
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
                        value = stateless_prefix(image.clone())
                        if cache_mode in ("prefix", "full"):
                            prefix_cache[sample_id] = value.clone()
                    output = stateless_suffix(value, epoch, sample_id)
                    if cache_mode == "full":
                        full_cache[sample_id] = output.clone()
                digests[(epoch, sample_id)] = tensor_digest(output)
    return time.perf_counter() - started, digests


def summarize_run(
    policy: str,
    execute: Callable[[], tuple[float, dict[tuple[int, int], str]]],
    sample_count: int,
    epochs: int,
    repeats: int,
) -> RunResult:
    runtimes: list[float] = []
    selected: dict[tuple[int, int], str] = {}
    execute()  # warm-up is excluded from timing samples
    for repeat in range(repeats):
        runtime, digests = execute()
        runtimes.append(runtime)
        if repeat == 0:
            selected = digests
    return build_run_result(policy, runtimes, selected, sample_count, epochs)


def build_run_result(
    policy: str,
    runtimes: list[float],
    selected: dict[tuple[int, int], str],
    sample_count: int,
    epochs: int,
) -> RunResult:
    median_runtime = statistics.median(runtimes)
    unique_counts = [
        len({selected[(epoch, sample_id)] for epoch in range(epochs)})
        for sample_id in range(sample_count)
    ]
    return RunResult(
        policy=policy,
        median_runtime_s=median_runtime,
        runtime_q1_s=float(np.quantile(runtimes, 0.25)),
        runtime_q3_s=float(np.quantile(runtimes, 0.75)),
        samples_per_s=sample_count * epochs / median_runtime,
        digests=selected,
        unique_outputs_per_sample=statistics.mean(unique_counts),
    )


def summarize_paired_runs(
    left_policy: str,
    left_execute: Callable[[], tuple[float, dict[tuple[int, int], str]]],
    right_policy: str,
    right_execute: Callable[[], tuple[float, dict[tuple[int, int], str]]],
    sample_count: int,
    epochs: int,
    repeats: int,
) -> tuple[RunResult, RunResult]:
    """Interleave AB/BA timing order to reduce drift and thermal bias."""

    left_execute()
    right_execute()
    left_runtimes: list[float] = []
    right_runtimes: list[float] = []
    left_selected: dict[tuple[int, int], str] = {}
    right_selected: dict[tuple[int, int], str] = {}
    for repeat in range(repeats):
        ordered = (
            (("left", left_execute), ("right", right_execute))
            if repeat % 2 == 0
            else (("right", right_execute), ("left", left_execute))
        )
        for side, execute in ordered:
            runtime, digests = execute()
            if side == "left":
                left_runtimes.append(runtime)
                if not left_selected:
                    left_selected = digests
            else:
                right_runtimes.append(runtime)
                if not right_selected:
                    right_selected = digests
    return (
        build_run_result(left_policy, left_runtimes, left_selected, sample_count, epochs),
        build_run_result(right_policy, right_runtimes, right_selected, sample_count, epochs),
    )


def trace_match(reference: RunResult, candidate: RunResult, after_epoch0: bool) -> float:
    keys = sorted(reference.digests)
    if after_epoch0:
        keys = [key for key in keys if key[0] > 0]
    return sum(reference.digests[key] == candidate.digests[key] for key in keys) / len(keys)


def apply_named(value: Tensor, name: str, epoch: int, sample_id: int) -> Tensor:
    if name == "fixed_gaussian_blur":
        return F.gaussian_blur(value, kernel_size=[9, 9], sigma=[1.4, 1.4])
    if name == "random_hflip":
        return stateless_hflip(value, epoch, sample_id)
    if name == "random_vflip":
        return stateless_vflip(value, epoch, sample_id)
    if name == "color_jitter":
        return stateless_color_jitter(value, epoch, sample_id)
    raise KeyError(name)


def validate_reorder(images: list[Tensor], trials: int) -> list[dict[str, object]]:
    pairs = (
        ("fixed_gaussian_blur", "random_hflip"),
        ("random_hflip", "random_vflip"),
        ("color_jitter", "random_hflip"),
    )
    rows: list[dict[str, object]] = []
    with torch.inference_mode():
        for left, right in pairs:
            passed = 0
            maximum_error = 0.0
            for trial in range(trials):
                sample_id = trial % len(images)
                epoch = trial // len(images)
                image = images[sample_id]
                forward = apply_named(
                    apply_named(image, left, epoch, sample_id), right, epoch, sample_id
                )
                reverse = apply_named(
                    apply_named(image, right, epoch, sample_id), left, epoch, sample_id
                )
                error = float(torch.max(torch.abs(forward - reverse)))
                maximum_error = max(maximum_error, error)
                passed += int(torch.allclose(forward, reverse, rtol=1e-5, atol=2e-6))
            rows.append(
                {
                    "pair": f"{left}<->{right}",
                    "trials": trials,
                    "allclose_pass_rate": passed / trials,
                    "maximum_absolute_error": maximum_error,
                }
            )
    return rows


def output_features(value: Tensor) -> np.ndarray:
    array = value.detach().cpu().numpy().astype(np.float64)
    features = [*array.mean(axis=(1, 2)), *array.std(axis=(1, 2))]
    height, width = array.shape[-2:]
    features.extend(
        (
            float(array[:, : height // 2].mean()),
            float(array[:, height // 2 :].mean()),
            float(array[:, :, : width // 2].mean()),
            float(array[:, :, width // 2 :].mean()),
            float(np.quantile(array, 0.10)),
            float(np.quantile(array, 0.90)),
        )
    )
    return np.asarray(features)


def pairwise_sq_distances(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.maximum(
        np.sum(left * left, axis=1)[:, None]
        + np.sum(right * right, axis=1)[None, :]
        - 2.0 * left @ right.T,
        0.0,
    )


def mmd_from_kernel(kernel: np.ndarray, left_indices: np.ndarray, right_indices: np.ndarray) -> float:
    left_kernel = kernel[np.ix_(left_indices, left_indices)]
    right_kernel = kernel[np.ix_(right_indices, right_indices)]
    cross_kernel = kernel[np.ix_(left_indices, right_indices)]
    return float(left_kernel.mean() + right_kernel.mean() - 2.0 * cross_kernel.mean())


def validate_distribution(image: Tensor, trials: int, permutations: int) -> dict[str, object]:
    prefix = stateless_prefix(image)
    native_suffix = native_operators()[1]
    native_features: list[np.ndarray] = []
    stateless_features: list[np.ndarray] = []
    torch.manual_seed(BASE_SEED + 11)
    with torch.inference_mode():
        for trial in range(trials):
            native_features.append(output_features(apply_native(prefix.clone(), native_suffix)))
            stateless_features.append(output_features(stateless_suffix(prefix.clone(), trial, 0)))

    left = np.stack(native_features)
    right = np.stack(stateless_features)
    combined = np.concatenate((left, right), axis=0)
    # Standardize feature scales before choosing an RBF bandwidth.
    combined = (combined - combined.mean(axis=0)) / (combined.std(axis=0) + 1e-9)
    distances = pairwise_sq_distances(combined, combined)
    positive = distances[distances > 0]
    median_distance = float(np.median(positive))
    gamma = 1.0 / max(2.0 * median_distance, 1e-12)
    kernel = np.exp(-gamma * distances)
    left_indices = np.arange(trials)
    right_indices = np.arange(trials, 2 * trials)
    observed = mmd_from_kernel(kernel, left_indices, right_indices)
    rng = np.random.default_rng(BASE_SEED + 29)
    exceedances = 0
    for _ in range(permutations):
        shuffled = rng.permutation(2 * trials)
        permuted = mmd_from_kernel(kernel, shuffled[:trials], shuffled[trials:])
        exceedances += int(permuted >= observed)
    p_value = (exceedances + 1) / (permutations + 1)
    return {
        "native_trials": trials,
        "stateless_trials": trials,
        "permutations": permutations,
        "mmd2": observed,
        "permutation_p_value": p_value,
        "difference_detected_at_0_05": p_value < 0.05,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--component-repeats", type=int, default=7)
    parser.add_argument("--reorder-trials", type=int, default=96)
    parser.add_argument("--distribution-trials", type=int, default=192)
    parser.add_argument("--permutations", type=int, default=199)
    args = parser.parse_args()

    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    images = make_images(args.samples)
    native_result, stateless_result = summarize_paired_runs(
            "native:none",
            lambda: execute_native(images, args.epochs),
            "stateless:none",
            lambda: execute_stateless(images, args.epochs, "none"),
            args.samples,
            args.epochs,
            args.repeats,
        )
    policies: list[RunResult] = [native_result, stateless_result]
    for cache_mode in ("prefix", "full"):
        policies.append(
            summarize_run(
                f"stateless:{cache_mode}",
                lambda mode=cache_mode: execute_stateless(images, args.epochs, mode),
                args.samples,
                args.epochs,
                args.repeats,
            )
        )

    with torch.inference_mode():
        prefixed_images = [stateless_prefix(image) for image in images]
    component_results = list(
        summarize_paired_runs(
            "native:random_suffix",
            lambda: execute_native_suffix(prefixed_images, args.epochs),
            "stateless:random_suffix",
            lambda: execute_stateless_suffix(prefixed_images, args.epochs),
            args.samples,
            args.epochs,
            args.component_repeats,
        )
    )

    by_policy = {result.policy: result for result in policies}
    native = by_policy["native:none"]
    stateless = by_policy["stateless:none"]
    rows: list[dict[str, object]] = []
    for result in policies:
        rows.append(
            {
                "policy": result.policy,
                "median_runtime_s": result.median_runtime_s,
                "runtime_q1_s": result.runtime_q1_s,
                "runtime_q3_s": result.runtime_q3_s,
                "samples_per_s": result.samples_per_s,
                "runtime_ratio_vs_native": result.median_runtime_s / native.median_runtime_s,
                "speedup_vs_stateless_no_cache": stateless.median_runtime_s / result.median_runtime_s,
                "trace_match_vs_stateless_all": (
                    trace_match(stateless, result, False)
                    if result.policy.startswith("stateless")
                    else "not_comparable"
                ),
                "trace_match_vs_stateless_after_epoch0": (
                    trace_match(stateless, result, True)
                    if result.policy.startswith("stateless")
                    else "not_comparable"
                ),
                "mean_unique_outputs_per_sample": result.unique_outputs_per_sample,
            }
        )

    reorder_rows = validate_reorder(images, args.reorder_trials)
    distribution = validate_distribution(images[0], args.distribution_trials, args.permutations)
    write_csv(OUT / "autocontract_stateless_benchmark.csv", rows)
    write_csv(OUT / "autocontract_stateless_reorders.csv", reorder_rows)

    native_suffix_result, stateless_suffix_result = component_results
    component_rows = [
        {
            "policy": result.policy,
            "median_runtime_s": result.median_runtime_s,
            "runtime_q1_s": result.runtime_q1_s,
            "runtime_q3_s": result.runtime_q3_s,
            "samples_per_s": result.samples_per_s,
            "runtime_ratio_vs_native_suffix": (
                result.median_runtime_s / native_suffix_result.median_runtime_s
            ),
            "mean_unique_outputs_per_sample": result.unique_outputs_per_sample,
        }
        for result in component_results
    ]
    write_csv(OUT / "autocontract_stateless_components.csv", component_rows)

    overhead = stateless.median_runtime_s / native.median_runtime_s - 1.0
    suffix_overhead = (
        stateless_suffix_result.median_runtime_s
        / native_suffix_result.median_runtime_s
        - 1.0
    )
    prefix = by_policy["stateless:prefix"]
    full = by_policy["stateless:full"]
    h4_pass = max(overhead, suffix_overhead) <= 0.05
    trace_pass = trace_match(stateless, prefix, True) == 1.0
    reorder_pass = all(row["allclose_pass_rate"] == 1.0 for row in reorder_rows)
    diversity_guard_pass = full.unique_outputs_per_sample == 1.0

    lines = [
        "# AutoContract stateless-RNG H4 benchmark",
        "",
        f"Images: {args.samples}; epochs: {args.epochs}; timing repeats: {args.repeats}.",
        "Warm-up is excluded; timings include output hashing and first-epoch cache construction.",
        "",
        "| Policy | Runtime median [Q1, Q3] (s) | Images/s | Runtime vs native | Speedup vs stateless/no-cache | Post-epoch-0 trace match | Mean epoch diversity |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        trace = row["trace_match_vs_stateless_after_epoch0"]
        trace_text = trace if isinstance(trace, str) else f"{trace:.3f}"
        lines.append(
            f"| {row['policy']} | {row['median_runtime_s']:.4f} "
            f"[{row['runtime_q1_s']:.4f}, {row['runtime_q3_s']:.4f}] | "
            f"{row['samples_per_s']:.1f} | {row['runtime_ratio_vs_native']:.3f}x | "
            f"{row['speedup_vs_stateless_no_cache']:.2f}x | {trace_text} | "
            f"{row['mean_unique_outputs_per_sample']:.2f} |"
        )

    lines.extend(
        (
            "",
            "## Isolated random-suffix timing",
            "",
            "This removes Gaussian blur and resize so deterministic work cannot hide RNG-control overhead.",
            "",
            "| Policy | Runtime median [Q1, Q3] (s) | Images/s | Runtime vs native suffix |",
            "|---|---:|---:|---:|",
        )
    )
    for row in component_rows:
        lines.append(
            f"| {row['policy']} | {row['median_runtime_s']:.4f} "
            f"[{row['runtime_q1_s']:.4f}, {row['runtime_q3_s']:.4f}] | "
            f"{row['samples_per_s']:.1f} | {row['runtime_ratio_vs_native_suffix']:.3f}x |"
        )

    lines.extend(("", "## Stable-ID reorder validation", "", "| Pair | Pass rate | Maximum absolute error |", "|---|---:|---:|"))
    for row in reorder_rows:
        lines.append(
            f"| {row['pair']} | {row['allclose_pass_rate']:.3f} | "
            f"{row['maximum_absolute_error']:.3e} |"
        )

    lines.extend(
        (
            "",
            "## Native/stateless output-distribution diagnostic",
            "",
            f"- RBF-MMD²: {distribution['mmd2']:.6g}",
            f"- Permutation p-value ({args.permutations} permutations): {distribution['permutation_p_value']:.4f}",
            f"- Difference detected at α=0.05: {distribution['difference_detected_at_0_05']}",
            "",
            "This finite-sample test can detect a discrepancy but cannot prove equal distributions.",
            "",
            "## Gate verdicts",
            "",
            f"- H4, stateless overhead <= 5% in both tests: **{'PASS' if h4_pass else 'FAIL'}** "
            f"(end-to-end {overhead * 100:+.2f}%; random suffix {suffix_overhead * 100:+.2f}%).",
            f"- Prefix-cache post-epoch-0 trace = 100%: **{'PASS' if trace_pass else 'FAIL'}**.",
            f"- Three stable-ID reorder tests = 100%: **{'PASS' if reorder_pass else 'FAIL'}**.",
            f"- Full-cache diversity guard detects frozen augmentation: **{'PASS' if diversity_guard_pass else 'FAIL'}**.",
            "",
            "Interpretation: a successful result supports replacing RNG-state mutation with "
            "operator-addressed functional draws. It does not yet establish end-to-end "
            "training equivalence, cross-version reproducibility, or cryptographic PRNG quality.",
            "",
        )
    )
    report = "\n".join(lines)
    (OUT / "autocontract_stateless_benchmark.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
