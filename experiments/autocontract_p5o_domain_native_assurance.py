#!/usr/bin/env python3
"""Audit V2 premises/native boundaries and dry-run the final-v3 protocol."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

import jsonschema
import torch
import torchvision
from torchvision.transforms import v2


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))
import autocontract_reorder_capability_v2 as capability_v2  # noqa: E402
import autocontract_r3_source_index_v1 as source_index_v1  # noqa: E402


PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5o_domain_native_assurance_protocol.json"
PUBLIC_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_public_manifest.schema.json"
PRIVATE_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_private_oracle.schema.json"
PREDICTION_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_prediction.schema.json"
PUBLIC_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_public_manifest.template.json"
PRIVATE_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_private_oracle.template.json"
PREDICTION_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_prediction.template.json"
CONTAMINATION_REGISTRY = ROOT / "benchmark" / "final_v1" / "contamination_registry.json"

ALGEBRA_OR_TOTALITY_PREMISES = (
    "type", "layout", "channels", "dtype", "device", "height_min", "width_min",
)
DECLARATION_ONLY_FIELDS = (
    "value_min", "value_max", "height_max", "width_max", "allow_nonfinite",
)
PAIR_FAMILIES = (
    "identity", "pointwise_spatial", "random_context", "boundary_definedness",
    "rounding_precision", "stateful_external", "other_nontrivial", "pointwise_spatial",
)


class P5OError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise P5OError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: object required")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def schema_validate(value: dict[str, Any], path: Path) -> None:
    jsonschema.validate(instance=value, schema=load_json(path))


def premise_profile() -> dict[str, Any]:
    value = {
        "required_runtime_premises": list(ALGEBRA_OR_TOTALITY_PREMISES),
        "declaration_only_fields": list(DECLARATION_ONLY_FIELDS),
    }
    return {**value, "profile_sha256": canonical_sha256(value)}


def declared_domain() -> dict[str, Any]:
    return {
        "type": "torch.Tensor", "layout": "CHW", "channels": 3,
        "dtype": "torch.float32", "value_min": 0.0, "value_max": 1.0,
        "height_min": 24, "height_max": 64, "width_min": 24, "width_max": 64,
        "device": "cpu", "allow_nonfinite": False,
    }


def premise_use_audit() -> dict[str, Any]:
    text = inspect.getsource(capability_v2._ensure_total_on_domain) + inspect.getsource(capability_v2._select_lemma)
    observed = sorted(name for name in capability_v2.DOMAIN_KEYS if f'domain["{name}"]' in text)
    unused_in_lemma_logic = sorted(set(capability_v2.DOMAIN_KEYS) - set(observed))
    return {
        "lemma_logic_domain_fields": observed,
        "required_runtime_premises": list(ALGEBRA_OR_TOTALITY_PREMISES),
        "implementation_boundary_fields": ["type", "layout", "channels", "dtype", "device"],
        "totality_fields": ["height_min", "width_min"],
        "declaration_only_fields": list(DECLARATION_ONLY_FIELDS),
        "unused_in_lemma_logic": unused_in_lemma_logic,
        "finding": "value bounds, maximum spatial bounds, and allow_nonfinite are receipt-bound but are not consumed by either current lemma",
    }


def runtime_native_identity() -> dict[str, Any]:
    config_text = torch.__config__.show()
    record = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "torch_cuda": torch.version.cuda,
        "torch_cxx11_abi": bool(getattr(torch._C, "_GLIBCXX_USE_CXX11_ABI", False)),
        "torch_config_sha256": hashlib.sha256(config_text.encode("utf-8")).hexdigest(),
    }
    return {**record, "identity_sha256": canonical_sha256(record)}


def pure_python_identity(value: Any) -> Any:
    return value


def classify_native_boundary(target: Any) -> dict[str, Any]:
    runtime = runtime_native_identity()
    if isinstance(target, v2.Transform):
        try:
            index = capability_v2.operator_source_index(target)
        except capability_v2.ReorderCapabilityV2Error as exc:
            return {
                "class": "opaque_native", "identity_sha256": None,
                "binding_scope": f"required Python slots unavailable: {exc}", "strict_policy": "force_unknown",
                "source_index_status": "unknown", "source_index_sha256": None,
            }
        return {
            "class": "known_versioned_native", "identity_sha256": runtime["identity_sha256"],
            "binding_scope": "torchvision Python dispatch plus pinned torch/torchvision build identity; native kernel bytes and hardware state are not fully attested",
            "strict_policy": "allow_versioned_relation_only", "source_index_status": index["status"], "source_index_sha256": index["sha256"],
        }
    record = source_index_v1.portable_callable_record(target, ROOT)
    if record["status"] != "supported":
        return {
            "class": "opaque_native", "identity_sha256": None,
            "binding_scope": "callable is builtin/native or has an unportable closure", "strict_policy": "force_unknown",
            "source_index_status": record["status"], "source_index_sha256": canonical_sha256(record),
        }
    return {
        "class": "pure_python", "identity_sha256": canonical_sha256(record),
        "binding_scope": "portable callable layers, constants, defaults, closure, and referenced globals",
        "strict_policy": "allow_local_proof", "source_index_status": record["status"], "source_index_sha256": canonical_sha256(record),
    }


def sample_violations(sample: Any, domain: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if not isinstance(sample, torch.Tensor):
        return ["type"]
    if sample.ndim != 3:
        violations.append("layout")
        return violations
    if sample.shape[0] != domain["channels"]:
        violations.append("channels")
    if sample.dtype != torch.float32:
        violations.append("dtype")
    if sample.device.type != domain["device"]:
        violations.append("device")
    if sample.shape[-2] < domain["height_min"]:
        violations.append("height_min")
    if sample.shape[-1] < domain["width_min"]:
        violations.append("width_min")
    return violations


def registration_guard(_: Any, domain: dict[str, Any]) -> list[dict[str, Any]]:
    capability_v2.validate_input_domain(domain)
    return []


def batch_boundary_guard(samples: Any, domain: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(samples, torch.Tensor):
        if samples.ndim != 4 or samples.shape[0] == 0:
            return [{"sample": "batch", "violations": ["dense_batch_layout"]}]
        violations = sample_violations(samples[0], domain)
        return [] if not violations else [{"sample": "dense_batch", "violations": violations}]
    require(bool(samples), "empty_batch")
    violations = sample_violations(samples[0], domain)
    return [] if not violations else [{"sample": 0, "violations": violations}]


def per_sample_guard(samples: Any, domain: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for index, sample in enumerate(samples):
        violations = sample_violations(sample, domain)
        if violations:
            found.append({"sample": index, "violations": violations})
    return found


def guard_cases() -> list[dict[str, Any]]:
    good = torch.zeros((3, 32, 32), dtype=torch.float32)
    cases: list[tuple[str, list[Any], bool]] = [
        ("all_valid", [good.clone() for _ in range(4)], False),
        ("first_wrong_dtype", [good.double(), good.clone(), good.clone(), good.clone()], True),
        ("later_wrong_dtype", [good.clone(), good.clone(), good.double(), good.clone()], True),
        ("later_wrong_channels", [good.clone(), torch.zeros((1, 32, 32)), good.clone(), good.clone()], True),
        ("later_too_small", [good.clone(), good.clone(), good.clone(), torch.zeros((3, 16, 32))], True),
        ("later_non_tensor", [good.clone(), good.clone(), "not-a-tensor", good.clone()], True),
        ("value_outside_declared_range", [torch.full((3, 32, 32), 2.0), good.clone()], False),
        ("nonfinite_value", [torch.full((3, 32, 32), float("nan")), good.clone()], False),
    ]
    return [{"name": name, "samples": samples, "structural_violation": violation} for name, samples, violation in cases]


def evaluate_guards() -> dict[str, Any]:
    domain = declared_domain()
    modes: dict[str, Callable[[list[Any], dict[str, Any]], list[dict[str, Any]]]] = {
        "registration": registration_guard, "batch_boundary": batch_boundary_guard, "per_sample": per_sample_guard,
    }
    results: dict[str, Any] = {}
    structural_cases = sum(case["structural_violation"] for case in guard_cases())
    for name, guard in modes.items():
        rows = []
        detected = 0
        false_rejects = 0
        for case in guard_cases():
            violations = guard(case["samples"], domain)
            rejected = bool(violations)
            detected += bool(case["structural_violation"] and rejected)
            false_rejects += bool(not case["structural_violation"] and rejected)
            rows.append({"case": case["name"], "expected_structural_violation": case["structural_violation"], "rejected": rejected, "violations": violations})
        results[name] = {
            "detected_structural": detected, "structural_cases": structural_cases,
            "detection_rate": detected / structural_cases, "false_rejects": false_rejects, "cases": rows,
        }
    return results


def evaluate_dense_batch_guard() -> dict[str, Any]:
    domain = declared_domain()
    cases = [
        ("dense_valid", torch.zeros((4, 3, 32, 32), dtype=torch.float32), False),
        ("dense_wrong_dtype", torch.zeros((4, 3, 32, 32), dtype=torch.float64), True),
        ("dense_wrong_channels", torch.zeros((4, 1, 32, 32), dtype=torch.float32), True),
        ("dense_too_small", torch.zeros((4, 3, 16, 32), dtype=torch.float32), True),
        ("dense_value_outside_range", torch.full((4, 3, 32, 32), 2.0), False),
        ("dense_nonfinite", torch.full((4, 3, 32, 32), float("nan")), False),
    ]
    rows = []
    detected = 0
    false_rejects = 0
    for name, batch, expected in cases:
        violations = batch_boundary_guard(batch, domain)
        rejected = bool(violations)
        detected += bool(expected and rejected)
        false_rejects += bool(not expected and rejected)
        rows.append({"case": name, "expected_structural_violation": expected, "rejected": rejected, "violations": violations})
    structural = sum(expected for _, _, expected in cases)
    return {"detected_structural": detected, "structural_cases": structural, "detection_rate": detected / structural, "false_rejects": false_rejects, "cases": rows}


def benchmark_guards(repetitions: int = 200) -> dict[str, Any]:
    domain = declared_domain()
    samples = [torch.zeros((3, 32, 32), dtype=torch.float32) for _ in range(16)]
    dense_batch = torch.zeros((16, 3, 32, 32), dtype=torch.float32)
    modes: dict[str, tuple[str, Callable[[], Any]]] = {
        "registration": ("one control-plane declaration", lambda: registration_guard(samples, domain)),
        "batch_boundary": ("one 16-sample list boundary", lambda: batch_boundary_guard(samples, domain)),
        "dense_batch_boundary": ("one uniform NCHW tensor with 16 samples", lambda: batch_boundary_guard(dense_batch, domain)),
        "per_sample": ("all 16 samples", lambda: per_sample_guard(samples, domain)),
    }
    result: dict[str, Any] = {}
    for name, (scope, action) in modes.items():
        for _ in range(10):
            action()
        timings = []
        for _ in range(repetitions):
            start = time.perf_counter_ns()
            action()
            timings.append(time.perf_counter_ns() - start)
        ordered = sorted(timings)
        result[name] = {
            "scope": scope, "repetitions": repetitions,
            "median_ns": statistics.median(ordered), "p95_ns": ordered[math.ceil(0.95 * len(ordered)) - 1],
            "descriptive_only": True,
        }
    return result


def boundary_for_fixture(index: int, side: str, runtime_sha: str) -> dict[str, Any]:
    if index == 7:
        return {
            "class": "opaque_native", "identity_sha256": None,
            "binding_scope": f"Synthetic opaque native {side} boundary for fail-closed dry-run.", "strict_policy": "force_unknown",
        }
    return {
        "class": "known_versioned_native", "identity_sha256": runtime_sha,
        "binding_scope": f"Synthetic version-bound native {side} fixture; not a real kernel attestation.", "strict_policy": "allow_versioned_relation_only",
    }


def observation_relation(rng: str) -> dict[str, Any]:
    return {
        "output": "exact_tensor", "tolerance_artifact": None, "definedness": "same",
        "exception": "exact_type_and_normalized_payload",
        "rng_post_state": "not_applicable" if rng == "not_applicable" else "exact_python_numpy_torch",
    }


def make_dry_run_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime_sha = runtime_native_identity()["identity_sha256"]
    profile = premise_profile()
    frameworks = [
        {"framework_id": "fixture-vision", "domain": "vision", "repository_url": "https://example.invalid/fixture-vision", "release": "dev", "commit_sha": hashlib.sha1(b"fixture-vision").hexdigest(), "source_tree_sha256": hashlib.sha256(b"fixture-vision-tree").hexdigest()},
        {"framework_id": "fixture-audio", "domain": "audio", "repository_url": "https://example.invalid/fixture-audio", "release": "dev", "commit_sha": hashlib.sha1(b"fixture-audio").hexdigest(), "source_tree_sha256": hashlib.sha256(b"fixture-audio-tree").hexdigest()},
    ]
    pairs = []
    for index, family in enumerate(PAIR_FAMILIES):
        framework = frameworks[index % len(frameworks)]
        rng = ("global_sequential", "operator_keyed", "not_applicable")[index % 3]
        pairs.append({
            "pair_id": f"p5o-dry-pair-{index:02d}", "framework_id": framework["framework_id"], "pair_family": family,
            "left": {"operator_id": f"dry-left-{index:02d}", "type": f"fixture.Left{index}", "configuration": {"index": index}, "source_index_sha256": hashlib.sha256(f"left-{index}".encode()).hexdigest(), "native_boundary": boundary_for_fixture(index, "left", runtime_sha)},
            "right": {"operator_id": f"dry-right-{index:02d}", "type": f"fixture.Right{index}", "configuration": {"index": index}, "source_index_sha256": hashlib.sha256(f"right-{index}".encode()).hexdigest(), "native_boundary": boundary_for_fixture(index, "right", runtime_sha)},
            "input_domain": {
                "description": "Contaminated P5O structural tensor fixture; no independent semantic evidence.",
                "artifact_path": "benchmark/final_v1/p5o_domain_native_assurance_protocol.json", "sha256": file_sha256(PROTOCOL),
                "premise_profile": copy.deepcopy(profile),
                "assurance_plan": {"mode": "per_sample", "guard_artifact": {"name": "P5O structural guard", "path": "experiments/autocontract_p5o_domain_native_assurance.py", "sha256": file_sha256(Path(__file__).resolve())}, "value_scan": "not_required_by_current_lemma"},
            },
            "operation_context": {"scope": "one_invocation_each_order", "rng_assignment": rng, "state_reset": "same_pre_pair_state", "observational_relation": observation_relation(rng), "optimizer_reorder_scope": "adjacent_swap"},
            "source_anchors": [f"synthetic-contaminated:{index}"], "inclusion_reason": "Exercise one predeclared family/RNG/protocol branch without scientific scoring.",
            "contamination": {"development_fixture": True, "registry_match": True},
        })
    public = {
        "schema_version": "autocontract.reorder-final-public.v1", "artifact_type": "reorder_public_manifest",
        "benchmark_id": "autocontract-p5o-contaminated-dry-run", "evaluation_mode": "development_dry_run", "status": "sealed",
        "created_at": "2026-08-01T00:00:00Z", "selection_author": "project-developer-dry-run", "selection_independent_of_analyzer": False,
        "claim_scope": "Contaminated development fixture for P5O schema, guard, native-boundary, and reporting mechanics only.",
        "contamination_registry": {"path": "benchmark/final_v1/contamination_registry.json", "sha256": file_sha256(CONTAMINATION_REGISTRY), "selection_cutoff": "2026-08-01T00:00:00Z"},
        "reporting_plan": {"unsafe_supported_max": 0, "unresolved_supported_max": 0, "prediction_completion_min": 1.0, "commutes_coverage_pilot_floor": 0.3, "family_stratified": True, "rng_stratified": True, "wilson_intervals": True, "non_identity_supported_report": True, "supported_framework_count_report": True, "viability_threshold_status": "draft_pending_dry_run"},
        "frameworks": frameworks, "pairs": pairs,
        "analyzer_bundle": [{"name": "P5O premise/native dry-run", "path": "experiments/autocontract_p5o_domain_native_assurance.py", "sha256": file_sha256(Path(__file__).resolve())}],
    }
    labels = ("commutes", "noncommutes", "unknown", "commutes", "unknown", "noncommutes", "commutes", "unknown")
    units = []
    for index, (pair, label) in enumerate(zip(pairs, labels)):
        checks = {"output_relation": "unresolved", "definedness": "unresolved", "exception": "unresolved", "rng_post_state": "unresolved"}
        proof_kind, premises, witness = "unresolved", [], None
        if label == "commutes":
            proof_kind, premises = "manual_source_proof", ["synthetic_contaminated_dry_run_only"]
            checks = {name: ("not_applicable" if name == "rng_post_state" and pair["operation_context"]["rng_assignment"] == "not_applicable" else "verified") for name in checks}
        elif label == "noncommutes":
            proof_kind = "counterexample"
            checks = {"output_relation": "violated", "definedness": "verified", "exception": "verified", "rng_post_state": "verified"}
            witness = {"seed": index, "mismatch_dimension": "output", "input_sha256": hashlib.sha256(f"input-{index}".encode()).hexdigest(), "original_outcome_sha256": hashlib.sha256(f"original-{index}".encode()).hexdigest(), "swapped_outcome_sha256": hashlib.sha256(f"swapped-{index}".encode()).hexdigest(), "reproduction_command_sha256": hashlib.sha256(f"command-{index}".encode()).hexdigest()}
        units.append({"pair_id": pair["pair_id"], "primary_label": label, "reviewer_label": label, "adjudicated_label": label, "confidence": "low", "proof_kind": proof_kind, "rationale": "Synthetic contaminated private rationale for protocol mechanics only.", "premises": premises, "observation_checks": checks, "evidence_anchors": [f"synthetic-private:{index}"], "counterexample": witness, "reviewed_by": ["dry-reviewer"]})
    oracle = {
        "schema_version": "autocontract.reorder-final-oracle.v1", "artifact_type": "reorder_private_oracle", "benchmark_id": public["benchmark_id"],
        "public_manifest_sha256": canonical_sha256(public), "commitment_salt_hex": hashlib.sha256(b"p5o-dry-run-salt").hexdigest(),
        "annotators": [{"annotator_id": "dry-primary", "role": "primary", "independent_of_analyzer": True, "conflict_disclosure": "project-generated contaminated fixture"}, {"annotator_id": "dry-reviewer", "role": "reviewer", "independent_of_analyzer": True, "conflict_disclosure": "project-generated contaminated fixture"}],
        "units": units, "adjudication": {"status": "complete", "disagreement_count": 0, "record_sha256": hashlib.sha256(b"p5o-dry-adjudication").hexdigest()},
    }
    prediction_pairs = []
    for index, pair in enumerate(pairs):
        supported = labels[index] == "commutes" and index != 7
        left_class, right_class = pair["left"]["native_boundary"]["class"], pair["right"]["native_boundary"]["class"]
        prediction_pairs.append({
            "pair_id": pair["pair_id"], "status": "supported" if supported else "unknown",
            "assurance_level": "locally_replayed_versioned_relation_algebra" if supported else "none",
            "reason": "synthetic_protocol_supported" if supported else "synthetic_protocol_unknown",
            "receipt_sha256": hashlib.sha256(f"receipt-{index}".encode()).hexdigest() if supported else None,
            "observational_relation_id": "exact-output-definedness-exception-rng-v1",
            "domain_assurance": {"mode": "per_sample", "premise_profile_sha256": profile["profile_sha256"], "guard_artifact_sha256": file_sha256(Path(__file__).resolve()), "checked_invocations": 8, "violations": 0, "overhead_ns_per_invocation": 0.0},
            "native_decision": {"left_class": left_class, "right_class": right_class, "runtime_identity_sha256": None if "opaque_native" in {left_class, right_class} else runtime_sha, "policy": "force_unknown" if "opaque_native" in {left_class, right_class} else "versioned_relation"},
            "generation_ms": 1.0 + index, "adapter_minutes": 0.5,
        })
    prediction = {
        "schema_version": "autocontract.reorder-final-prediction.v1", "artifact_type": "reorder_prediction", "benchmark_id": public["benchmark_id"],
        "public_manifest_sha256": canonical_sha256(public), "producer_bundle_sha256": canonical_sha256(public["analyzer_bundle"]),
        "created_at": "2026-08-01T01:00:00Z", "status": "sealed", "pairs": prediction_pairs,
        "burden": {"total_adapter_minutes": 4.0, "source_inspection_minutes": 3.0, "guard_implementation_minutes": 5.0, "semantic_rule_sloc": 0, "all_pairs_timed": True},
    }
    return public, oracle, prediction


def validate_public(public: dict[str, Any]) -> None:
    schema_validate(public, PUBLIC_SCHEMA)
    framework_ids = {item["framework_id"] for item in public["frameworks"]}
    pair_ids = [item["pair_id"] for item in public["pairs"]]
    require(len(pair_ids) == len(set(pair_ids)), "duplicate_pair_id")
    expected_profile = premise_profile()
    for pair in public["pairs"]:
        require(pair["framework_id"] in framework_ids, f"{pair['pair_id']}:unknown_framework")
        require(pair["input_domain"]["premise_profile"] == expected_profile, f"{pair['pair_id']}:premise_profile_drift")
        relation = pair["operation_context"]["observational_relation"]
        require((relation["output"] == "declared_tolerance") == (relation["tolerance_artifact"] is not None), f"{pair['pair_id']}:tolerance_artifact_mismatch")
        for side in ("left", "right"):
            boundary = pair[side]["native_boundary"]
            expected_policy = {"pure_python": "allow_local_proof", "known_versioned_native": "allow_versioned_relation_only", "opaque_native": "force_unknown", "external_attested_native": "require_external_attestation"}[boundary["class"]]
            require(boundary["strict_policy"] == expected_policy, f"{pair['pair_id']}:{side}:native_policy_mismatch")
    if public["evaluation_mode"] == "development_dry_run":
        require(6 <= len(pair_ids) <= 8, "dry_run_pair_count_outside_6_8")
        require(all(pair["contamination"]["development_fixture"] for pair in public["pairs"]), "dry_run_must_be_marked_contaminated")
    else:
        require(public["status"] == "sealed" and public["selection_independent_of_analyzer"], "final_independence_or_seal_missing")
        require(20 <= len(pair_ids) <= 40 and len(framework_ids) >= 3, "final_pair_or_framework_quota_missing")
        require(len({item["domain"] for item in public["frameworks"]}) >= 2, "final_domain_quota_missing")
        require(len({pair["pair_family"] for pair in public["pairs"]}) >= 4, "final_family_stratification_missing")
        require(all(not pair["contamination"]["development_fixture"] and not pair["contamination"]["registry_match"] for pair in public["pairs"]), "final_contamination_detected")
        require(public["reporting_plan"]["viability_threshold_status"] == "frozen_before_independent_selection", "final_viability_reporting_not_frozen")


def validate_private(oracle: dict[str, Any], public: dict[str, Any]) -> None:
    schema_validate(oracle, PRIVATE_SCHEMA)
    require(oracle["benchmark_id"] == public["benchmark_id"] and oracle["public_manifest_sha256"] == canonical_sha256(public), "oracle_public_binding_mismatch")
    require([unit["pair_id"] for unit in oracle["units"]] == [pair["pair_id"] for pair in public["pairs"]], "oracle_pair_order_mismatch")
    for unit in oracle["units"]:
        label, checks = unit["adjudicated_label"], unit["observation_checks"]
        if label == "commutes":
            require(unit["proof_kind"] in {"formal", "manual_source_proof"} and unit["premises"] and unit["counterexample"] is None, f"{unit['pair_id']}:bad_commutes_evidence")
            require(all(value in {"verified", "not_applicable"} for value in checks.values()), f"{unit['pair_id']}:commutes_observation_unresolved")
        elif label == "noncommutes":
            require(unit["proof_kind"] == "counterexample" and unit["counterexample"] is not None, f"{unit['pair_id']}:noncommutes_witness_missing")
            require("violated" in checks.values(), f"{unit['pair_id']}:noncommutes_without_violated_observation")
        else:
            require(unit["proof_kind"] == "unresolved" and unit["counterexample"] is None and "unresolved" in checks.values(), f"{unit['pair_id']}:bad_unknown_evidence")


def validate_prediction(prediction: dict[str, Any], public: dict[str, Any]) -> None:
    schema_validate(prediction, PREDICTION_SCHEMA)
    require(prediction["benchmark_id"] == public["benchmark_id"] and prediction["public_manifest_sha256"] == canonical_sha256(public), "prediction_public_binding_mismatch")
    require(prediction["producer_bundle_sha256"] == canonical_sha256(public["analyzer_bundle"]), "producer_bundle_mismatch")
    by_id = {pair["pair_id"]: pair for pair in public["pairs"]}
    require([item["pair_id"] for item in prediction["pairs"]] == list(by_id), "prediction_pair_order_mismatch")
    adapter_total = 0.0
    for item in prediction["pairs"]:
        pair = by_id[item["pair_id"]]
        adapter_total += float(item["adapter_minutes"])
        require(item["domain_assurance"]["premise_profile_sha256"] == pair["input_domain"]["premise_profile"]["profile_sha256"], f"{item['pair_id']}:domain_profile_mismatch")
        public_classes = {pair["left"]["native_boundary"]["class"], pair["right"]["native_boundary"]["class"]}
        predicted_classes = {item["native_decision"]["left_class"], item["native_decision"]["right_class"]}
        require(public_classes == predicted_classes, f"{item['pair_id']}:native_class_mismatch")
        if item["status"] == "supported":
            require(item["receipt_sha256"] is not None and item["assurance_level"] != "none", f"{item['pair_id']}:supported_without_receipt")
            require(item["domain_assurance"]["mode"] in {"batch_boundary", "per_sample", "external_attestation"} and item["domain_assurance"]["violations"] == 0, f"{item['pair_id']}:supported_without_runtime_domain_assurance")
            require("opaque_native" not in public_classes or item["native_decision"]["policy"] == "external_attestation", f"{item['pair_id']}:opaque_native_supported_without_attestation")
            relation = pair["operation_context"]["observational_relation"]
            require(relation["output"] != "declared_tolerance" or item["assurance_level"] == "trusted_revocable_external_proof", f"{item['pair_id']}:local_exact_lemma_used_for_tolerance_relation")
        else:
            require(item["receipt_sha256"] is None and item["assurance_level"] == "none", f"{item['pair_id']}:non_supported_carries_receipt")
    require(abs(adapter_total - float(prediction["burden"]["total_adapter_minutes"])) <= 1e-9, "adapter_burden_total_mismatch")


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> dict[str, float | int | None]:
    if total == 0:
        return {"successes": successes, "total": total, "rate": None, "low": None, "high": None}
    rate = successes / total
    denominator = 1.0 + z * z / total
    centre = (rate + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total)) / denominator
    return {"successes": successes, "total": total, "rate": rate, "low": max(0.0, centre - margin), "high": min(1.0, centre + margin)}


def score_dry_run(public: dict[str, Any], oracle: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    labels = {unit["pair_id"]: unit["adjudicated_label"] for unit in oracle["units"]}
    predictions = {item["pair_id"]: item["status"] for item in prediction["pairs"]}
    unsafe = sum(predictions[pair_id] == "supported" and label == "noncommutes" for pair_id, label in labels.items())
    unresolved = sum(predictions[pair_id] == "supported" and label == "unknown" for pair_id, label in labels.items())
    family: dict[str, dict[str, Any]] = {}
    rng: dict[str, dict[str, Any]] = {}
    for pair in public["pairs"]:
        pair_id, label = pair["pair_id"], labels[pair["pair_id"]]
        for key, bucket in ((pair["pair_family"], family), (pair["operation_context"]["rng_assignment"], rng)):
            row = bucket.setdefault(key, {"commutes": 0, "supported_commutes": 0})
            if label == "commutes":
                row["commutes"] += 1
                row["supported_commutes"] += predictions[pair_id] == "supported"
    for bucket in (family, rng):
        for row in bucket.values():
            row["wilson"] = wilson(row["supported_commutes"], row["commutes"])
    supported_pairs = [pair for pair in public["pairs"] if predictions[pair["pair_id"]] == "supported"]
    return {
        "unsafe_supported": unsafe, "unresolved_supported": unresolved,
        "overall_commutes_coverage": wilson(sum(predictions[pair_id] == "supported" and label == "commutes" for pair_id, label in labels.items()), sum(label == "commutes" for label in labels.values())),
        "family_strata": family, "rng_strata": rng,
        "non_identity_supported": sum(pair["pair_family"] != "identity" for pair in supported_pairs),
        "supported_framework_count": len({pair["framework_id"] for pair in supported_pairs}),
        "scientific_evidence": False,
    }


def expect_failure(name: str, action: Callable[[], Any], checks: list[dict[str, Any]]) -> None:
    try:
        action()
    except (P5OError, jsonschema.ValidationError, KeyError, TypeError, ValueError) as exc:
        checks.append({"name": name, "passed": True, "reason": f"{type(exc).__name__}:{exc}"})
    else:
        checks.append({"name": name, "passed": False, "reason": "unexpected_accept"})


def run(output_path: Path | None) -> dict[str, Any]:
    protocol = load_json(PROTOCOL)
    checks: list[dict[str, Any]] = []
    frozen = {path: file_sha256(ROOT / path) for path in protocol["frozen_predecessors"]}
    checks.append({"name": "frozen predecessors exact", "passed": frozen == protocol["frozen_predecessors"], "observed": frozen})

    audit = premise_use_audit()
    checks.append({"name": "lemma premise-use audit isolates only spatial minima in proof logic", "passed": audit["lemma_logic_domain_fields"] == ["height_min", "width_min"]})
    checks.append({"name": "value/max/nonfinite fields classified declaration-only", "passed": audit["declaration_only_fields"] == list(DECLARATION_ONLY_FIELDS) and set(DECLARATION_ONLY_FIELDS) <= set(audit["unused_in_lemma_logic"])})

    for template, schema, name in ((PUBLIC_TEMPLATE, PUBLIC_SCHEMA, "public"), (PRIVATE_TEMPLATE, PRIVATE_SCHEMA, "private"), (PREDICTION_TEMPLATE, PREDICTION_SCHEMA, "prediction")):
        schema_validate(load_json(template), schema)
        checks.append({"name": f"final-v3 {name} template validates", "passed": True})

    guard_results = evaluate_guards()
    dense_batch_result = evaluate_dense_batch_guard()
    checks.append({"name": "per-sample guard detects every structural violation", "passed": guard_results["per_sample"]["detected_structural"] == guard_results["per_sample"]["structural_cases"] and guard_results["per_sample"]["false_rejects"] == 0})
    checks.append({"name": "registration attestation does not pretend to detect runtime substitution", "passed": guard_results["registration"]["detected_structural"] == 0})
    checks.append({"name": "representative batch sentinel limitation is measured", "passed": 0 < guard_results["batch_boundary"]["detected_structural"] < guard_results["batch_boundary"]["structural_cases"]})
    checks.append({"name": "uniform dense-batch structural sentinel detects shared violations", "passed": dense_batch_result["detected_structural"] == dense_batch_result["structural_cases"] and dense_batch_result["false_rejects"] == 0})
    checks.append({"name": "unused value range is not hot-scanned", "passed": all(not next(row for row in guard_results[mode]["cases"] if row["case"] == "value_outside_declared_range")["rejected"] for mode in guard_results)})
    checks.append({"name": "unused finite-value declaration is not hot-scanned", "passed": all(not next(row for row in guard_results[mode]["cases"] if row["case"] == "nonfinite_value")["rejected"] for mode in guard_results)})

    pure_boundary = classify_native_boundary(pure_python_identity)
    known_boundary = classify_native_boundary(v2.Identity())
    opaque_boundary = classify_native_boundary(len)
    checks.append({"name": "pure Python callable remains distinguishable", "passed": pure_boundary["class"] == "pure_python" and pure_boundary["strict_policy"] == "allow_local_proof"})
    checks.append({"name": "torchvision transform is version-bound native, not mislabeled pure Python", "passed": known_boundary["class"] == "known_versioned_native" and known_boundary["identity_sha256"] is not None})
    checks.append({"name": "uninspectable builtin fails closed as opaque native", "passed": opaque_boundary["class"] == "opaque_native" and opaque_boundary["strict_policy"] == "force_unknown"})

    public, oracle, prediction = make_dry_run_fixture()
    validate_public(public); validate_private(oracle, public); validate_prediction(prediction, public)
    checks.append({"name": "eight-pair contaminated dry-run validates", "passed": len(public["pairs"]) == 8 and not public["selection_independent_of_analyzer"] and all(pair["contamination"]["development_fixture"] for pair in public["pairs"])})

    broken = copy.deepcopy(prediction)
    broken["pairs"][7].update({"status": "supported", "assurance_level": "locally_replayed_versioned_relation_algebra", "receipt_sha256": hashlib.sha256(b"bad-opaque-receipt").hexdigest()})
    expect_failure("opaque native Supported without external attestation rejected", lambda: validate_prediction(broken, public), checks)
    broken = copy.deepcopy(prediction)
    supported_index = next(index for index, item in enumerate(broken["pairs"]) if item["status"] == "supported")
    broken["pairs"][supported_index]["domain_assurance"]["violations"] = 1
    expect_failure("Supported with runtime premise violation rejected", lambda: validate_prediction(broken, public), checks)
    broken_public, broken_prediction = copy.deepcopy(public), copy.deepcopy(prediction)
    broken_public["pairs"][supported_index]["operation_context"]["observational_relation"].update({"output": "declared_tolerance", "tolerance_artifact": {"name": "synthetic tolerance", "path": "benchmark/final_v1/p5o_domain_native_assurance_protocol.json", "sha256": file_sha256(PROTOCOL)}})
    broken_prediction["public_manifest_sha256"] = canonical_sha256(broken_public)
    expect_failure("local exact lemma cannot silently authorize tolerance relation", lambda: validate_prediction(broken_prediction, broken_public), checks)

    score = score_dry_run(public, oracle, prediction)
    checks.append({"name": "family/RNG/Wilson/non-identity reporting produced", "passed": score["scientific_evidence"] is False and len(score["family_strata"]) >= 4 and len(score["rng_strata"]) >= 2 and score["non_identity_supported"] >= 1 and score["supported_framework_count"] >= 2})
    overhead = benchmark_guards()
    checks.append({"name": "guard overhead measured descriptively without posthoc threshold", "passed": all(row["median_ns"] >= 0 and row["p95_ns"] >= row["median_ns"] and row["descriptive_only"] for row in overhead.values())})

    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5o-domain-native-assurance-result.v0",
        "status": "pass" if passed == len(checks) else "fail", "passed": passed, "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
        "schema_sha256": {"public": file_sha256(PUBLIC_SCHEMA), "private": file_sha256(PRIVATE_SCHEMA), "prediction": file_sha256(PREDICTION_SCHEMA)},
        "premise_audit": audit, "domain_assurance": {"detection": guard_results, "dense_batch_detection": dense_batch_result, "overhead": overhead},
        "native_boundary": {"runtime_identity": runtime_native_identity(), "pure_python": pure_boundary, "known_versioned_native": known_boundary, "opaque_native": opaque_boundary},
        "dry_run": {"public_sha256": canonical_sha256(public), "oracle_sha256": canonical_sha256(oracle), "prediction_sha256": canonical_sha256(prediction), "score": score, "scientific_evidence": False},
        "checks": checks, "claim_boundary": protocol["claim_boundary"],
    }
    if output_path is not None:
        write_json(output_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = run(args.output)
    except (OSError, P5OError, jsonschema.ValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
