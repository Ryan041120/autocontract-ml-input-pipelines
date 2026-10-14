#!/usr/bin/env python3
"""Run receipt-guarded cedar preprocessing into a deterministic ResNet18 step."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as functional
import torchvision
from torchvision.models import resnet18
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5q_cedar_resnet_workload_protocol.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"


class P5QError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise P5QError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def tensor_digest(value: torch.Tensor) -> str:
    tensor = value.detach().cpu().contiguous()
    digest = hashlib.sha256()
    digest.update(str(tensor.dtype).encode("ascii"))
    digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
    digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def named_tensor_digest(items: list[tuple[str, torch.Tensor]]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(items):
        digest.update(name.encode("utf-8")); digest.update(b"\0")
        digest.update(tensor_digest(value).encode("ascii")); digest.update(b"\0")
    return digest.hexdigest()


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def build_feature(
    recipe: list[dict[str, Any]],
    ids: list[str],
    operators: dict[str, Any],
    samples: list[torch.Tensor],
    feature_type: Any,
    mapper_type: Any,
    source_type: Any,
) -> Any:
    class WorkloadFeature(feature_type):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, operator_id in zip(recipe, ids, strict=True):
                pipe = mapper_type(pipe, operators[operator_id], tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
            return pipe

    feature = WorkloadFeature()
    feature.apply(source_type([sample.clone() for sample in samples]))
    return feature


def execute_once(
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
    import autocontract_p5m_relation_boundary_falsification as p5m

    recipe = bundle["backends"]["cedar"]["operators"]
    feature = build_feature(recipe, ids, operators, samples, Feature, MapperPipe, IterSource)
    candidates = calculate_reorderings(feature.logical_pipes, feature.logical_adj_list)
    planning_ms = 0.0
    if optimize:
        options = OptimizerOptions(
            enable_prefetch=False, available_local_cpus=1, enable_offload=False,
            enable_reorder=True, enable_local_parallelism=False, enable_fusion=False,
            enable_caching=False, disable_physical_opt=True, num_samples=100,
        )
        started = time.perf_counter_ns()
        plan = feature.optimize(options, str(cedar_root / "tests" / "data" / "test_profile_stats.yml"))
        planning_ms = (time.perf_counter_ns() - started) / 1_000_000
        path = p5m.ordered_path(plan.graph)
        seed_everything(seed)
        started = time.perf_counter_ns()
        iterator = feature.load_from_plan(CedarContext(), plan)
    else:
        path = p5m.ordered_path(feature.logical_adj_list)
        seed_everything(seed)
        started = time.perf_counter_ns()
        iterator = feature.load(CedarContext(), prefetch=False)
    try:
        outputs = [sample.data for sample in iterator]
        outcome, exception = "output", None
    except Exception as exc:
        outputs = []
        outcome, exception = "exception", {"type": type(exc).__name__, "message": str(exc)}
    execution_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "candidate_count": len(candidates), "path": path, "fix": [item["fix"] for item in recipe],
        "outcome": outcome, "exception": exception, "planning_ms": planning_ms, "execution_ms": execution_ms,
        "samples_per_second": len(outputs) / (execution_ms / 1000.0) if outputs and execution_ms > 0 else None,
        "output_digests": [tensor_digest(value) for value in outputs], "output_shapes": [list(value.shape) for value in outputs],
        "rng": p5m.rng_digest(), "outputs": outputs,
    }


def run_arm(
    cedar_root: Path,
    bundle: dict[str, Any],
    ids: list[str],
    operators: dict[str, Any],
    samples: list[torch.Tensor],
    seed: int,
    repetitions: int,
    *,
    optimize: bool,
) -> dict[str, Any]:
    warmup = execute_once(cedar_root, bundle, ids, operators, samples, seed, optimize=optimize)
    runs = [execute_once(cedar_root, bundle, ids, operators, samples, seed, optimize=optimize) for _ in range(repetitions)]
    execution = sorted(float(run["execution_ms"]) for run in runs)
    planning = sorted(float(run["planning_ms"]) for run in runs)
    first = runs[0]
    stable = all(
        run["outcome"] == first["outcome"] and run["path"] == first["path"]
        and run["output_digests"] == first["output_digests"] and run["rng"] == first["rng"]
        for run in runs
    )
    return {
        "candidate_count": first["candidate_count"], "path": first["path"], "fix": first["fix"],
        "outcome": first["outcome"], "exception": first["exception"],
        "output_digests": first["output_digests"], "output_shapes": first["output_shapes"], "rng": first["rng"],
        "repetitions": repetitions, "repeat_stable": stable,
        "warmup": {"planning_ms": warmup["planning_ms"], "execution_ms": warmup["execution_ms"], "output_stable": warmup["output_digests"] == first["output_digests"] and warmup["rng"] == first["rng"]},
        "planning_ms": {"values": planning, "median": statistics.median(planning), "p95": planning[math.ceil(0.95 * len(planning)) - 1]},
        "execution_ms": {"values": execution, "median": statistics.median(execution), "p95": execution[math.ceil(0.95 * len(execution)) - 1]},
        "samples_per_second_median": len(samples) / (statistics.median(execution) / 1000.0),
        "outputs": first["outputs"],
    }


def public_arm(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "outputs"}


def train_resnet(outputs: list[torch.Tensor], labels: torch.Tensor, seed: int, batch_size: int) -> dict[str, Any]:
    seed_everything(seed)
    model = resnet18(weights=None, num_classes=10)
    model.train()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.0)
    losses: list[str] = []
    logits: list[tuple[str, torch.Tensor]] = []
    started = time.perf_counter_ns()
    for batch_index, start in enumerate(range(0, len(outputs), batch_size)):
        batch = torch.stack(outputs[start:start + batch_size])
        target = labels[start:start + batch_size]
        optimizer.zero_grad(set_to_none=True)
        prediction = model(batch)
        loss = functional.cross_entropy(prediction, target)
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach().item()).hex())
        logits.append((f"batch-{batch_index}", prediction.detach()))
    training_ms = (time.perf_counter_ns() - started) / 1_000_000
    gradients = [(name, parameter.grad) for name, parameter in model.named_parameters() if parameter.grad is not None]
    state = [(name, value) for name, value in model.state_dict().items()]
    return {
        "loss_hex": losses, "logits_sha256": named_tensor_digest(logits),
        "gradient_sha256": named_tensor_digest([(name, value) for name, value in gradients]),
        "model_state_sha256": named_tensor_digest(state), "training_ms": training_ms,
        "samples_per_second": len(outputs) / (training_ms / 1000.0),
    }


def summarize_training(runs: list[dict[str, Any]], sample_count: int) -> dict[str, Any]:
    first = runs[0]
    stable = all(
        run["loss_hex"] == first["loss_hex"] and run["logits_sha256"] == first["logits_sha256"]
        and run["gradient_sha256"] == first["gradient_sha256"] and run["model_state_sha256"] == first["model_state_sha256"]
        for run in runs
    )
    timings = sorted(float(run["training_ms"]) for run in runs)
    return {
        "loss_hex": first["loss_hex"], "logits_sha256": first["logits_sha256"],
        "gradient_sha256": first["gradient_sha256"], "model_state_sha256": first["model_state_sha256"],
        "repeat_stable": stable, "repetitions": len(runs),
        "training_ms": {"values": timings, "median": statistics.median(timings), "p95": timings[math.ceil(0.95 * len(timings)) - 1]},
        "samples_per_second_median": sample_count / (statistics.median(timings) / 1000.0),
    }


def run(cedar_root: Path, output_path: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    frozen = {path: file_sha256(ROOT / path) for path in protocol["frozen_inputs"]}
    append_check(checks, "frozen inputs exact", frozen == protocol["frozen_inputs"], frozen)
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "cedar checkout fixed and clean", head == UPSTREAM_COMMIT and not status, {"head": head, "status": status or "clean"})

    sys.path.insert(0, str(ROOT / "experiments")); sys.path.insert(0, str(cedar_root))
    import autocontract_feasibility as feasibility
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_p5m_relation_boundary_falsification as p5m
    import autocontract_p5o_domain_native_assurance as p5o
    import autocontract_reorder_capability_v0 as capability_v0
    import autocontract_reorder_capability_v2 as capability_v2

    runtime = capability_v2.framework_record()
    expected = {key: value for key, value in protocol["runtime"].items() if key != "cedar_commit"}
    append_check(checks, "framework runtime and source tree pinned", all(runtime[key] == value for key, value in expected.items()), runtime)
    torch.set_num_threads(int(protocol["workload"]["torch_threads"]))
    torch.use_deterministic_algorithms(True)

    domain = p5m.input_domain()
    ids = ["normalize", "random_crop", "identity"]
    operators = {
        "normalize": v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]),
        "random_crop": v2.RandomCrop((23, 25)), "identity": v2.Identity(),
    }
    base = p5m.make_bundle(compiler, capability_v0, capability_v2, ids, operators, domain)
    receipts = [
        capability_v2.make_verified_receipt(base, ids[left], ids[right], operators, domain)
        for left in range(len(ids)) for right in range(left + 1, len(ids))
    ]
    verified = [capability_v2.verify_receipt(receipt, base, operators, domain) for receipt in receipts]
    append_check(checks, "all three V2 receipts locally replay", len(receipts) == 3 and all(item[0] for item in verified), verified)
    fail_closed = capability_v2.compile_reorder_safe_strict(base, [], operators, domain)
    admitted = capability_v2.compile_reorder_safe_strict(base, receipts, operators, domain)
    append_check(checks, "compiler remains constraint-only", not capability_v0.contains_decision_fields(admitted))

    sample_count = int(protocol["workload"]["samples"])
    samples = [feasibility.make_probe_image(31 + index % 5, 37 + (2 * index) % 7, index) for index in range(sample_count)]
    domain_violations = p5o.per_sample_guard(samples, domain)
    append_check(checks, "per-sample runtime premises hold", not domain_violations, domain_violations)
    native = {name: p5o.classify_native_boundary(operator) for name, operator in operators.items()}
    append_check(checks, "torchvision operations are explicitly version-bound native", all(item["class"] == "known_versioned_native" for item in native.values()), native)

    repetitions = int(protocol["workload"]["preprocess_repetitions"])
    execution_seed = int(protocol["workload"]["execution_seed"])
    baseline = run_arm(cedar_root, fail_closed, ids, operators, samples, execution_seed, repetitions, optimize=False)
    optimized = run_arm(cedar_root, admitted, ids, operators, samples, execution_seed, repetitions, optimize=True)
    append_check(checks, "receipts restore six candidates and change selected path", baseline["candidate_count"] == 1 and optimized["candidate_count"] == 6 and baseline["path"] != optimized["path"], {"baseline": public_arm(baseline), "optimized": public_arm(optimized)})
    append_check(checks, "each arm is repeat-stable", baseline["repeat_stable"] and optimized["repeat_stable"])
    preprocess_exact = (
        baseline["outcome"] == optimized["outcome"] == "output"
        and len(baseline["outputs"]) == len(optimized["outputs"]) == sample_count
        and all(torch.equal(left, right) for left, right in zip(baseline["outputs"], optimized["outputs"], strict=True))
    )
    append_check(checks, "preprocessing outputs and definedness exact", preprocess_exact and baseline["output_shapes"] == optimized["output_shapes"])
    append_check(checks, "preprocessing RNG post-state exact", baseline["rng"] == optimized["rng"], {"baseline": baseline["rng"], "optimized": optimized["rng"]})

    labels = torch.arange(sample_count, dtype=torch.long) % 10
    training_seed = int(protocol["workload"]["training_seed"])
    batch_size = int(protocol["workload"]["batch_size"])
    train_resnet(baseline["outputs"], labels, training_seed, batch_size)
    training_repetitions = int(protocol["workload"]["training_repetitions"])
    baseline_training_runs: list[dict[str, Any]] = []
    optimized_training_runs: list[dict[str, Any]] = []
    for repetition in range(training_repetitions):
        order = ("baseline", "optimized") if repetition % 2 == 0 else ("optimized", "baseline")
        for arm in order:
            if arm == "baseline":
                baseline_training_runs.append(train_resnet(baseline["outputs"], labels, training_seed, batch_size))
            else:
                optimized_training_runs.append(train_resnet(optimized["outputs"], labels, training_seed, batch_size))
    baseline_training = summarize_training(baseline_training_runs, sample_count)
    optimized_training = summarize_training(optimized_training_runs, sample_count)
    append_check(checks, "ResNet18 loss sequence exact", baseline_training["loss_hex"] == optimized_training["loss_hex"], {"baseline": baseline_training["loss_hex"], "optimized": optimized_training["loss_hex"]})
    append_check(checks, "ResNet18 logits exact", baseline_training["logits_sha256"] == optimized_training["logits_sha256"])
    append_check(checks, "ResNet18 gradients exact", baseline_training["gradient_sha256"] == optimized_training["gradient_sha256"])
    append_check(checks, "ResNet18 final model state exact", baseline_training["model_state_sha256"] == optimized_training["model_state_sha256"])
    append_check(checks, "paired training repetitions are internally stable", baseline_training["repeat_stable"] and optimized_training["repeat_stable"])

    warm_baseline = baseline["execution_ms"]["median"] + baseline_training["training_ms"]["median"]
    warm_optimized = optimized["execution_ms"]["median"] + optimized_training["training_ms"]["median"]
    cold_baseline = baseline["planning_ms"]["median"] + warm_baseline
    cold_optimized = optimized["planning_ms"]["median"] + warm_optimized
    performance = {
        "fail_closed_baseline": {"planning_ms": baseline["planning_ms"], "preprocessing_ms": baseline["execution_ms"], "preprocessing_samples_per_second": baseline["samples_per_second_median"], "training": baseline_training, "warm_end_to_end_ms": warm_baseline, "cold_end_to_end_ms": cold_baseline},
        "receipt_guarded_cedar": {"planning_ms": optimized["planning_ms"], "preprocessing_ms": optimized["execution_ms"], "preprocessing_samples_per_second": optimized["samples_per_second_median"], "training": optimized_training, "warm_end_to_end_ms": warm_optimized, "cold_end_to_end_ms": cold_optimized},
        "ratios": {"preprocessing_runtime_guarded_over_baseline": optimized["execution_ms"]["median"] / baseline["execution_ms"]["median"], "warm_end_to_end_guarded_over_baseline": warm_optimized / warm_baseline, "cold_end_to_end_guarded_over_baseline": cold_optimized / cold_baseline},
        "interpretation": "descriptive_contaminated_cpu_calibration_no_minimum_speedup_gate",
    }
    finite_positive = all(math.isfinite(float(value)) and float(value) > 0 for value in (
        baseline["execution_ms"]["median"], optimized["execution_ms"]["median"], baseline_training["training_ms"]["median"], optimized_training["training_ms"]["median"], warm_baseline, warm_optimized, cold_baseline, cold_optimized,
    ))
    append_check(checks, "performance endpoints finite and positive", finite_positive, performance["ratios"])
    append_check(checks, "performance direction is descriptive not a pass gate", performance["interpretation"].endswith("no_minimum_speedup_gate"))
    append_check(checks, "workload remains contaminated and non-independent", protocol["status"] == "predeclared_contaminated_workload_calibration" and "not an independent" in protocol["claim_boundary"])

    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5q-cedar-resnet-workload-result.v0", "status": "pass" if passed == len(checks) else "fail",
        "passed": passed, "total": len(checks), "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
        "runtime": {**runtime, "cedar_commit": head, "torch_threads": torch.get_num_threads()},
        "workload": {"samples": sample_count, "batch_size": batch_size, "preprocess_repetitions": repetitions, "training_repetitions": training_repetitions, "execution_seed": execution_seed, "training_seed": training_seed, "model": "resnet18", "synthetic_inputs": True, "contaminated_operators": True, "scientific_evidence": False},
        "receipts": {"count": len(receipts), "verified": verified}, "native_boundary": native,
        "arms": {"fail_closed_baseline": public_arm(baseline), "receipt_guarded_cedar": public_arm(optimized)},
        "semantic_equivalence": {"preprocess_exact": preprocess_exact, "rng_exact": baseline["rng"] == optimized["rng"], "loss_exact": baseline_training["loss_hex"] == optimized_training["loss_hex"], "logits_exact": baseline_training["logits_sha256"] == optimized_training["logits_sha256"], "gradient_exact": baseline_training["gradient_sha256"] == optimized_training["gradient_sha256"], "model_state_exact": baseline_training["model_state_sha256"] == optimized_training["model_state_sha256"]},
        "performance": performance, "checks": checks, "claim_boundary": protocol["claim_boundary"],
    }
    if output_path is not None:
        write_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedar-root", required=True, type=Path); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.cedar_root.resolve(), args.output)
    except (OSError, P5QError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
