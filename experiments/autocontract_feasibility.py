"""Feasibility study for automatic semantic contracts in ML input pipelines.

The experiment intentionally targets a small, falsifiable question before any
cedar integration: can lightweight runtime probes recover basic transformation
effects, and can differential validation reject unsafe adjacent reorderings?

This is not a proof of equivalence.  Passing dynamic tests only means that no
counterexample was found in the tested input/seed domain.  Unknown or stateful
operators remain fixed under the proposed conservative policy.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

Randomness = Literal["deterministic", "stateless_random", "stateful"]
Scope = Literal["per_sample", "cross_sample", "unknown"]
Kind = Literal[
    "identity",
    "pointwise_affine",
    "spatial",
    "color",
    "region",
    "dtype",
    "unknown",
]


@dataclass(frozen=True)
class GroundTruthEffect:
    randomness: Randomness
    consumes_rng: bool
    changes_shape: bool
    changes_dtype: bool
    scope: Scope
    kind: Kind


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    factory: Callable[[], Callable[[Tensor], Tensor]]
    truth: GroundTruthEffect


@dataclass(frozen=True)
class InferredEffect:
    randomness: Randomness
    consumes_rng: bool
    changes_shape: bool
    changes_dtype: bool
    replayable: bool
    successful_probes: int
    failed_probes: int


@dataclass(frozen=True)
class PairSpec:
    left: str
    right: str
    trace_safe: bool
    operator_keyed_trace_safe: bool
    distribution_safe: bool | None
    rationale: str


class StatefulOffset:
    """Adversarial UDF whose result depends on hidden mutable state."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image: Tensor) -> Tensor:
        self.calls += 1
        return torch.clamp(image + self.calls / 100.0, 0.0, 1.0)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def make_probe_image(height: int, width: int, offset: int = 0) -> Tensor:
    """Create an asymmetric image so random flips/crops are observable."""

    y = torch.linspace(0.0, 1.0, height).view(1, height, 1)
    x = torch.linspace(0.0, 1.0, width).view(1, 1, width)
    channels = torch.cat(
        (
            (0.70 * x + 0.30 * y) % 1.0,
            (0.15 * x + 0.85 * y + 0.07) % 1.0,
            (x * y + 0.13) % 1.0,
        ),
        dim=0,
    )
    patch_h = max(2, height // 7)
    patch_w = max(2, width // 9)
    row = (3 * offset + 2) % max(1, height - patch_h)
    col = (5 * offset + 3) % max(1, width - patch_w)
    channels[:, row : row + patch_h, col : col + patch_w] *= 0.17
    return channels.to(torch.float32)


def operators() -> dict[str, OperatorSpec]:
    deterministic = "deterministic"
    random_effect = "stateless_random"
    per_sample = "per_sample"
    return {
        "identity": OperatorSpec(
            "identity",
            v2.Identity,
            GroundTruthEffect(
                deterministic, False, False, False, per_sample, "identity"
            ),
        ),
        "normalize": OperatorSpec(
            "normalize",
            lambda: v2.Normalize([0.45, 0.40, 0.35], [0.25, 0.30, 0.35]),
            GroundTruthEffect(
                deterministic,
                False,
                False,
                False,
                per_sample,
                "pointwise_affine",
            ),
        ),
        "center_crop": OperatorSpec(
            "center_crop",
            lambda: v2.CenterCrop((23, 25)),
            GroundTruthEffect(
                deterministic, False, True, False, per_sample, "spatial"
            ),
        ),
        "resize": OperatorSpec(
            "resize",
            lambda: v2.Resize((29, 31), antialias=True),
            GroundTruthEffect(
                deterministic, False, True, False, per_sample, "spatial"
            ),
        ),
        "grayscale3": OperatorSpec(
            "grayscale3",
            lambda: v2.Grayscale(num_output_channels=3),
            GroundTruthEffect(
                deterministic, False, False, False, per_sample, "color"
            ),
        ),
        "gaussian_blur": OperatorSpec(
            "gaussian_blur",
            lambda: v2.GaussianBlur(kernel_size=3, sigma=(0.8, 0.8)),
            GroundTruthEffect(
                deterministic, True, False, False, per_sample, "spatial"
            ),
        ),
        "random_hflip": OperatorSpec(
            "random_hflip",
            lambda: v2.RandomHorizontalFlip(p=0.5),
            GroundTruthEffect(
                random_effect, True, False, False, per_sample, "spatial"
            ),
        ),
        "random_vflip": OperatorSpec(
            "random_vflip",
            lambda: v2.RandomVerticalFlip(p=0.5),
            GroundTruthEffect(
                random_effect, True, False, False, per_sample, "spatial"
            ),
        ),
        "random_crop": OperatorSpec(
            "random_crop",
            lambda: v2.RandomCrop((23, 25)),
            GroundTruthEffect(
                random_effect, True, True, False, per_sample, "spatial"
            ),
        ),
        "color_jitter": OperatorSpec(
            "color_jitter",
            lambda: v2.ColorJitter(
                brightness=0.35, contrast=0.25, saturation=0.20, hue=0.04
            ),
            GroundTruthEffect(
                random_effect, True, False, False, per_sample, "color"
            ),
        ),
        "random_erasing": OperatorSpec(
            "random_erasing",
            lambda: v2.RandomErasing(
                p=0.8, scale=(0.10, 0.18), ratio=(0.75, 1.33), value=0.0
            ),
            GroundTruthEffect(
                random_effect, True, False, False, per_sample, "region"
            ),
        ),
        "to_uint8": OperatorSpec(
            "to_uint8",
            lambda: v2.ToDtype(torch.uint8, scale=True),
            GroundTruthEffect(
                deterministic, False, False, True, per_sample, "dtype"
            ),
        ),
        "stateful_udf": OperatorSpec(
            "stateful_udf",
            StatefulOffset,
            GroundTruthEffect(
                "stateful", False, False, False, "unknown", "unknown"
            ),
        ),
    }


PAIR_SPECS = (
    PairSpec("identity", "resize", True, True, True, "identity commutes"),
    PairSpec(
        "normalize",
        "center_crop",
        True,
        True,
        True,
        "pointwise affine transform commutes with a pure crop",
    ),
    PairSpec(
        "normalize",
        "random_hflip",
        True,
        True,
        True,
        "normalization is spatially equivariant and consumes no RNG",
    ),
    PairSpec(
        "normalize",
        "random_vflip",
        True,
        True,
        True,
        "normalization is spatially equivariant and consumes no RNG",
    ),
    PairSpec(
        "normalize",
        "random_crop",
        True,
        True,
        True,
        "normalization is pointwise and does not alter crop coordinates",
    ),
    PairSpec(
        "grayscale3",
        "random_hflip",
        True,
        True,
        True,
        "channel projection is spatially equivariant",
    ),
    PairSpec(
        "gaussian_blur",
        "random_hflip",
        False,
        True,
        True,
        "fixed-sigma blur advances global RNG even though its output is deterministic",
    ),
    PairSpec(
        "resize",
        "center_crop",
        False,
        False,
        False,
        "different final geometry and field of view",
    ),
    PairSpec(
        "random_crop",
        "resize",
        False,
        False,
        False,
        "different final geometry and sampled field of view",
    ),
    PairSpec(
        "random_crop",
        "center_crop",
        False,
        False,
        False,
        "crop coordinates and final geometry differ",
    ),
    PairSpec(
        "random_hflip",
        "random_vflip",
        False,
        True,
        True,
        "shared RNG assigns draws to different operators; ideal distribution remains equal",
    ),
    PairSpec(
        "color_jitter",
        "random_hflip",
        False,
        True,
        True,
        "shared RNG trace changes although independent ideal effects commute",
    ),
    PairSpec(
        "color_jitter",
        "normalize",
        False,
        False,
        False,
        "jitter clipping/range semantics do not commute with normalization",
    ),
    PairSpec(
        "random_erasing",
        "normalize",
        False,
        False,
        False,
        "erase value is interpreted before versus after normalization",
    ),
    PairSpec(
        "to_uint8",
        "normalize",
        False,
        False,
        False,
        "normalization requires floating input and has range preconditions",
    ),
    PairSpec(
        "stateful_udf",
        "normalize",
        False,
        False,
        None,
        "hidden state makes retries and reordering unsafe by default",
    ),
)


def outputs_equal(left: Tensor, right: Tensor, atol: float = 2e-5) -> tuple[bool, str]:
    if not isinstance(left, Tensor) or not isinstance(right, Tensor):
        return False, "non_tensor_output"
    if left.shape != right.shape:
        return False, f"shape:{tuple(left.shape)}!={tuple(right.shape)}"
    if left.dtype != right.dtype:
        return False, f"dtype:{left.dtype}!={right.dtype}"
    if left.dtype.is_floating_point:
        delta = float(torch.max(torch.abs(left - right)).item())
        return delta <= atol, f"max_abs_delta={delta:.8g}"
    equal = bool(torch.equal(left, right))
    return equal, "exact" if equal else "integer_value_mismatch"


def infer_effect(spec: OperatorSpec, seeds: list[int]) -> InferredEffect:
    op = spec.factory()
    image = make_probe_image(31, 37, 1)
    shape_probes = (image, make_probe_image(43, 29, 2))
    outputs: list[Tensor] = []
    failed = 0
    replayable = True
    consumes_rng = False
    changes_shape = False
    changes_dtype = False

    # Reuse the same instance intentionally so hidden mutable state is visible.
    for seed in seeds:
        try:
            seed_everything(seed)
            torch_rng_before = torch.get_rng_state().clone()
            python_rng_before = random.getstate()
            numpy_rng_before = np.random.get_state()
            first = op(image.clone())
            torch_rng_after = torch.get_rng_state()
            python_rng_after = random.getstate()
            numpy_rng_after = np.random.get_state()
            numpy_unchanged = (
                numpy_rng_before[0] == numpy_rng_after[0]
                and np.array_equal(numpy_rng_before[1], numpy_rng_after[1])
                and numpy_rng_before[2:] == numpy_rng_after[2:]
            )
            consumes_rng = consumes_rng or not (
                torch.equal(torch_rng_before, torch_rng_after)
                and python_rng_before == python_rng_after
                and numpy_unchanged
            )
            seed_everything(seed)
            second = op(image.clone())
            same, _ = outputs_equal(first, second)
            replayable = replayable and same
            outputs.append(first.detach().cpu())
        except Exception:
            failed += 1

    # Shape and dtype probes are separate from randomness inference so normal
    # input variation is not mistaken for stochastic operator behavior.
    for index, shape_probe in enumerate(shape_probes):
        try:
            seed_everything(70_001 + index)
            transformed = spec.factory()(shape_probe.clone())
            changes_shape = changes_shape or transformed.shape != shape_probe.shape
            changes_dtype = changes_dtype or transformed.dtype != shape_probe.dtype
        except Exception:
            failed += 1

    if not replayable:
        randomness: Randomness = "stateful"
    else:
        varied = False
        comparable = [item for item in outputs if item.shape == outputs[0].shape]
        for item in comparable[1:]:
            same, _ = outputs_equal(comparable[0], item)
            if not same:
                varied = True
                break
        randomness = "stateless_random" if varied else "deterministic"

    return InferredEffect(
        randomness=randomness,
        consumes_rng=consumes_rng,
        changes_shape=changes_shape,
        changes_dtype=changes_dtype,
        replayable=replayable,
        successful_probes=len(outputs),
        failed_probes=failed,
    )


def run_chain(
    names: tuple[str, str],
    image: Tensor,
    seed: int,
    specs: dict[str, OperatorSpec],
    rng_mode: Literal["global", "operator_keyed"] = "global",
) -> Tensor:
    seed_everything(seed)
    value = image.clone()
    for name in names:
        if rng_mode == "operator_keyed":
            operator_key = zlib.crc32(name.encode("utf-8"))
            seed_everything((seed * 1_000_003 + operator_key) % (2**31 - 1))
        value = specs[name].factory()(value)
    return value


def trace_validation(
    pair: PairSpec,
    specs: dict[str, OperatorSpec],
    trials: int,
    rng_mode: Literal["global", "operator_keyed"] = "global",
) -> tuple[bool, int, str]:
    for trial in range(trials):
        image = make_probe_image(31 + trial % 5, 37 + (2 * trial) % 7, trial)
        seed = 10_007 + 97 * trial
        try:
            original = run_chain(
                (pair.left, pair.right), image, seed, specs, rng_mode
            )
            swapped = run_chain(
                (pair.right, pair.left), image, seed, specs, rng_mode
            )
        except Exception as error:
            return False, trial + 1, f"exception:{type(error).__name__}:{error}"
        same, reason = outputs_equal(original, swapped)
        if not same:
            return False, trial + 1, reason
    return True, trials, "no_counterexample_found"


def output_features(image: Tensor) -> np.ndarray:
    value = image.detach().to(torch.float64).cpu()
    if value.ndim == 2:
        value = value.unsqueeze(0)
    nonfinite = (~torch.isfinite(value)).to(torch.float64).mean()
    value = torch.nan_to_num(value, nan=1e3, posinf=1e3, neginf=-1e3)
    means = value.mean(dim=(-2, -1))
    stds = value.std(dim=(-2, -1), unbiased=False)
    if means.numel() == 1:
        means = means.repeat(3)
        stds = stds.repeat(3)
    elif means.numel() > 3:
        means = means[:3]
        stds = stds[:3]
    grad_x = torch.mean(torch.abs(value[..., :, 1:] - value[..., :, :-1]))
    grad_y = torch.mean(torch.abs(value[..., 1:, :] - value[..., :-1, :]))
    q25 = torch.quantile(value.flatten(), 0.25)
    q75 = torch.quantile(value.flatten(), 0.75)
    geometry = torch.tensor(
        [value.shape[-2] / 64.0, value.shape[-1] / 64.0], dtype=torch.float64
    )
    return torch.cat(
        (
            means,
            stds,
            grad_x.view(1),
            grad_y.view(1),
            q25.view(1),
            q75.view(1),
            geometry,
            nonfinite.view(1),
        )
    ).numpy()


def squared_distances(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.maximum(
        np.sum(left * left, axis=1, keepdims=True)
        + np.sum(right * right, axis=1, keepdims=True).T
        - 2.0 * left @ right.T,
        0.0,
    )


def mmd_statistic(left: np.ndarray, right: np.ndarray, gamma: float) -> float:
    k_xx = np.exp(-gamma * squared_distances(left, left))
    k_yy = np.exp(-gamma * squared_distances(right, right))
    k_xy = np.exp(-gamma * squared_distances(left, right))
    return max(float(k_xx.mean() + k_yy.mean() - 2.0 * k_xy.mean()), 0.0)


def distribution_validation(
    pair: PairSpec,
    specs: dict[str, OperatorSpec],
    trials: int,
    permutations: int,
) -> tuple[bool, float, float, str]:
    image = make_probe_image(35, 41, 9)
    left_features: list[np.ndarray] = []
    right_features: list[np.ndarray] = []
    for trial in range(trials):
        # Use disjoint seeds: the contract compares distributions, not paired traces.
        try:
            left = run_chain(
                (pair.left, pair.right), image, 20_011 + 53 * trial, specs
            )
            right = run_chain(
                (pair.right, pair.left), image, 90_001 + 59 * trial, specs
            )
        except Exception as error:
            return False, math.nan, 0.0, f"exception:{type(error).__name__}:{error}"
        left_features.append(output_features(left))
        right_features.append(output_features(right))

    x = np.stack(left_features)
    y = np.stack(right_features)
    combined = np.concatenate((x, y), axis=0)
    distances = squared_distances(combined, combined)
    nonzero = distances[distances > 0]
    gamma = 1.0 if nonzero.size == 0 else 1.0 / max(float(np.median(nonzero)), 1e-12)
    observed = mmd_statistic(x, y, gamma)

    rng = np.random.default_rng(20260726)
    exceed = 1
    for _ in range(permutations):
        order = rng.permutation(len(combined))
        perm_x = combined[order[:trials]]
        perm_y = combined[order[trials:]]
        if mmd_statistic(perm_x, perm_y, gamma) >= observed:
            exceed += 1
    p_value = exceed / (permutations + 1)
    return p_value > 0.05, observed, p_value, "rbf_mmd_permutation"


def confusion(rows: list[dict[str, object]], prediction: str, truth: str) -> dict[str, int]:
    result = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for row in rows:
        predicted = bool(row[prediction])
        expected = bool(row[truth])
        if predicted and expected:
            result["tp"] += 1
        elif predicted and not expected:
            result["fp"] += 1
        elif not predicted and not expected:
            result["tn"] += 1
        else:
            result["fn"] += 1
    return result


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def make_report(
    effect_rows: list[dict[str, object]],
    pair_rows: list[dict[str, object]],
    distribution_rows: list[dict[str, object]],
    trace_confusion: dict[str, int],
    keyed_confusion: dict[str, int],
) -> str:
    effect_cells = sum(
        int(row["randomness_correct"])
        + int(row["shape_correct"])
        + int(row["dtype_correct"])
        for row in effect_rows
    )
    total_effect_cells = 4 * len(effect_rows)
    effect_cells += sum(int(row["rng_consumption_correct"]) for row in effect_rows)
    unsafe_total = sum(not bool(row["trace_safe_truth"]) for row in pair_rows)
    unsafe_accepted = trace_confusion["fp"]
    safe_total = sum(bool(row["trace_safe_truth"]) for row in pair_rows)
    safe_accepted = trace_confusion["tp"]
    precision = trace_confusion["tp"] / max(
        trace_confusion["tp"] + trace_confusion["fp"], 1
    )
    recall = trace_confusion["tp"] / max(
        trace_confusion["tp"] + trace_confusion["fn"], 1
    )
    keyed_precision = keyed_confusion["tp"] / max(
        keyed_confusion["tp"] + keyed_confusion["fp"], 1
    )
    keyed_recall = keyed_confusion["tp"] / max(
        keyed_confusion["tp"] + keyed_confusion["fn"], 1
    )

    lines = [
        "# AutoContract feasibility experiment",
        "",
        "This pilot uses synthetic asymmetric tensors and real torchvision v2 operators. "
        "Dynamic validation is a counterexample search, not a proof.",
        "",
        "## Summary",
        "",
        f"- Effect cells correct: {effect_cells}/{total_effect_cells}.",
        f"- Trace-safe pairs accepted: {safe_accepted}/{safe_total}.",
        f"- Trace-unsafe pairs incorrectly accepted: {unsafe_accepted}/{unsafe_total}.",
        f"- Trace validator precision: {precision:.3f}; recall: {recall:.3f}.",
        f"- Operator-keyed RNG precision: {keyed_precision:.3f}; "
        f"recall: {keyed_recall:.3f}.",
        "",
        "## Trace-level pair results",
        "",
        "| Pair | Global truth | Global validator | Keyed truth | Keyed validator | First evidence |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in pair_rows:
        pair = f"{row['left']} <-> {row['right']}"
        lines.append(
            f"| {pair} | {row['trace_safe_truth']} | "
            f"{row['trace_validator_accept']} | "
            f"{row['operator_keyed_trace_safe_truth']} | "
            f"{row['operator_keyed_validator_accept']} | "
            f"{str(row['evidence']).replace('|', '/')} |"
        )

    lines.extend(
        (
            "",
            "## Distribution-level diagnostics",
            "",
            "| Pair | Truth | MMD decision | p-value |",
            "|---|---:|---:|---:|",
        )
    )
    for row in distribution_rows:
        pair = f"{row['left']} <-> {row['right']}"
        lines.append(
            f"| {pair} | {row['distribution_safe_truth']} | "
            f"{row['distribution_validator_accept']} | {row['p_value']:.4f} |"
        )

    lines.extend(
        (
            "",
            "## Interpretation",
            "",
            "A zero false-accept count in this curated set is only the entry criterion. "
            "The next study must expand the adversarial operator set, separate operator-keyed "
            "from global RNG semantics, and compare against manual cedar/Pecan annotations.",
            "",
        )
    )
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-trials", type=int, default=24)
    parser.add_argument("--effect-seeds", type=int, default=16)
    parser.add_argument("--distribution-trials", type=int, default=96)
    parser.add_argument("--permutations", type=int, default=199)
    args = parser.parse_args()

    OUT.mkdir(exist_ok=True)
    specs = operators()
    seeds = [1_003 + 131 * index for index in range(args.effect_seeds)]

    inferred = {name: infer_effect(spec, seeds) for name, spec in specs.items()}
    effect_rows: list[dict[str, object]] = []
    for name, spec in specs.items():
        result = inferred[name]
        effect_rows.append(
            {
                "operator": name,
                "truth_randomness": spec.truth.randomness,
                "inferred_randomness": result.randomness,
                "randomness_correct": result.randomness == spec.truth.randomness,
                "truth_consumes_rng": spec.truth.consumes_rng,
                "inferred_consumes_rng": result.consumes_rng,
                "rng_consumption_correct": (
                    result.consumes_rng == spec.truth.consumes_rng
                ),
                "truth_changes_shape": spec.truth.changes_shape,
                "inferred_changes_shape": result.changes_shape,
                "shape_correct": result.changes_shape == spec.truth.changes_shape,
                "truth_changes_dtype": spec.truth.changes_dtype,
                "inferred_changes_dtype": result.changes_dtype,
                "dtype_correct": result.changes_dtype == spec.truth.changes_dtype,
                "replayable": result.replayable,
                "successful_probes": result.successful_probes,
                "failed_probes": result.failed_probes,
            }
        )

    pair_rows: list[dict[str, object]] = []
    for pair in PAIR_SPECS:
        accepted, trials_run, evidence = trace_validation(
            pair, specs, args.trace_trials
        )
        keyed_accepted, keyed_trials, keyed_evidence = trace_validation(
            pair, specs, args.trace_trials, "operator_keyed"
        )
        left_effect = inferred[pair.left]
        right_effect = inferred[pair.right]
        # A conservative safety gate: stateful/failed probes are fixed even if
        # the finite differential test happens not to find a counterexample.
        conservative_accept = (
            accepted
            and left_effect.randomness != "stateful"
            and right_effect.randomness != "stateful"
            and left_effect.failed_probes == 0
            and right_effect.failed_probes == 0
        )
        keyed_conservative_accept = (
            keyed_accepted
            and left_effect.randomness != "stateful"
            and right_effect.randomness != "stateful"
            and left_effect.failed_probes == 0
            and right_effect.failed_probes == 0
        )
        pair_rows.append(
            {
                "left": pair.left,
                "right": pair.right,
                "trace_safe_truth": pair.trace_safe,
                "trace_validator_accept": conservative_accept,
                "trials_run": trials_run,
                "evidence": evidence,
                "operator_keyed_trace_safe_truth": (
                    pair.operator_keyed_trace_safe
                ),
                "operator_keyed_validator_accept": keyed_conservative_accept,
                "operator_keyed_trials_run": keyed_trials,
                "operator_keyed_evidence": keyed_evidence,
                "rationale": pair.rationale,
            }
        )

    distribution_rows: list[dict[str, object]] = []
    for pair in PAIR_SPECS:
        if pair.distribution_safe is None:
            continue
        accepted, statistic, p_value, evidence = distribution_validation(
            pair,
            specs,
            args.distribution_trials,
            args.permutations,
        )
        distribution_rows.append(
            {
                "left": pair.left,
                "right": pair.right,
                "distribution_safe_truth": pair.distribution_safe,
                "distribution_validator_accept": accepted,
                "mmd_statistic": statistic,
                "p_value": p_value,
                "evidence": evidence,
            }
        )

    trace_confusion = confusion(
        pair_rows, "trace_validator_accept", "trace_safe_truth"
    )
    keyed_confusion = confusion(
        pair_rows,
        "operator_keyed_validator_accept",
        "operator_keyed_trace_safe_truth",
    )
    write_csv(OUT / "autocontract_effects.csv", effect_rows)
    write_csv(OUT / "autocontract_pairs.csv", pair_rows)
    write_csv(OUT / "autocontract_distributions.csv", distribution_rows)
    report = make_report(
        effect_rows,
        pair_rows,
        distribution_rows,
        trace_confusion,
        keyed_confusion,
    )
    (OUT / "autocontract_feasibility.md").write_text(report, encoding="utf-8")

    print(
        json.dumps(
            {
                "trace_confusion": trace_confusion,
                "operator_keyed_confusion": keyed_confusion,
            },
            indent=2,
        )
    )
    print(report)


if __name__ == "__main__":
    main()
