#!/usr/bin/env python3
"""P5R: frozen high-resolution 2D Crop-before-Normalize workload calibration.

The script deliberately treats timing as descriptive.  Its pass condition is
semantic: a single mismatch in output, RNG, definedness, or model trace fails
the cell even if the reordered arm is faster.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as functional
from torchvision.models import mobilenet_v3_small
from torchvision.transforms import v2
from torchvision.transforms import functional as tvf


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5r_highres_2d_workload_protocol.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
BOOTSTRAP_SEED = 20260807
PROFILE_YML = ROOT / "benchmark" / "final_v1" / "p5r_highres_2d_profile.yml"


class P5RError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise P5RError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)


def rng_digest() -> dict[str, str]:
    import pickle
    return {
        "python": hashlib.sha256(pickle.dumps(random.getstate(), protocol=4)).hexdigest(),
        "numpy": hashlib.sha256(pickle.dumps(np.random.get_state(), protocol=4)).hexdigest(),
        "torch": hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
    }


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


def storage_record(values: list[torch.Tensor]) -> dict[str, Any]:
    logical = sum(value.numel() * value.element_size() for value in values)
    retained = sum(value.untyped_storage().nbytes() for value in values)
    views = sum(value._base is not None for value in values)
    return {
        "logical_output_bytes": logical,
        "retained_output_backing_bytes": retained,
        "view_output_count": views,
        "retained_over_logical_ratio": retained / logical if logical else None,
        "note": "Counts each output tensor backing storage independently; source-owner retention is reported separately and no crop-view saving is claimed.",
    }


def make_samples(cedar_root: Path, height: int, width: int, count: int) -> tuple[list[torch.Tensor], list[dict[str, Any]]]:
    """Decode cedar's real JPEG fixtures and resize before timing begins."""
    from torchvision.io import read_image
    images = sorted((cedar_root / "tests" / "data" / "images").glob("*.jpg"))[:count]
    require(len(images) == count, "insufficient_cedar_jpeg_fixtures")
    samples, provenance = [], []
    for path in images:
        decoded = read_image(str(path))
        resized = tvf.resize(decoded, [height, width], antialias=True).to(torch.float32).div_(255.0)
        samples.append(resized)
        provenance.append({"path": str(path), "sha256": file_sha256(path), "decoded_shape": list(decoded.shape), "resident_shape": list(resized.shape)})
    return samples, provenance


def build_feature(recipe: list[dict[str, Any]], ids: list[str], operators: dict[str, Any], samples: list[torch.Tensor]) -> Any:
    from cedar.compose import Feature
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    class WorkloadFeature(Feature):
        def _compose(self, source_pipes: list[Any]) -> Any:
            pipe = source_pipes[0]
            for item, operator_id in zip(recipe, ids, strict=True):
                pipe = MapperPipe(pipe, operators[operator_id], tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
            return pipe

    feature = WorkloadFeature()
    feature.apply(IterSource([sample.clone() for sample in samples]))
    return feature


def path_tags(feature: Any, graph: dict[int, set[int]], path: list[int]) -> list[str]:
    """Return tags in source-to-sink execution order where cedar exposes them."""
    tags: list[str] = []
    for node in path:
        pipe = feature.logical_pipes.get(node)
        if pipe is None:
            continue
        tag = getattr(pipe, "tag", None)
        if tag is not None:
            tags.append(str(tag))
    return tags


def ordered_path(graph: dict[int, set[int]]) -> list[int]:
    """cedar numbers the source after the mapper nodes; do not assume P5Q's 3."""
    source = max(graph)
    path = [source]
    current = source
    while graph[current]:
        require(len(graph[current]) == 1, "cedar_graph_not_linear")
        current = next(iter(graph[current]))
        path.append(current)
    return path


def execute_preprocess(
    cedar_root: Path, bundle: dict[str, Any], ids: list[str], operators: dict[str, Any], samples: list[torch.Tensor], seed: int,
) -> dict[str, Any]:
    from cedar.compose import OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    import autocontract_p5m_relation_boundary_falsification as p5m

    recipe = bundle["backends"]["cedar"]["operators"]
    feature = build_feature(recipe, ids, operators, samples)
    candidates = calculate_reorderings(feature.logical_pipes, feature.logical_adj_list)
    require(PROFILE_YML.is_file(), "workload_specific_profile_missing")
    options = OptimizerOptions(
        enable_prefetch=False, available_local_cpus=1, enable_offload=False, enable_reorder=True,
        enable_local_parallelism=False, enable_fusion=False, enable_caching=False,
        disable_physical_opt=True, num_samples=100,
    )
    started = time.perf_counter_ns()
    plan = feature.optimize(options, str(PROFILE_YML))
    planning_ms = (time.perf_counter_ns() - started) / 1_000_000
    graph = plan.graph
    path = ordered_path(graph)
    tags = path_tags(feature, graph, path)
    seed_everything(seed)
    started = time.perf_counter_ns()
    iterator = feature.load_from_plan(CedarContext(), plan)
    try:
        outputs = [sample.data for sample in iterator]
        outcome, exception = "output", None
    except Exception as exc:  # definedness is an endpoint, so preserve it.
        outputs, outcome = [], "exception"
        exception = {"type": type(exc).__name__, "message": str(exc)}
    execution_ms = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "candidate_count": len(candidates), "path": path, "path_tags": tags,
        "execution_order_tags": [tag for tag in tags if not tag.startswith("IterSourcePipe_")],
        "fix": [item["fix"] for item in recipe], "outcome": outcome, "exception": exception,
        "planning_ms": planning_ms, "execution_ms": execution_ms,
        "output_digests": [tensor_digest(value) for value in outputs],
        "output_shapes": [list(value.shape) for value in outputs], "rng": rng_digest(),
        "storage": storage_record(outputs), "outputs": outputs,
    }


def train_mobile(outputs: list[torch.Tensor], labels: torch.Tensor, seed: int, batch_size: int) -> dict[str, Any]:
    seed_everything(seed)
    model = mobilenet_v3_small(weights=None, num_classes=10)
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
        loss.backward(); optimizer.step()
        losses.append(float(loss.detach().item()).hex())
        logits.append((f"batch-{batch_index}", prediction.detach()))
    training_ms = (time.perf_counter_ns() - started) / 1_000_000
    gradients = [(name, parameter.grad) for name, parameter in model.named_parameters() if parameter.grad is not None]
    state = list(model.state_dict().items())
    return {
        "loss_hex": losses, "logits_sha256": named_tensor_digest(logits),
        "gradient_sha256": named_tensor_digest([(name, value) for name, value in gradients]),
        "model_state_sha256": named_tensor_digest(state), "training_ms": training_ms,
    }


def public_preprocess(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "outputs"}


def bootstrap_ci(deltas: list[float]) -> dict[str, Any]:
    require(len(deltas) >= 2, "need_two_paired_timings")
    generator = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(2000):
        means.append(statistics.fmean(deltas[generator.randrange(len(deltas))] for _ in deltas))
    means.sort()
    return {"method": "paired_nonparametric_bootstrap_percentile", "resamples": 2000,
            "seed": BOOTSTRAP_SEED, "mean_delta_ms": statistics.fmean(deltas),
            "ci95_ms": [means[49], means[1949]], "paired_samples": len(deltas)}


def make_context(protocol: dict[str, Any]) -> tuple[Any, Any, Any, Any, Any, Any]:
    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_p5m_relation_boundary_falsification as p5m
    import autocontract_p5o_domain_native_assurance as p5o
    import autocontract_reorder_capability_v0 as capability_v0
    import autocontract_reorder_capability_v2 as capability_v2
    return compiler, p5m, p5o, capability_v0, capability_v2, capability_v2.framework_record()


def make_authorized_bundle(compiler: Any, p5m: Any, v0: Any, v2cap: Any, height: int, width: int) -> tuple[dict[str, Any], dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    domain = p5m.input_domain()
    domain.update({"height_min": height, "height_max": height, "width_min": width, "width_max": width})
    # The trailing Identity is semantically inert. It is included because the
    # workload-specific, cedar-compatible profile measures this three-node
    # pipeline; complete pair receipts still make the Normalize/Crop swap explicit.
    ids = ["normalize", "random_crop", "identity"]
    operators = {
        "normalize": v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]),
        "random_crop": v2.RandomCrop((224, 224)),
        "identity": v2.Identity(),
    }
    base = p5m.make_bundle(compiler, v0, v2cap, ids, operators, domain)
    receipts = [v2cap.make_verified_receipt(base, ids[left], ids[right], operators, domain)
                for left in range(len(ids)) for right in range(left + 1, len(ids))]
    admitted = v2cap.compile_reorder_safe_strict(base, receipts, operators, domain)
    fail_closed = v2cap.compile_reorder_safe_strict(base, [], operators, domain)
    return domain, base, ids, operators, {"receipts": receipts, "admitted": admitted, "fail_closed": fail_closed}


def mutation_checks(v2cap: Any, base: dict[str, Any], receipt: dict[str, Any], operators: dict[str, Any], domain: dict[str, Any]) -> dict[str, Any]:
    bad_domain = dict(domain); bad_domain["height_min"] = 223
    domain_result = v2cap.verify_receipt(receipt, base, operators, bad_domain)
    changed_ops = dict(operators)
    changed_ops["normalize"] = v2.Normalize([0.46, 0.4, 0.35], [0.25, 0.3, 0.35])
    config_result = v2cap.verify_receipt(receipt, base, changed_ops, domain)
    source_bound = copy.deepcopy(receipt)
    source_bound["left"]["source_index_sha256"] = "0" * 64
    source_result = v2cap.verify_receipt(source_bound, base, operators, domain)
    return {
        "domain_height_below_crop": {"result": domain_result, "rejected": not domain_result[0]},
        "config_normalize_mean_changed": {"result": config_result, "rejected": not config_result[0]},
        "source_binding_digest_tamper": {"result": source_result, "rejected": not source_result[0]},
    }


def create_workload_profile(samples: list[torch.Tensor], operators: dict[str, Any], seed: int) -> dict[str, Any]:
    """Measure the fixed baseline nodes and freeze cedar's required YAML schema."""
    current = [value.clone() for value in samples]
    # Node numbering follows the measured three-mapper cedar baseline path: source 3 -> normalize 2 -> crop 1 -> identity 0.
    records: dict[int, dict[str, float | int]] = {3: {"input": 0, "output": sum(x.numel() * x.element_size() for x in current), "latency": 0.001}}
    for node, name in ((2, "normalize"), (1, "random_crop"), (0, "identity")):
        seed_everything(seed)
        input_bytes = sum(x.numel() * x.element_size() for x in current)
        started = time.perf_counter_ns()
        current = [operators[name](value) for value in current]
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        output_bytes = sum(x.numel() * x.element_size() for x in current)
        records[node] = {"input": input_bytes, "output": output_bytes, "latency": max(elapsed / len(samples), 0.001)}
    lines = ["baseline:", "  input_sizes:"]
    for node in range(4): lines.append(f"    {node}: {records[node]['input']}")
    lines.append("  latencies:")
    for node in range(4): lines.append(f"    {node}: {records[node]['latency']:.9f}")
    lines.append("  output_sizes:")
    for node in range(4): lines.append(f"    {node}: {records[node]['output']}")
    lines.append("  throughput: 1")
    PROFILE_YML.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"path": str(PROFILE_YML.relative_to(ROOT)), "sha256": file_sha256(PROFILE_YML), "baseline_node_path": [3, 2, 1, 0], "measured": records}


def execute_manual_oracle(operators: dict[str, Any], samples: list[torch.Tensor], seed: int) -> dict[str, Any]:
    seed_everything(seed)
    started = time.perf_counter_ns()
    try:
        outputs = [operators["identity"](operators["normalize"](operators["random_crop"](sample.clone()))) for sample in samples]
        outcome, exception = "output", None
    except Exception as exc:
        outputs, outcome, exception = [], "exception", {"type": type(exc).__name__, "message": str(exc)}
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    return {"outcome": outcome, "exception": exception, "execution_ms": elapsed, "output_digests": [tensor_digest(x) for x in outputs], "output_shapes": [list(x.shape) for x in outputs], "rng": rng_digest(), "storage": storage_record(outputs), "outputs": outputs}


def run_cell(cedar_root: Path, protocol: dict[str, Any], cell: dict[str, Any], *, phase: str) -> dict[str, Any]:
    compiler, p5m, p5o, v0, v2cap, runtime = make_context(protocol)
    height, width, count = int(cell["height"]), int(cell["width"]), int(cell["samples"])
    domain, base, ids, operators, authorization = make_authorized_bundle(compiler, p5m, v0, v2cap, height, width)
    receipts = authorization["receipts"]
    receipt = receipts[0]
    verify = [v2cap.verify_receipt(item, base, operators, domain) for item in receipts]
    samples, image_provenance = make_samples(cedar_root, height, width, count)
    checks: list[dict[str, Any]] = []
    append_check(checks, "runtime domain guard", not p5o.per_sample_guard(samples, domain))
    native = {name: p5o.classify_native_boundary(operator) for name, operator in operators.items()}
    append_check(checks, "native operations are version-bound", all(item["class"] == "known_versioned_native" for item in native.values()), native)
    append_check(checks, "manual safe oracle configuration", operators["normalize"].inplace is False and operators["random_crop"].padding is None and operators["random_crop"].pad_if_needed is False and height >= 224 and width >= 224)
    append_check(checks, "all complete-pair receipts locally replay", len(receipts) == 3 and all(item[0] for item in verify), verify)
    mutations = mutation_checks(v2cap, base, receipt, operators, domain)
    append_check(checks, "domain config and source mutations reject", all(item["rejected"] for item in mutations.values()), mutations)

    seed = int(protocol["measurement"]["execution_seed"])
    baseline = execute_preprocess(cedar_root, authorization["fail_closed"], ids, operators, samples, seed)
    guarded = execute_preprocess(cedar_root, authorization["admitted"], ids, operators, samples, seed)
    manual = execute_manual_oracle(operators, samples, seed)
    append_check(checks, "fail closed has one candidate; receipt opens reorder", baseline["candidate_count"] == 1 and guarded["candidate_count"] == 6 and baseline["path"] != guarded["path"], {"baseline": public_preprocess(baseline), "guarded": public_preprocess(guarded)})
    baseline_nontrivial = [tag.rsplit(":", 1)[-1] for tag in baseline["execution_order_tags"] if not tag.endswith("identity")]
    guarded_nontrivial = [tag.rsplit(":", 1)[-1] for tag in guarded["execution_order_tags"] if not tag.endswith("identity")]
    append_check(checks, "cedar selected Normalize then Crop versus Crop then Normalize", baseline_nontrivial == ["normalize", "random_crop"] and guarded_nontrivial == ["random_crop", "normalize"], {"baseline": baseline["execution_order_tags"], "guarded": guarded["execution_order_tags"]})
    exact = baseline["outcome"] == guarded["outcome"] == "output" and baseline["exception"] == guarded["exception"] and len(baseline["outputs"]) == len(guarded["outputs"]) == count and all(torch.equal(a, b) for a, b in zip(baseline["outputs"], guarded["outputs"], strict=True))
    append_check(checks, "exact tensors shapes and definedness", exact and baseline["output_shapes"] == guarded["output_shapes"])
    append_check(checks, "exact RNG post state", baseline["rng"] == guarded["rng"], {"baseline": baseline["rng"], "guarded": guarded["rng"]})
    manual_exact = manual["outcome"] == guarded["outcome"] == "output" and manual["exception"] == guarded["exception"] and manual["output_digests"] == guarded["output_digests"] and manual["rng"] == guarded["rng"]
    append_check(checks, "manual Crop Normalize Identity oracle exact to guarded", manual_exact)

    labels = torch.arange(count, dtype=torch.long) % 10
    training_seed, batch_size = int(protocol["measurement"]["training_seed"]), int(protocol["measurement"]["batch_size"])
    baseline_model = train_mobile(baseline["outputs"], labels, training_seed, batch_size)
    guarded_model = train_mobile(guarded["outputs"], labels, training_seed, batch_size)
    manual_model = train_mobile(manual["outputs"], labels, training_seed, batch_size)
    for key, label in (("loss_hex", "loss"), ("logits_sha256", "logits"), ("gradient_sha256", "gradients"), ("model_state_sha256", "model state")):
        append_check(checks, f"MobileNetV3-small {label} exact", baseline_model[key] == guarded_model[key])
        append_check(checks, f"manual oracle MobileNetV3-small {label} exact", manual_model[key] == guarded_model[key])

    # Warmups are intentionally discarded. Paired blocks use fresh sources and a fresh model.
    for _ in range(int(protocol["measurement"]["warmups_per_arm"])):
        execute_preprocess(cedar_root, authorization["fail_closed"], ids, operators, samples, seed)
        execute_preprocess(cedar_root, authorization["admitted"], ids, operators, samples, seed)
    pairs: list[dict[str, Any]] = []
    for index in range(int(cell["timing_pairs"])):
        order = ("baseline", "guarded") if index % 2 == 0 else ("guarded", "baseline")
        recorded: dict[str, Any] = {}
        for arm in order:
            bundle = authorization["fail_closed"] if arm == "baseline" else authorization["admitted"]
            started = time.perf_counter_ns()
            pre = execute_preprocess(cedar_root, bundle, ids, operators, samples, seed)
            model = train_mobile(pre["outputs"], labels, training_seed, batch_size)
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            semantic = pre["outcome"] == "output" and pre["output_digests"] == baseline["output_digests"] and pre["rng"] == baseline["rng"] and all(model[key] == baseline_model[key] for key in ("loss_hex", "logits_sha256", "gradient_sha256", "model_state_sha256"))
            require(semantic, f"paired_block_semantic_mismatch:{arm}:{index}")
            recorded[arm] = {"wall_ms": elapsed, "preprocessing_ms": pre["execution_ms"], "planning_ms": pre["planning_ms"], "training_ms": model["training_ms"]}
        pairs.append({"index": index, "order": list(order), **recorded, "guarded_minus_baseline_ms": recorded["guarded"]["wall_ms"] - recorded["baseline"]["wall_ms"]})
    deltas = [float(pair["guarded_minus_baseline_ms"]) for pair in pairs]
    ratios = [pair["guarded"]["wall_ms"] / pair["baseline"]["wall_ms"] for pair in pairs]
    logs = [math.log(value) for value in ratios]
    extreme = max(range(len(logs)), key=lambda index: abs(logs[index]))
    sensitivity = [value for index, value in enumerate(ratios) if index != extreme]
    performance = {
        "pairs": pairs,
        "baseline_wall_ms": [pair["baseline"]["wall_ms"] for pair in pairs],
        "guarded_wall_ms": [pair["guarded"]["wall_ms"] for pair in pairs],
        "paired_ratios": ratios,
        "paired_guarded_minus_baseline": bootstrap_ci(deltas),
        "wins": sum(value < 1.0 for value in ratios), "losses": sum(value >= 1.0 for value in ratios),
        "paired_median_ratio": statistics.median(ratios), "mean_delta_ms": statistics.fmean(deltas), "median_delta_ms": statistics.median(deltas),
        "remove_most_extreme_pair": {"index": extreme, "paired_median_ratio": statistics.median(sensitivity)},
        "baseline_median_ms": statistics.median(pair["baseline"]["wall_ms"] for pair in pairs),
        "guarded_median_ms": statistics.median(pair["guarded"]["wall_ms"] for pair in pairs),
        "interpretation": "descriptive_internal_proxy_predeclared_benefit_gate_applies_only_to_two-run_S3_aggregate",
    }
    append_check(checks, "paired timing values finite", all(math.isfinite(value) and value > 0 for value in performance["baseline_wall_ms"] + performance["guarded_wall_ms"]))
    passed = sum(item["passed"] for item in checks)
    source_bytes = sum(value.untyped_storage().nbytes() for value in samples)
    return {
        "schema_version": "autocontract.p5r-highres-2d-workload-result.v0", "phase": phase,
        "status": "pass" if passed == len(checks) else "fail", "passed": passed, "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
        "runtime": {**runtime, "cedar_commit": subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip(), "torch_threads": torch.get_num_threads()},
        "cell": cell, "input_domain": domain, "source_owner_retained_bytes": source_bytes, "input_provenance": {"kind": "real-image-content/shape-faithful resident-tensor proxy", "images": image_provenance, "construction_outside_timing": True},
        "scientific_evidence": False, "claim_boundary": protocol["claim_boundary"], "native_boundary": native,
        "receipts": {"count": len(receipts), "verified": verify, "sha256": [canonical_sha256(item) for item in receipts]}, "mutations": mutations,
        "arms": {"fail_closed_baseline": public_preprocess(baseline), "receipt_guarded_cedar": public_preprocess(guarded), "manual_safe_oracle": public_preprocess(manual)},
        "semantic_equivalence": {"preprocess_exact": exact, "manual_oracle_exact": manual_exact, "rng_exact": baseline["rng"] == guarded["rng"], "loss_exact": baseline_model["loss_hex"] == guarded_model["loss_hex"], "logits_exact": baseline_model["logits_sha256"] == guarded_model["logits_sha256"], "gradients_exact": baseline_model["gradient_sha256"] == guarded_model["gradient_sha256"], "model_state_exact": baseline_model["model_state_sha256"] == guarded_model["model_state_sha256"]},
        "performance": performance, "checks": checks,
    }


def check_environment(cedar_root: Path, protocol: dict[str, Any]) -> None:
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    require(head == UPSTREAM_COMMIT and not status, "cedar_checkout_not_pinned_clean")
    require(sys.version.split()[0] == protocol["runtime"]["python"], "python_not_pinned")
    require(torch.__version__ == protocol["runtime"]["torch"], "torch_not_pinned")
    import torchvision
    require(torchvision.__version__ == protocol["runtime"]["torchvision"], "torchvision_not_pinned")
    if str(cedar_root) not in sys.path:
        sys.path.insert(0, str(cedar_root))
    torch.set_num_threads(int(protocol["measurement"]["torch_threads"])); torch.use_deterministic_algorithms(True)


def log_ratio_bootstrap(values: list[float]) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED); logs = [math.log(x) for x in values]; means = []
    for _ in range(10000): means.append(statistics.fmean(logs[rng.randrange(len(logs))] for _ in logs))
    means.sort(); return {"resamples": 10000, "mean_log_ratio": statistics.fmean(logs), "ci95_log": [means[249], means[9749]], "ci95_ratio": [math.exp(means[249]), math.exp(means[9749])], "samples": len(values)}


def aggregate(profile_path: Path, confirm_paths: list[Path]) -> dict[str, Any]:
    profile = json.loads(profile_path.read_text(encoding="utf-8")); confirms = [json.loads(path.read_text(encoding="utf-8")) for path in confirm_paths]
    current_runner = file_sha256(Path(__file__).resolve()); current_protocol = file_sha256(PROTOCOL); current_profile = file_sha256(PROFILE_YML)
    require(profile["phase"] == "profile" and len(confirms) == 2 and all(x["phase"] == "confirm" for x in confirms), "wrong_phase_outputs")
    require(profile["semantic_pass"] and all(x["semantic_pass"] for x in confirms), "cannot_aggregate_semantic_failure")
    require(profile["protocol_sha256"] == current_protocol and profile["runner_sha256"] == current_runner, "profile_hash_mismatch")
    require(profile["workload_profile"]["sha256"] == current_profile, "profile_output_yaml_mismatch")
    require(all(x["protocol_sha256"] == current_protocol and x["runner_sha256"] == current_runner for x in confirms), "confirm_runner_or_protocol_mismatch")
    require(all(x["workload_profile"]["sha256"] == profile["workload_profile"]["sha256"] == current_profile for x in confirms), "confirm_workload_profile_mismatch")
    require(len({x["execution_metadata"]["run_uuid"] for x in confirms}) == 2, "confirm_run_uuid_not_distinct")
    require(len({x["execution_metadata"]["pid"] for x in confirms}) == 2, "confirm_pid_not_distinct")
    starts = [datetime.fromisoformat(x["execution_metadata"]["utc_start"]) for x in confirms]
    require(starts[0] != starts[1] and starts[0] < starts[1], "confirm_utc_not_distinct_or_ordered")
    confirm_cell = json.loads(PROTOCOL.read_text(encoding="utf-8"))["confirm_phase"]["cell"]
    expected_pairs = int(confirm_cell["paired_blocks_per_run"])
    require(expected_pairs == int(confirm_cell["timing_pairs"]) == 21 and all(len(x["cells"]) == 1 and len(x["cells"][0]["performance"]["pairs"]) == expected_pairs for x in confirms), "confirm_pair_count_mismatch")
    ratios = [ratio for output in confirms for ratio in output["cells"][0]["performance"]["paired_ratios"]]
    boot = log_ratio_bootstrap(ratios)
    each_go = [x["cells"][0]["performance"]["paired_median_ratio"] < 0.95 for x in confirms]
    benefit_go = all(each_go) and boot["ci95_log"][1] < math.log(0.95)
    return {
        "schema_version": "autocontract.p5r-highres-2d-workload-aggregate.v1", "semantic_pass": True, "benefit_go": benefit_go,
        "protocol_sha256": current_protocol, "runner_sha256": current_runner, "workload_profile_sha256": current_profile, "profile_output_sha256": file_sha256(profile_path), "confirm_output_sha256": [file_sha256(path) for path in confirm_paths],
        "scientific_evidence": False, "claim_boundary": json.loads(PROTOCOL.read_text(encoding="utf-8"))["claim_boundary"],
        "profile": profile, "confirm_runs": confirms, "aggregate_log_ratio_bootstrap": boot, "per_run_median_ratio_go": each_go,
        "audit": {"distinct_run_uuid": True, "distinct_pid": True, "utc_ordered": True, "pairs_per_confirm": expected_pairs, "runner_sha256": current_runner, "protocol_sha256": current_protocol, "workload_profile_sha256": current_profile},
        "summary": "P5R semantic pass is separate from the preregistered proxy-only benefit gate; neither is general performance evidence.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cedar-root", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("profile", "confirm", "aggregate"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--confirm-output", type=Path, action="append")
    args = parser.parse_args(argv)
    try:
        protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
        if args.mode == "aggregate":
            require(args.profile_output is not None and args.confirm_output is not None and len(args.confirm_output) == 2, "aggregate_requires_two_confirm_outputs")
            result = aggregate(args.profile_output, args.confirm_output)
        else:
            check_environment(args.cedar_root.resolve(), protocol)
            profile_record = None
            if args.mode == "profile":
                target = protocol["confirm_phase"]["cell"]
                profile_samples, _ = make_samples(args.cedar_root.resolve(), int(target["height"]), int(target["width"]), int(target["samples"]))
                profile_ops = {"normalize": v2.Normalize([0.45, 0.4, 0.35], [0.25, 0.3, 0.35]), "random_crop": v2.RandomCrop((224, 224)), "identity": v2.Identity()}
                profile_record = create_workload_profile(profile_samples, profile_ops, int(protocol["measurement"]["execution_seed"]))
            else:
                require(args.profile_output is not None and args.profile_output.is_file(), "confirm_requires_frozen_profile_output")
                prior = json.loads(args.profile_output.read_text(encoding="utf-8"))
                require(prior["semantic_pass"] and PROFILE_YML.is_file() and prior["workload_profile"]["sha256"] == file_sha256(PROFILE_YML), "profile_yaml_sha_mismatch")
            cells = protocol["profile_phase"]["cells"] if args.mode == "profile" else [protocol["confirm_phase"]["cell"]]
            result = {
                "schema_version": "autocontract.p5r-highres-2d-workload-phase.v0", "phase": args.mode,
                "semantic_pass": True, "benefit_go": None, "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
                "scientific_evidence": False, "claim_boundary": protocol["claim_boundary"], "cells": [],
                "workload_profile": profile_record or {"path": str(PROFILE_YML.relative_to(ROOT)), "sha256": file_sha256(PROFILE_YML)},
                "execution_metadata": {"pid": os.getpid(), "utc_start": datetime.now(UTC).isoformat(), "run_uuid": str(uuid.uuid4()), "argv": sys.argv},
            }
            for cell in cells:
                value = run_cell(args.cedar_root.resolve(), protocol, cell, phase=args.mode)
                result["cells"].append(value)
                if value["status"] != "pass": result["semantic_pass"] = False
            if args.mode == "confirm": result["benefit_go"] = result["semantic_pass"] and result["cells"][0]["performance"]["paired_median_ratio"] < 0.95
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("semantic_pass", False) else 1
    except (OSError, P5RError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2)); return 2


if __name__ == "__main__":
    raise SystemExit(main())
