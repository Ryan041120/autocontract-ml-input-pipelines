"""H3 ablation for automatic semantic-effect inference.

The pilot covers 30 operator instances and 10 image pipelines.  It compares a
small trusted registry, static source/bytecode inspection, runtime probing, and
their conservative hybrid.  Adjacent rewrites are admitted only when inferred
effects permit per-sample replay and an operator-keyed differential test finds
no counterexample.

The high-budget rewrite oracle is empirical rather than a proof.  Stateful and
external-state UDFs are manually forced unsafe even if finite testing observes
commuting values.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import os
import random
import re
import statistics
import sys
import textwrap
import time
import zlib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
BASE_SEED = 20260728
Mode = Literal["registry", "static", "runtime", "hybrid"]
Scope = Literal["per_sample", "cross_sample", "unknown"]
InputKind = Literal["float", "uint8"]


class PythonRandomGamma:
    def __call__(self, image: Tensor) -> Tensor:
        gamma = random.uniform(0.75, 1.25)
        return torch.clamp(image, 0.0, 1.0).pow(gamma)


class NumpyRandomOffset:
    def __call__(self, image: Tensor) -> Tensor:
        offset = float(np.random.uniform(-0.08, 0.08))
        return torch.clamp(image + offset, 0.0, 1.0)


class StatefulOffset:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, image: Tensor) -> Tensor:
        self.calls += 1
        return torch.clamp(image + self.calls / 100.0, 0.0, 1.0)


class ExternalEnvironmentGain:
    """Looks constant in this run but depends on mutable process environment."""

    def __call__(self, image: Tensor) -> Tensor:
        gain = float(os.environ.get("AUTOCONTRACT_EXTERNAL_GAIN", "1.0"))
        return torch.clamp(image * gain, 0.0, 1.0)


@dataclass(frozen=True)
class Effect:
    output_random: bool | None
    rng_sources: frozenset[str] | None
    changes_shape: bool | None
    changes_dtype: bool | None
    stateful: bool | None
    scope: Scope | None


@dataclass(frozen=True)
class OperatorSpec:
    name: str
    factory: Callable[[], Callable[[Tensor], Tensor]]
    input_kind: InputKind
    truth: Effect


@dataclass(frozen=True)
class PipelineSpec:
    name: str
    input_kind: InputKind
    operators: tuple[str, ...]


@dataclass(frozen=True)
class PairOccurrence:
    pipeline: str
    position: int
    base_input_kind: InputKind
    input_kind: InputKind
    prefix: tuple[str, ...]
    left: str
    right: str
    oracle_safe: bool
    oracle_evidence: str


@dataclass(frozen=True)
class RuntimeEvidence:
    effect: Effect
    successful_probes: int
    failed_probes: int
    replayable: bool


UNKNOWN_EFFECT = Effect(None, None, None, None, None, None)


def truth(
    output_random: bool,
    rng_sources: tuple[str, ...] = (),
    changes_shape: bool = False,
    changes_dtype: bool = False,
    stateful: bool = False,
    scope: Scope = "per_sample",
) -> Effect:
    return Effect(
        output_random,
        frozenset(rng_sources),
        changes_shape,
        changes_dtype,
        stateful,
        scope,
    )


def operator_specs() -> dict[str, OperatorSpec]:
    torch_rng = ("torch",)
    specs = [
        OperatorSpec("identity", v2.Identity, "float", truth(False)),
        OperatorSpec("resize", lambda: v2.Resize((39, 45), antialias=True), "float", truth(False, changes_shape=True)),
        OperatorSpec("center_crop", lambda: v2.CenterCrop((37, 41)), "float", truth(False, changes_shape=True)),
        OperatorSpec("grayscale3", lambda: v2.Grayscale(num_output_channels=3), "float", truth(False)),
        OperatorSpec("rgb", v2.RGB, "float", truth(False)),
        OperatorSpec("pad", lambda: v2.Pad((2, 3, 4, 1)), "float", truth(False, changes_shape=True)),
        OperatorSpec("normalize", lambda: v2.Normalize((0.45, 0.40, 0.35), (0.25, 0.30, 0.35)), "float", truth(False)),
        OperatorSpec("to_float", lambda: v2.ToDtype(torch.float32, scale=True), "uint8", truth(False, changes_dtype=True)),
        OperatorSpec("fixed_blur", lambda: v2.GaussianBlur(5, sigma=(1.2, 1.2)), "float", truth(False, torch_rng)),
        OperatorSpec("variable_blur", lambda: v2.GaussianBlur(5, sigma=(0.3, 1.8)), "float", truth(True, torch_rng)),
        OperatorSpec("hflip", lambda: v2.RandomHorizontalFlip(p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("vflip", lambda: v2.RandomVerticalFlip(p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_crop", lambda: v2.RandomCrop((35, 39)), "float", truth(True, torch_rng, changes_shape=True)),
        OperatorSpec("random_resized_crop", lambda: v2.RandomResizedCrop((37, 41), scale=(0.55, 0.95)), "float", truth(True, torch_rng, changes_shape=True)),
        OperatorSpec("color_jitter", lambda: v2.ColorJitter(0.25, 0.20, 0.15, 0.03), "float", truth(True, torch_rng)),
        OperatorSpec("random_grayscale", lambda: v2.RandomGrayscale(p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_solarize", lambda: v2.RandomSolarize(0.45, p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_posterize", lambda: v2.RandomPosterize(4, p=0.7), "uint8", truth(True, torch_rng)),
        OperatorSpec("random_sharpness", lambda: v2.RandomAdjustSharpness(1.8, p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_autocontrast", lambda: v2.RandomAutocontrast(p=0.7), "uint8", truth(True, torch_rng)),
        OperatorSpec("random_equalize", lambda: v2.RandomEqualize(p=0.7), "uint8", truth(True, torch_rng)),
        OperatorSpec("random_invert", lambda: v2.RandomInvert(p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_rotation", lambda: v2.RandomRotation(25), "float", truth(True, torch_rng)),
        OperatorSpec("random_affine", lambda: v2.RandomAffine(20, translate=(0.12, 0.10), scale=(0.85, 1.15)), "float", truth(True, torch_rng)),
        OperatorSpec("random_perspective", lambda: v2.RandomPerspective(0.35, p=0.7), "float", truth(True, torch_rng)),
        OperatorSpec("random_erasing", lambda: v2.RandomErasing(p=0.7, scale=(0.08, 0.18), value=0.0), "float", truth(True, torch_rng)),
        OperatorSpec("python_gamma", PythonRandomGamma, "float", truth(True, ("python",))),
        OperatorSpec("numpy_offset", NumpyRandomOffset, "float", truth(True, ("numpy",))),
        OperatorSpec("stateful_offset", StatefulOffset, "float", truth(False, stateful=True, scope="cross_sample")),
        OperatorSpec("external_env", ExternalEnvironmentGain, "float", truth(False, stateful=True, scope="unknown")),
    ]
    return {spec.name: spec for spec in specs}


def pipelines() -> tuple[PipelineSpec, ...]:
    return (
        PipelineSpec("classification_a", "float", ("resize", "fixed_blur", "hflip", "color_jitter", "normalize")),
        PipelineSpec("classification_b", "float", ("pad", "random_crop", "random_resized_crop", "vflip", "random_solarize", "normalize")),
        PipelineSpec("geometry", "float", ("center_crop", "resize", "random_rotation", "random_sharpness", "variable_blur", "normalize")),
        PipelineSpec("equivariant", "float", ("identity", "hflip", "vflip", "random_grayscale", "random_invert", "rgb")),
        PipelineSpec("warps", "float", ("random_affine", "random_perspective", "resize", "color_jitter", "normalize")),
        PipelineSpec("dtype_boundary", "uint8", ("to_float", "normalize", "hflip", "color_jitter")),
        PipelineSpec("uint8_photo", "uint8", ("random_posterize", "random_equalize", "random_autocontrast")),
        PipelineSpec("foreign_rng", "float", ("python_gamma", "numpy_offset", "hflip", "fixed_blur")),
        PipelineSpec("hidden_state", "float", ("stateful_offset", "resize", "hflip", "normalize")),
        PipelineSpec("external_state", "float", ("external_env", "center_crop", "color_jitter", "random_erasing")),
    )


REGISTRY_NAMES = frozenset(
    ("identity", "resize", "normalize", "hflip", "random_crop", "color_jitter")
)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def make_image(kind: InputKind, offset: int = 0, height: int = 43, width: int = 51) -> Tensor:
    y = torch.linspace(0.0, 1.0, height).view(1, height, 1)
    x = torch.linspace(0.0, 1.0, width).view(1, 1, width)
    image = torch.cat((0.72 * x + 0.28 * y, 0.18 * x + 0.82 * y, x * y), dim=0)
    patch = 3 + offset % 7
    image[:, patch : patch + 7, 2 * patch : 2 * patch + 9] *= 0.12
    image = torch.clamp(image + (offset % 5) * 0.007, 0.0, 1.0)
    if kind == "uint8":
        # Keep headroom at both ends so autocontrast is observably non-identity.
        return torch.round(30.0 + image * 180.0).to(torch.uint8)
    return image.to(torch.float32)


def rng_snapshot() -> tuple[object, tuple[object, ...], Tensor]:
    return random.getstate(), np.random.get_state(), torch.random.get_rng_state().clone()


def numpy_state_equal(left: tuple[object, ...], right: tuple[object, ...]) -> bool:
    return (
        left[0] == right[0]
        and np.array_equal(left[1], right[1])
        and left[2:] == right[2:]
    )


def changed_rng_sources(
    before: tuple[object, tuple[object, ...], Tensor],
    after: tuple[object, tuple[object, ...], Tensor],
) -> frozenset[str]:
    changed: set[str] = set()
    if before[0] != after[0]:
        changed.add("python")
    if not numpy_state_equal(before[1], after[1]):
        changed.add("numpy")
    if not torch.equal(before[2], after[2]):
        changed.add("torch")
    return frozenset(changed)


def values_equal(left: Tensor, right: Tensor) -> bool:
    if left.shape != right.shape or left.dtype != right.dtype:
        return False
    if left.dtype.is_floating_point:
        return bool(torch.allclose(left, right, rtol=1e-5, atol=2e-5))
    return bool(torch.equal(left, right))


def infer_runtime(spec: OperatorSpec, seeds: tuple[int, ...]) -> RuntimeEvidence:
    outputs: list[Tensor] = []
    rng_sources: set[str] = set()
    successful = 0
    failed = 0
    shapes: set[tuple[int, ...]] = set()
    dtypes: set[torch.dtype] = set()
    replayable = True
    stateful = False
    source = make_image(spec.input_kind)
    for seed in seeds:
        try:
            operator = spec.factory()
            seed_everything(seed)
            before = rng_snapshot()
            first = operator(source.clone())
            after = rng_snapshot()
            rng_sources.update(changed_rng_sources(before, after))
            seed_everything(seed)
            second = operator(source.clone())
            if not values_equal(first, second):
                stateful = True
                replayable = False
            seed_everything(seed)
            fresh = spec.factory()(source.clone())
            if not values_equal(first, fresh):
                replayable = False
            outputs.append(first)
            shapes.add(tuple(first.shape))
            dtypes.add(first.dtype)
            successful += 1
        except Exception:
            failed += 1
    if not outputs:
        return RuntimeEvidence(UNKNOWN_EFFECT, successful, failed, False)
    output_random = any(not values_equal(outputs[0], value) for value in outputs[1:])
    changes_shape = any(tuple(value.shape) != tuple(source.shape) for value in outputs)
    changes_dtype = any(value.dtype != source.dtype for value in outputs)
    effect = Effect(
        output_random=output_random,
        rng_sources=frozenset(rng_sources),
        changes_shape=changes_shape,
        changes_dtype=changes_dtype,
        stateful=stateful,
        scope="cross_sample" if stateful else "per_sample",
    )
    return RuntimeEvidence(effect, successful, failed, replayable)


def callable_source_fragments(operator: object) -> list[str]:
    fragments: list[str] = []
    cls = type(operator)
    method_names = ("__call__", "forward", "_get_params", "_transform")
    for candidate in cls.mro():
        if candidate is object:
            continue
        for name in method_names:
            if name not in candidate.__dict__:
                continue
            try:
                fragments.append(textwrap.dedent(inspect.getsource(candidate.__dict__[name])))
            except (OSError, TypeError):
                continue
    return fragments


def has_attribute_store(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return True
    return False


def infer_static(spec: OperatorSpec) -> Effect:
    operator = spec.factory()
    fragments = callable_source_fragments(operator)
    if not fragments:
        return UNKNOWN_EFFECT
    source = "\n".join(fragments)
    lowered = source.lower()
    rng_sources: set[str] = set()
    if any(token in source for token in ("torch.rand", "torch.randint", ".uniform_(")):
        rng_sources.add("torch")
    if re.search(r"(?<![\w.])random\.", source):
        rng_sources.add("python")
    if "np.random" in source or "numpy.random" in source:
        rng_sources.add("numpy")
    external = any(token in lowered for token in ("os.environ", "getenv(", "open(", "time.time"))
    mutation = any(has_attribute_store(fragment) for fragment in fragments)
    stateful = external or mutation
    if external:
        scope: Scope | None = None
    elif mutation:
        scope = "cross_sample"
    else:
        scope = "per_sample"
    return Effect(
        output_random=bool(rng_sources),
        rng_sources=frozenset(rng_sources),
        changes_shape=None,
        changes_dtype=None,
        stateful=stateful,
        scope=scope,
    )


def merge_hybrid(
    spec: OperatorSpec, static: Effect, runtime: RuntimeEvidence
) -> Effect:
    if spec.name in REGISTRY_NAMES:
        return spec.truth
    dynamic = runtime.effect
    static_sources = static.rng_sources or frozenset()
    dynamic_sources = dynamic.rng_sources or frozenset()
    rng_sources = static_sources | dynamic_sources
    static_detected_external = static.stateful is True and static.scope is None
    stateful = bool(static.stateful) or bool(dynamic.stateful)
    scope: Scope | None
    if static_detected_external:
        scope = None
    elif stateful:
        scope = "cross_sample"
    else:
        scope = dynamic.scope or static.scope
    return Effect(
        output_random=dynamic.output_random,
        rng_sources=frozenset(rng_sources),
        changes_shape=dynamic.changes_shape,
        changes_dtype=dynamic.changes_dtype,
        stateful=stateful,
        scope=scope,
    )


def infer_all(
    specs: dict[str, OperatorSpec], seeds: tuple[int, ...]
) -> tuple[dict[Mode, dict[str, Effect]], dict[str, RuntimeEvidence]]:
    runtime_evidence = {name: infer_runtime(spec, seeds) for name, spec in specs.items()}
    static_effects = {name: infer_static(spec) for name, spec in specs.items()}
    registry_effects = {
        name: (spec.truth if name in REGISTRY_NAMES else UNKNOWN_EFFECT)
        for name, spec in specs.items()
    }
    runtime_effects = {name: evidence.effect for name, evidence in runtime_evidence.items()}
    hybrid_effects = {
        name: merge_hybrid(spec, static_effects[name], runtime_evidence[name])
        for name, spec in specs.items()
    }
    return (
        {
            "registry": registry_effects,
            "static": static_effects,
            "runtime": runtime_effects,
            "hybrid": hybrid_effects,
        },
        runtime_evidence,
    )


def operator_seed(trial: int, sample_id: int, operator_name: str) -> int:
    key = zlib.crc32(operator_name.encode("utf-8"))
    return (BASE_SEED + trial * 1_000_003 + sample_id * 65_537 + key) % (2**31 - 1)


def apply_chain(
    image: Tensor,
    names: tuple[str, ...],
    specs: dict[str, OperatorSpec],
    trial: int,
    sample_id: int,
) -> Tensor:
    value = image.clone()
    for name in names:
        seed_everything(operator_seed(trial, sample_id, name))
        value = specs[name].factory()(value)
    return value


def differential_pair(
    left: str,
    right: str,
    base_input_kind: InputKind,
    prefix: tuple[str, ...],
    specs: dict[str, OperatorSpec],
    trials: int,
    trial_offset: int = 0,
) -> tuple[bool, str]:
    for local_trial in range(trials):
        trial = trial_offset + local_trial
        image = make_image(
            base_input_kind,
            offset=trial,
            height=43 + 2 * (trial % 3),
            width=51 + 2 * (trial % 4),
        )
        try:
            image = apply_chain(image, prefix, specs, trial, trial % 11)
            forward = apply_chain(image, (left, right), specs, trial, trial % 11)
            reverse = apply_chain(image, (right, left), specs, trial, trial % 11)
        except Exception as error:
            return False, f"trial={trial}:exception:{type(error).__name__}"
        if not values_equal(forward, reverse):
            return False, f"trial={trial}:value_or_signature_mismatch"
    return True, f"no_counterexample_in_{trials}_trials"


def build_pair_oracle(
    specs: dict[str, OperatorSpec], oracle_trials: int
) -> list[PairOccurrence]:
    occurrences: list[PairOccurrence] = []
    for pipeline in pipelines():
        for position, (left, right) in enumerate(zip(pipeline.operators, pipeline.operators[1:])):
            prefix = pipeline.operators[:position]
            probe = apply_chain(
                make_image(pipeline.input_kind),
                prefix,
                specs,
                trial=999,
                sample_id=0,
            )
            pair_input_kind: InputKind = (
                "float" if probe.dtype.is_floating_point else "uint8"
            )
            if left in ("stateful_offset", "external_env") or right in (
                "stateful_offset",
                "external_env",
            ):
                safe = False
                evidence = "manual_unsafe_hidden_or_external_state"
            else:
                safe, evidence = differential_pair(
                    left,
                    right,
                    pipeline.input_kind,
                    prefix,
                    specs,
                    oracle_trials,
                    trial_offset=1000,
                )
            occurrences.append(
                PairOccurrence(
                    pipeline.name,
                    position,
                    pipeline.input_kind,
                    pair_input_kind,
                    prefix,
                    left,
                    right,
                    safe,
                    evidence,
                )
            )
    return occurrences


def admit_pair(
    pair: PairOccurrence,
    effects: dict[str, Effect],
    specs: dict[str, OperatorSpec],
    trials: int,
) -> tuple[bool, str]:
    left = effects[pair.left]
    right = effects[pair.right]
    for name, effect in ((pair.left, left), (pair.right, right)):
        if effect.stateful is not False:
            return False, f"{name}:stateful_or_unknown"
        if effect.scope != "per_sample":
            return False, f"{name}:scope_not_per_sample"
        if effect.rng_sources is None:
            return False, f"{name}:rng_sources_unknown"
        if not effect.rng_sources.issubset({"torch", "python", "numpy"}):
            return False, f"{name}:rng_not_virtualizable"
    safe, evidence = differential_pair(
        pair.left,
        pair.right,
        pair.base_input_kind,
        pair.prefix,
        specs,
        trials,
        trial_offset=0,
    )
    return safe, evidence


def effect_to_json_value(value: object) -> object:
    if isinstance(value, frozenset):
        return "+".join(sorted(value)) if value else "none"
    return value if value is not None else "unknown"


def effect_cell_metrics(
    specs: dict[str, OperatorSpec], predictions: dict[str, Effect]
) -> dict[str, float | int]:
    total = len(specs) * len(fields(Effect))
    resolved = 0
    correct = 0
    for name, spec in specs.items():
        predicted = predictions[name]
        for field in fields(Effect):
            value = getattr(predicted, field.name)
            if value is None:
                continue
            resolved += 1
            correct += int(value == getattr(spec.truth, field.name))
    return {
        "effect_cells_total": total,
        "effect_cells_resolved": resolved,
        "effect_cell_coverage": resolved / total,
        "effect_cell_accuracy_on_resolved": correct / max(resolved, 1),
        "effect_cells_correct": correct,
    }


def pair_metrics(rows: list[dict[str, object]]) -> dict[str, float | int]:
    tp = sum(bool(row["accepted"]) and bool(row["oracle_safe"]) for row in rows)
    fp = sum(bool(row["accepted"]) and not bool(row["oracle_safe"]) for row in rows)
    fn = sum(not bool(row["accepted"]) and bool(row["oracle_safe"]) for row in rows)
    tn = sum(not bool(row["accepted"]) and not bool(row["oracle_safe"]) for row in rows)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "unsafe_precision": tn / max(tn + fp, 1),
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
    parser.add_argument("--effect-seeds", type=int, default=8)
    parser.add_argument("--validator-trials", type=int, default=8)
    parser.add_argument("--oracle-trials", type=int, default=48)
    args = parser.parse_args()

    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    specs = operator_specs()
    if len(specs) != 30 or len(pipelines()) != 10:
        raise AssertionError("H3 protocol requires 30 operators and 10 pipelines")
    seeds = tuple(BASE_SEED + index * 101 for index in range(args.effect_seeds))
    started = time.perf_counter()
    predictions, runtime_evidence = infer_all(specs, seeds)
    pairs = build_pair_oracle(specs, args.oracle_trials)

    effect_rows: list[dict[str, object]] = []
    mode_summaries: list[dict[str, object]] = []
    pair_rows: list[dict[str, object]] = []
    for mode, mode_predictions in predictions.items():
        effect_metrics = effect_cell_metrics(specs, mode_predictions)
        local_pair_rows: list[dict[str, object]] = []
        for pair in pairs:
            accepted, evidence = admit_pair(
                pair, mode_predictions, specs, args.validator_trials
            )
            row = {
                "mode": mode,
                "pipeline": pair.pipeline,
                "position": pair.position,
                "left": pair.left,
                "right": pair.right,
                "base_input_kind": pair.base_input_kind,
                "input_kind": pair.input_kind,
                "prefix": ">".join(pair.prefix),
                "oracle_safe": pair.oracle_safe,
                "accepted": accepted,
                "validator_evidence": evidence,
                "oracle_evidence": pair.oracle_evidence,
            }
            pair_rows.append(row)
            local_pair_rows.append(row)
        summary = {"mode": mode, **effect_metrics, **pair_metrics(local_pair_rows)}
        mode_summaries.append(summary)
        for name, spec in specs.items():
            predicted = mode_predictions[name]
            effect_rows.append(
                {
                    "mode": mode,
                    "operator": name,
                    "registered": name in REGISTRY_NAMES,
                    "input_kind": spec.input_kind,
                    **{
                        f"truth_{field.name}": effect_to_json_value(
                            getattr(spec.truth, field.name)
                        )
                        for field in fields(Effect)
                    },
                    **{
                        f"predicted_{field.name}": effect_to_json_value(
                            getattr(predicted, field.name)
                        )
                        for field in fields(Effect)
                    },
                    "runtime_successes": runtime_evidence[name].successful_probes,
                    "runtime_failures": runtime_evidence[name].failed_probes,
                    "runtime_replayable": runtime_evidence[name].replayable,
                }
            )

    hybrid = predictions["hybrid"]
    unresolved_operators = [
        name
        for name, effect in hybrid.items()
        if any(getattr(effect, field.name) is None for field in fields(Effect))
    ]
    manual_signatures = len(REGISTRY_NAMES) + len(unresolved_operators)
    annotation_reduction = 1.0 - manual_signatures / len(specs)
    hybrid_summary = next(row for row in mode_summaries if row["mode"] == "hybrid")
    h3_pass = (
        int(hybrid_summary["fp"]) == 0
        and float(hybrid_summary["safe_recall"]) >= 0.80
        and annotation_reduction >= 0.70
    )

    for row in mode_summaries:
        row["registered_operator_signatures"] = len(REGISTRY_NAMES)
        row["unresolved_hybrid_operators"] = len(unresolved_operators)
        row["manual_signatures_hybrid"] = manual_signatures
        row["annotation_reduction_hybrid"] = annotation_reduction
        row["h3_gate_pass"] = h3_pass if row["mode"] == "hybrid" else "not_applicable"

    write_csv(OUT / "autocontract_h3_effects.csv", effect_rows)
    write_csv(OUT / "autocontract_h3_pairs.csv", pair_rows)
    write_csv(OUT / "autocontract_h3_ablation.csv", mode_summaries)

    elapsed = time.perf_counter() - started
    safe_count = sum(pair.oracle_safe for pair in pairs)
    unsafe_count = len(pairs) - safe_count
    lines = [
        "# AutoContract H3 effect-inference ablation",
        "",
        f"Operators: {len(specs)}; pipelines: {len(pipelines())}; adjacent rewrite occurrences: {len(pairs)} "
        f"({safe_count} empirically safe, {unsafe_count} unsafe).",
        f"Effect seeds: {args.effect_seeds}; validator trials: {args.validator_trials}; "
        f"oracle trials: {args.oracle_trials}; runtime: {elapsed:.2f}s.",
        "",
        "| Mode | Effect coverage | Effect accuracy (resolved) | TP | FP | FN | TN | Safe recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in mode_summaries:
        lines.append(
            f"| {row['mode']} | {row['effect_cell_coverage']:.1%} | "
            f"{row['effect_cell_accuracy_on_resolved']:.1%} | {row['tp']} | "
            f"{row['fp']} | {row['fn']} | {row['tn']} | {row['safe_recall']:.1%} |"
        )
    lines.extend(
        (
            "",
            "## Annotation accounting",
            "",
            f"- Unique operator signatures: {len(specs)}.",
            f"- Trusted registry signatures: {len(REGISTRY_NAMES)} ({', '.join(sorted(REGISTRY_NAMES))}).",
            f"- Hybrid unresolved operators requiring annotation: {len(unresolved_operators)} "
            f"({', '.join(unresolved_operators) if unresolved_operators else 'none'}).",
            f"- Manual signatures remaining: {manual_signatures}/{len(specs)}.",
            f"- Annotation reduction: {annotation_reduction:.1%}.",
            "",
            "## H3 gate",
            "",
            f"- Known unsafe false accepts = 0: **{'PASS' if int(hybrid_summary['fp']) == 0 else 'FAIL'}**.",
            f"- Safe rewrite recall >=80%: **{'PASS' if float(hybrid_summary['safe_recall']) >= 0.80 else 'FAIL'}** "
            f"({hybrid_summary['safe_recall']:.1%}).",
            f"- Annotation reduction >=70%: **{'PASS' if annotation_reduction >= 0.70 else 'FAIL'}** "
            f"({annotation_reduction:.1%}).",
            f"- Overall H3 pilot: **{'PASS' if h3_pass else 'FAIL'}**.",
            "",
            "The rewrite oracle is a higher-budget differential oracle, not a formal proof. "
            "Hidden/external-state pairs are manually labeled unsafe to prevent finite-test optimism.",
            "",
        )
    )
    report = "\n".join(lines)
    (OUT / "autocontract_h3_ablation.md").write_text(report, encoding="utf-8")
    print(report)
    print(json.dumps({"unresolved": unresolved_operators, "h3_pass": h3_pass}, indent=2))


if __name__ == "__main__":
    main()
