#!/usr/bin/env python3
"""Falsify P5L relation-lemma boundaries and execute a random cedar chain."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import pickle
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5m_relation_boundary_falsification_protocol.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
SEMANTIC_FUNCTIONS = {
    "validate_input_domain",
    "operator_source_index",
    "extract_operator_ir",
    "_ensure_total_on_domain",
    "_select_lemma",
    "build_proof_artifact",
    "make_verified_receipt",
    "verify_receipt",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def input_domain() -> dict[str, Any]:
    return {
        "type": "torch.Tensor",
        "layout": "CHW",
        "channels": 3,
        "dtype": "torch.float32",
        "value_min": 0.0,
        "value_max": 1.0,
        "height_min": 31,
        "height_max": 35,
        "width_min": 37,
        "width_max": 43,
        "device": "cpu",
        "allow_nonfinite": False,
    }


def make_bundle(compiler: Any, v0cap: Any, v2cap: Any, ids: list[str], operators: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    items = []
    for operator_id in ids:
        operator = operators[operator_id]
        items.append(
            compiler.make_operator(
                operator_id,
                source_index_sha256=v2cap.operator_source_sha256(operator),
                contract_sha256=v0cap.canonical_sha256(
                    {"type": f"{type(operator).__module__}.{type(operator).__qualname__}", "repr": repr(operator)}
                ),
            )
        )
    pipeline = compiler.make_pipeline(items, operation="adjacent_reorder")
    pipeline["input_schema_sha256"] = v0cap.canonical_sha256(domain)
    return compiler.compile_constraints(pipeline)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def rng_digest() -> dict[str, str]:
    return {
        "python": hashlib.sha256(pickle.dumps(random.getstate(), protocol=4)).hexdigest(),
        "numpy": hashlib.sha256(pickle.dumps(np.random.get_state(), protocol=4)).hexdigest(),
        "torch": hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
    }


def tensor_digest(value: torch.Tensor) -> str:
    payload = {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "bytes_sha256": hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest(),
    }
    return canonical_sha256(payload)


def ordered_path(graph: dict[int, set[int]], source: int = 3) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        if len(graph[current]) != 1:
            raise ValueError("fixture_graph_not_linear")
        current = next(iter(graph[current]))
        path.append(current)
    return path


def mutate_domain(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    result.update(updates)
    return result


def try_receipt(
    compiler: Any,
    v0cap: Any,
    v2cap: Any,
    left_factory: Callable[[], Any],
    right_factory: Callable[[], Any],
    domain: dict[str, Any],
) -> dict[str, Any]:
    try:
        operators = {"a": left_factory(), "b": right_factory()}
        base = make_bundle(compiler, v0cap, v2cap, ["a", "b"], operators, domain)
        receipt = v2cap.make_verified_receipt(base, "a", "b", operators, domain)
        compiled = v2cap.compile_reorder_safe_strict(base, [receipt], operators, domain)
        return {
            "admitted": bool(compiled["proof_verification"]["verified_pairs"]),
            "reason": compiled["proof_verification"]["receipt_audit"],
        }
    except Exception as exc:  # The experiment records the exact fail-closed layer.
        return {"admitted": False, "reason": f"{type(exc).__name__}:{exc}"}


def make_image(feasibility: Any, height: int, width: int, offset: int, memory: str) -> torch.Tensor:
    if memory == "contiguous":
        image = feasibility.make_probe_image(height, width, offset).contiguous()
    elif memory == "noncontiguous_chw":
        image = feasibility.make_probe_image(width, height, offset).transpose(1, 2)
        if image.is_contiguous():
            raise AssertionError("noncontiguous_fixture_became_contiguous")
    else:
        raise ValueError(memory)
    return image


def execute_pair(
    left_factory: Callable[[], Any],
    right_factory: Callable[[], Any],
    order: tuple[int, int],
    image: torch.Tensor,
    seed: int,
) -> dict[str, Any]:
    seed_everything(seed)
    operators = [left_factory(), right_factory()]
    try:
        value = image.clone(memory_format=torch.preserve_format)
        for index in order:
            value = operators[index](value)
        outcome: dict[str, Any] = {"kind": "output", "value": value, "digest": tensor_digest(value)}
    except Exception as exc:
        outcome = {"kind": "exception", "exception": {"type": type(exc).__name__, "message": str(exc)}}
    outcome["rng"] = rng_digest()
    return outcome


def compare_pair_outcomes(original: dict[str, Any], swapped: dict[str, Any]) -> tuple[bool, str, float | None]:
    if original["kind"] != swapped["kind"]:
        return False, "definedness_mismatch", None
    if original["kind"] == "exception":
        return original["exception"] == swapped["exception"] and original["rng"] == swapped["rng"], "exception_outcome", None
    left, right = original["value"], swapped["value"]
    same_shape_dtype = left.shape == right.shape and left.dtype == right.dtype
    exact = same_shape_dtype and torch.equal(left, right)
    rng_equal = original["rng"] == swapped["rng"]
    delta = float(torch.max(torch.abs(left - right)).item()) if same_shape_dtype and left.numel() else math.inf
    return exact and rng_equal, "exact_output_and_rng" if exact and rng_equal else "output_or_rng_mismatch", delta


def sloc_metrics(path: Path) -> dict[str, int]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    module_sloc = sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in lines)
    tree = ast.parse(source)
    selected: set[int] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in SEMANTIC_FUNCTIONS:
            selected.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    semantic_sloc = sum(bool(lines[index - 1].strip()) and not lines[index - 1].lstrip().startswith("#") for index in selected)
    return {"module_sloc": int(module_sloc), "semantic_adapter_sloc": int(semantic_sloc)}


def execute_cedar_random(
    cedar_root: Path,
    bundle: dict[str, Any],
    ids: list[str],
    operators: dict[str, Any],
    samples: list[torch.Tensor],
    seed: int,
    *,
    optimize: bool,
) -> dict[str, Any]:
    from cedar.compose import Feature, OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    recipe = bundle["backends"]["cedar"]["operators"]

    class RandomTransformFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, operator_id in zip(recipe, ids, strict=True):
                pipe = MapperPipe(pipe, operators[operator_id], tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
            return pipe

    feature = RandomTransformFeature()
    feature.apply(IterSource([sample.clone() for sample in samples]))
    candidates = calculate_reorderings(feature.logical_pipes, feature.logical_adj_list)
    if optimize:
        options = OptimizerOptions(
            enable_prefetch=False,
            available_local_cpus=1,
            enable_offload=False,
            enable_reorder=True,
            enable_local_parallelism=False,
            enable_fusion=False,
            enable_caching=False,
            disable_physical_opt=True,
            num_samples=100,
        )
        plan = feature.optimize(options, str(cedar_root / "tests/data/test_profile_stats.yml"))
        path = ordered_path(plan.graph)
        seed_everything(seed)
        iterator = feature.load_from_plan(CedarContext(), plan)
    else:
        path = ordered_path(feature.logical_adj_list)
        seed_everything(seed)
        iterator = feature.load(CedarContext(), prefetch=False)
    try:
        outputs = [sample.data for sample in iterator]
        outcome = "output"
        exception = None
    except Exception as exc:
        outputs = []
        outcome = "exception"
        exception = {"type": type(exc).__name__, "message": str(exc)}
    return {
        "candidate_count": len(candidates),
        "path": path,
        "fix": [item["fix"] for item in recipe],
        "outcome": outcome,
        "exception": exception,
        "output_digests": [tensor_digest(value) for value in outputs],
        "output_shapes": [list(value.shape) for value in outputs],
        "rng": rng_digest(),
        "outputs": outputs,
    }


def public_cedar(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "outputs"}


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    frozen = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in protocol["frozen_inputs"]}
    append_check(checks, "p5l_artifacts_are_frozen", frozen == protocol["frozen_inputs"], frozen)
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "cedar_checkout_is_fixed_and_clean", head == UPSTREAM_COMMIT and not status, {"head": head, "status": status or "clean"})

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_feasibility as feasibility
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_reorder_capability_v0 as v0cap
    import autocontract_reorder_capability_v2 as v2cap

    runtime = v2cap.framework_record()
    expected_runtime = {key: value for key, value in protocol["runtime"].items() if key != "cedar_commit"}
    append_check(checks, "framework_runtime_and_tree_match", runtime == expected_runtime, runtime)
    domain = input_domain()

    domain_cases: list[tuple[str, Callable[[], Any], Callable[[], Any], dict[str, Any]]] = [
        ("layout_hwc", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"layout": "HWC"})),
        ("channels_one", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"channels": 1})),
        ("channels_four", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"channels": 4})),
        ("dtype_float64", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"dtype": "torch.float64"})),
        ("device_cuda", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"device": "cuda"})),
        ("allow_nonfinite", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"allow_nonfinite": True})),
        ("nonfinite_value_min", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"value_min": float("-inf")})),
        ("nonfinite_value_max", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"value_max": float("inf")})),
        ("inverted_value_range", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"value_min": 1.0, "value_max": 0.0})),
        ("zero_height_min", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"height_min": 0})),
        ("noninteger_width_max", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"width_max": 43.5})),
        ("center_crop_height_totality", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"height_min": 22})),
        ("center_crop_width_totality", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25)), mutate_domain(domain, {"width_min": 24})),
        ("random_crop_height_totality", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.RandomCrop((23, 25)), mutate_domain(domain, {"height_min": 22})),
        ("random_crop_width_totality", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), lambda: v2.RandomCrop((23, 25)), mutate_domain(domain, {"width_min": 24})),
    ]
    domain_results = []
    for name, left_factory, right_factory, attack_domain in domain_cases:
        attempt = try_receipt(compiler, v0cap, v2cap, left_factory, right_factory, attack_domain)
        domain_results.append({"name": name, **attempt})
    append_check(
        checks,
        "all_domain_and_totality_mutations_fail_closed",
        len(domain_results) == protocol["predeclared_matrix"]["domain_and_totality_mutations"] and not any(item["admitted"] for item in domain_results),
        domain_results,
    )

    class IdentitySubclass(v2.Identity):
        pass

    config_cases: list[tuple[str, Callable[[], Any], Callable[[], Any]]] = [
        ("normalize_inplace", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35], inplace=True), lambda: v2.CenterCrop((23, 25))),
        ("normalize_two_channels", lambda: v2.Normalize([0.45, 0.4], [0.25, 0.3]), lambda: v2.CenterCrop((23, 25))),
        ("normalize_zero_std", lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.0, 0.35]), lambda: v2.CenterCrop((23, 25))),
        ("normalize_nonfinite_mean", lambda: v2.Normalize([0.45, float("nan"), 0.35], [0.25, 0.3, 0.35]), lambda: v2.CenterCrop((23, 25))),
        ("grayscale_one_channel", lambda: v2.Grayscale(num_output_channels=1), lambda: v2.CenterCrop((23, 25))),
        ("random_crop_padding", lambda: v2.RandomCrop((23, 25), padding=1), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("random_crop_pad_if_needed", lambda: v2.RandomCrop((23, 25), pad_if_needed=True), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("random_crop_too_large", lambda: v2.RandomCrop((36, 44)), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("center_crop_too_large", lambda: v2.CenterCrop((36, 44)), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("hflip_probability_negative", lambda: v2.RandomHorizontalFlip(p=-0.1), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("vflip_probability_above_one", lambda: v2.RandomVerticalFlip(p=1.1), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
        ("identity_subclass", IdentitySubclass, lambda: v2.Resize((29, 31), antialias=True)),
        ("unsupported_gaussian_blur", lambda: v2.GaussianBlur(kernel_size=3, sigma=(0.8, 0.8)), lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])),
    ]
    config_results = []
    for name, left_factory, right_factory in config_cases:
        attempt = try_receipt(compiler, v0cap, v2cap, left_factory, right_factory, domain)
        config_results.append({"name": name, **attempt})
    append_check(
        checks,
        "all_unsupported_operator_configs_fail_closed",
        len(config_results) == protocol["predeclared_matrix"]["operator_configuration_mutations"] and not any(item["admitted"] for item in config_results),
        config_results,
    )

    normalize = lambda: v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35])
    admitted_cases: list[tuple[str, str, Callable[[], Any], Callable[[], Any]]] = [
        ("identity_resize", "identity_composition_v0", v2.Identity, lambda: v2.Resize((29, 31), antialias=True)),
        ("identity_normalize", "identity_composition_v0", v2.Identity, normalize),
        ("identity_random_crop", "identity_composition_v0", v2.Identity, lambda: v2.RandomCrop((23, 25))),
        ("normalize_center_base", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.CenterCrop((23, 25))),
        ("normalize_center_edge", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.CenterCrop((31, 37))),
        ("normalize_hflip_p0", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomHorizontalFlip(p=0.0)),
        ("normalize_hflip_p05", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomHorizontalFlip(p=0.5)),
        ("normalize_hflip_p1", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomHorizontalFlip(p=1.0)),
        ("normalize_vflip_p0", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomVerticalFlip(p=0.0)),
        ("normalize_vflip_p05", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomVerticalFlip(p=0.5)),
        ("normalize_vflip_p1", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomVerticalFlip(p=1.0)),
        ("normalize_random_crop_base", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomCrop((23, 25))),
        ("normalize_random_crop_edge", "pointwise_channel_map_spatial_index_v0", normalize, lambda: v2.RandomCrop((31, 37))),
        ("grayscale_hflip_p05", "pointwise_channel_map_spatial_index_v0", lambda: v2.Grayscale(num_output_channels=3), lambda: v2.RandomHorizontalFlip(p=0.5)),
        ("grayscale_hflip_p1", "pointwise_channel_map_spatial_index_v0", lambda: v2.Grayscale(num_output_channels=3), lambda: v2.RandomHorizontalFlip(p=1.0)),
        ("grayscale_center_edge", "pointwise_channel_map_spatial_index_v0", lambda: v2.Grayscale(num_output_channels=3), lambda: v2.CenterCrop((31, 37))),
        ("grayscale_vflip_p05", "pointwise_channel_map_spatial_index_v0", lambda: v2.Grayscale(num_output_channels=3), lambda: v2.RandomVerticalFlip(p=0.5)),
        ("grayscale_vflip_p1", "pointwise_channel_map_spatial_index_v0", lambda: v2.Grayscale(num_output_channels=3), lambda: v2.RandomVerticalFlip(p=1.0)),
    ]
    shapes = [(31, 37), (31, 43), (35, 37), (35, 43)]
    seeds = [0, 1, 2, 17, 10007, 2147483646]
    memories = ["contiguous", "noncontiguous_chw"]
    metamorphic_rows = []
    total_trials = 0
    total_failures = 0
    for case_index, (name, lemma, left_factory, right_factory) in enumerate(admitted_cases):
        first_failure = None
        case_trials = 0
        case_max_delta = 0.0
        for height, width in shapes:
            for seed in seeds:
                for memory in memories:
                    image = make_image(feasibility, height, width, case_index + seed, memory)
                    original = execute_pair(left_factory, right_factory, (0, 1), image, seed)
                    swapped = execute_pair(left_factory, right_factory, (1, 0), image, seed)
                    equal, reason, delta = compare_pair_outcomes(original, swapped)
                    case_trials += 1
                    total_trials += 1
                    if delta is not None and math.isfinite(delta):
                        case_max_delta = max(case_max_delta, delta)
                    if not equal:
                        total_failures += 1
                        if first_failure is None:
                            first_failure = {
                                "shape": [height, width],
                                "seed": seed,
                                "memory": memory,
                                "reason": reason,
                                "original_kind": original["kind"],
                                "swapped_kind": swapped["kind"],
                                "original_rng": original["rng"],
                                "swapped_rng": swapped["rng"],
                            }
        metamorphic_rows.append(
            {"name": name, "lemma": lemma, "trials": case_trials, "failures": int(first_failure is not None), "max_abs_delta": case_max_delta, "first_failure": first_failure}
        )
    append_check(
        checks,
        "all_admitted_boundary_trials_preserve_exact_output_and_rng",
        len(admitted_cases) == protocol["predeclared_matrix"]["admitted_pair_configurations"]
        and total_trials == protocol["predeclared_matrix"]["metamorphic_trials"]
        and total_failures == 0,
        {"trials": total_trials, "failures": total_failures, "cases": metamorphic_rows},
    )
    exercised = {item["lemma"] for item in metamorphic_rows}
    append_check(
        checks,
        "matrix_exercises_both_lemmas_shapes_and_memory_layouts",
        exercised == {"identity_composition_v0", "pointwise_channel_map_spatial_index_v0"}
        and len(shapes) == 4
        and memories == protocol["predeclared_matrix"]["memory_layouts"],
        {"lemmas": sorted(exercised), "shapes": shapes, "memory_layouts": memories},
    )

    cost_ops = {"normalize": normalize(), "center_crop": v2.CenterCrop((23, 25))}
    cost_base = make_bundle(compiler, v0cap, v2cap, ["normalize", "center_crop"], cost_ops, domain)
    generation_ms = []
    receipts = []
    for _ in range(3):
        started = time.perf_counter_ns()
        receipt = v2cap.make_verified_receipt(cost_base, "normalize", "center_crop", cost_ops, domain)
        generation_ms.append((time.perf_counter_ns() - started) / 1_000_000)
        receipts.append(receipt)
    verification_ms = []
    verification_results = []
    for receipt in receipts:
        started = time.perf_counter_ns()
        verification_results.append(v2cap.verify_receipt(receipt, cost_base, cost_ops, domain))
        verification_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    receipt_bytes = len(json.dumps(receipts[-1], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    burden = {
        "generation_ms": generation_ms,
        "generation_median_ms": statistics.median(generation_ms),
        "verification_ms": verification_ms,
        "verification_median_ms": statistics.median(verification_ms),
        "receipt_bytes": receipt_bytes,
        **sloc_metrics(ROOT / "experiments" / "autocontract_reorder_capability_v2.py"),
        "interpretation": "descriptive_calibration_only_no_low_overhead_claim",
    }
    append_check(checks, "proof_and_adapter_burden_is_recorded", all(item[0] for item in verification_results) and all(value > 0 for value in generation_ms + verification_ms) and receipt_bytes > 0, burden)

    chain_ids = ["normalize", "random_crop", "identity"]
    chain_ops = {"normalize": normalize(), "random_crop": v2.RandomCrop((23, 25)), "identity": v2.Identity()}
    chain_base = make_bundle(compiler, v0cap, v2cap, chain_ids, chain_ops, domain)
    chain_receipts = [
        v2cap.make_verified_receipt(chain_base, chain_ids[left], chain_ids[right], chain_ops, domain)
        for left in range(3)
        for right in range(left + 1, 3)
    ]
    fail_closed = v2cap.compile_reorder_safe_strict(chain_base, [], chain_ops, domain)
    admitted = v2cap.compile_reorder_safe_strict(chain_base, chain_receipts, chain_ops, domain)
    samples = [feasibility.make_probe_image(31 + index % 5, 37 + (2 * index) % 7, index) for index in range(8)]
    execution_seed = 918273
    baseline = execute_cedar_random(cedar_root, fail_closed, chain_ids, chain_ops, samples, execution_seed, optimize=False)
    optimized = execute_cedar_random(cedar_root, admitted, chain_ids, chain_ops, samples, execution_seed, optimize=True)
    append_check(
        checks,
        "v2_receipts_restore_six_random_cedar_candidates",
        baseline["candidate_count"] == 1 and optimized["candidate_count"] == 6 and baseline["path"] != optimized["path"],
        {"baseline": public_cedar(baseline), "optimized": public_cedar(optimized)},
    )
    cedar_exact = (
        baseline["outcome"] == optimized["outcome"] == "output"
        and len(baseline["outputs"]) == len(optimized["outputs"]) == len(samples)
        and all(torch.equal(left, right) for left, right in zip(baseline["outputs"], optimized["outputs"], strict=True))
    )
    cedar_max_delta = (
        max(float(torch.max(torch.abs(left - right)).item()) for left, right in zip(baseline["outputs"], optimized["outputs"], strict=True))
        if cedar_exact
        else None
    )
    append_check(
        checks,
        "random_cedar_reorder_preserves_output_exception_and_rng_post_state",
        cedar_exact and baseline["rng"] == optimized["rng"],
        {"max_abs_delta": cedar_max_delta, "baseline": public_cedar(baseline), "optimized": public_cedar(optimized)},
    )
    append_check(checks, "compiler_output_contains_no_optimizer_decisions", not v0cap.contains_decision_fields(admitted))

    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5m-relation-boundary-falsification-result.v0",
        "status": "pass" if passed == len(checks) else "fail",
        "passed": passed,
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "p5l_module_sha256": file_sha256(ROOT / "experiments" / "autocontract_reorder_capability_v2.py"),
        "upstream_commit_sha": head,
        "domain_mutations": domain_results,
        "operator_config_mutations": config_results,
        "metamorphic": {"trials": total_trials, "failures": total_failures, "cases": metamorphic_rows},
        "burden": burden,
        "cedar": {"seed": execution_seed, "baseline": public_cedar(baseline), "optimized": public_cedar(optimized), "max_abs_delta": cedar_max_delta},
        "checks": checks,
        "claim_boundary": protocol["claim_boundary"],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedar-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.cedar_root.resolve(), args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
