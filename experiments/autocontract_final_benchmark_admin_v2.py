#!/usr/bin/env python3
"""Leakage, scope, commitment, and sealing guards for final-blind v2.

This module is administrative infrastructure, not benchmark evidence.  It
never scores analyzer predictions.  In particular, ReplayCapabilityV1 is
restricted to registered parameter replay; cache and reorder candidates keep
rewrite-specific verification plans and do not receive generic capability
labels.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "benchmark" / "final_v1" / "contamination_registry.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")

REQUIRED_GATES = {
    "known_unsafe_false_accepts_max": 0,
    "semantic_safe_recall_min": 0.8,
    "semantic_reason_accuracy_min": 0.9,
    "semantic_resolution_min": 0.9,
    "replay_capability_resolution_min": 0.9,
    "source_resolution_min": 0.9,
    "final_safe_admit_recall_min": 0.8,
    "oracle_benefit_coverage_min": 0.9,
}

FORBIDDEN_PUBLIC_KEYS = {
    "answer", "capability_status", "coarse_reason", "confidence", "decision",
    "effect_labels", "expected_capability_status", "expected_decision",
    "expected_effects", "expected_output", "expected_reason",
    "expected_replay_capability_status", "expected_semantic_decision",
    "final_status", "gold", "ground_truth", "is_safe", "is_unsafe",
    "known_unsafe", "label", "labels", "oracle", "outcome", "rationale",
    "reference_answer", "replay_capability_reason", "safe",
    "semantic_oracle", "source_index_status", "target_decision", "unsafe",
    "verdict",
}

COARSE_REASONS = {
    "none", "hidden_rng_effect", "external_state_drift", "state_mutation",
    "mode_dependent_effect", "lineage_or_binding_mismatch",
    "augmentation_diversity_frozen", "gradient_or_autograd_change",
    "unsupported_or_ambiguous",
}

REPLAY_CHECKS = {
    "rng_state_restoration": {
        "public_callable", "deterministic_mode", "exact_replay",
        "caller_rng_unchanged",
    },
    "stored_parameter_record": {
        "record_generated", "stored_params_present", "public_restore_completed",
        "exact_replay", "caller_rng_unchanged",
    },
    "none": set(),
}

TOP_PUBLIC = {
    "schema_version", "artifact_type", "benchmark_id", "status", "created_at",
    "selection_author", "claim_scope", "analyzer_bundle",
    "contamination_policy", "metric_gates", "units",
}
TOP_PRIVATE = {
    "schema_version", "artifact_type", "benchmark_id", "public_manifest_sha256",
    "commitment_salt_hex", "annotators", "units", "adjudication",
}


class ValidationError(ValueError):
    """Raised for a protocol violation."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def oracle_commitment_sha256(oracle: dict[str, Any]) -> str:
    return hashlib.sha256(b"autocontract.final-oracle.v2\0" + canonical_bytes(oracle)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"top-level JSON must be an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def exact_keys(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{where} must be an object")
    missing, extra = keys - set(value), set(value) - keys
    require(not missing and not extra, f"{where} keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    return value


def find_forbidden_keys(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if key.casefold() in FORBIDDEN_PUBLIC_KEYS:
                findings.append(path)
            findings.extend(find_forbidden_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_forbidden_keys(child, f"{prefix}[{index}]"))
    return findings


def string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from string_values(child)


def normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def validate_artifact(value: Any, where: str, *, named: bool = False, strict: bool = False) -> None:
    keys = {"path", "sha256", "name"} if named else {"path", "sha256"}
    artifact = exact_keys(value, keys, where)
    if named:
        require(isinstance(artifact["name"], str) and artifact["name"], f"{where}.name is required")
    require(isinstance(artifact["path"], str) and artifact["path"], f"{where}.path is required")
    require(isinstance(artifact["sha256"], str) and HEX64.fullmatch(artifact["sha256"]) is not None, f"{where}.sha256 is invalid")
    if strict:
        require(artifact["sha256"] != "0" * 64, f"{where}.sha256 is a placeholder")


def validate_public(manifest: dict[str, Any], *, strict: bool = False, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    exact_keys(manifest, TOP_PUBLIC, "public")
    require(manifest["schema_version"] == "autocontract.final-public.v2", "bad public schema_version")
    require(manifest["artifact_type"] == "public_manifest", "bad public artifact_type")
    require(isinstance(manifest["benchmark_id"], str) and ID_PATTERN.fullmatch(manifest["benchmark_id"]), "invalid benchmark_id")
    require(manifest["status"] in {"draft", "sealed"}, "status must be draft or sealed")
    require(isinstance(manifest["created_at"], str) and manifest["created_at"], "created_at is required")
    require(isinstance(manifest["selection_author"], str) and manifest["selection_author"], "selection_author is required")
    require(isinstance(manifest["claim_scope"], str) and len(manifest["claim_scope"]) >= 20, "claim_scope is too short")
    leaked = find_forbidden_keys(manifest)
    require(not leaked, "answer-bearing key(s) in public manifest: " + ", ".join(leaked))

    bundle = exact_keys(manifest["analyzer_bundle"], {"systems", "runner", "adapters", "schemas"}, "analyzer_bundle")
    systems = exact_keys(bundle["systems"], {"effect", "replay_capability", "source_index"}, "analyzer_bundle.systems")
    for name in ("effect", "replay_capability", "source_index"):
        validate_artifact(systems[name], f"analyzer_bundle.systems.{name}", named=True, strict=strict)
    validate_artifact(bundle["runner"], "analyzer_bundle.runner", strict=strict)
    for group in ("adapters", "schemas"):
        require(isinstance(bundle[group], list), f"analyzer_bundle.{group} must be an array")
    require(bundle["adapters"], "at least one adapter is required")
    require(len(bundle["schemas"]) >= 3, "at least three schemas are required")
    for group in ("adapters", "schemas"):
        for index, artifact in enumerate(bundle[group]):
            validate_artifact(artifact, f"analyzer_bundle.{group}[{index}]", strict=strict)
    artifact_paths = [systems[n]["path"] for n in systems] + [bundle["runner"]["path"]] + [a["path"] for a in bundle["adapters"]] + [a["path"] for a in bundle["schemas"]]
    require(len(artifact_paths) == len(set(artifact_paths)), "declared artifact paths must be unique")

    require(manifest["metric_gates"] == REQUIRED_GATES, f"metric_gates must remain frozen at {REQUIRED_GATES}")
    policy = exact_keys(manifest["contamination_policy"], {"registry_path", "selection_cutoff", "minimum_novel_frameworks"}, "contamination_policy")
    require(isinstance(policy["registry_path"], str) and policy["registry_path"], "registry_path is required")
    require(isinstance(policy["selection_cutoff"], str) and policy["selection_cutoff"], "selection_cutoff is required")
    require(isinstance(policy["minimum_novel_frameworks"], int) and policy["minimum_novel_frameworks"] >= 1, "minimum_novel_frameworks must be positive")

    units = manifest["units"]
    require(isinstance(units, list) and units, "units must be a non-empty array")
    unit_ids: list[str] = []
    frameworks: set[str] = set()
    domains: set[str] = set()
    task_counts = {"contract_inference": 0, "rewrite_validation": 0, "optimizer_workload": 0}
    replay_denominator = 0
    for index, unit in enumerate(units):
        where = f"units[{index}]"
        exact_keys(unit, {"unit_id", "task_type", "split", "framework", "domain", "repository", "source_binding", "operation_context", "candidate", "contract_plan", "verification_plan"}, where)
        unit_id = unit["unit_id"]
        require(isinstance(unit_id, str) and ID_PATTERN.fullmatch(unit_id), f"{where}.unit_id is invalid")
        unit_ids.append(unit_id)
        require(unit["split"] == "final_blind", f"{unit_id}: split must be final_blind")
        require(unit["task_type"] in task_counts, f"{unit_id}: invalid task_type")
        task_counts[unit["task_type"]] += 1
        for field in ("framework", "domain"):
            require(isinstance(unit[field], str) and unit[field].strip(), f"{unit_id}: {field} is required")
        frameworks.add(unit["framework"].casefold())
        domains.add(unit["domain"].casefold())

        repository = exact_keys(unit["repository"], {"url", "release", "commit_sha"}, f"{unit_id}.repository")
        require(str(repository["url"]).startswith("https://"), f"{unit_id}: repository URL must use https")
        require(isinstance(repository["release"], str) and repository["release"], f"{unit_id}: release is required")
        require(isinstance(repository["commit_sha"], str) and HEX40.fullmatch(repository["commit_sha"]), f"{unit_id}: bad commit_sha")
        binding = exact_keys(unit["source_binding"], {"path", "public_symbol", "binding_sha256"}, f"{unit_id}.source_binding")
        require(bool(binding["path"]) and bool(binding["public_symbol"]), f"{unit_id}: incomplete source binding")
        require(isinstance(binding["binding_sha256"], str) and HEX64.fullmatch(binding["binding_sha256"]), f"{unit_id}: bad binding_sha256")

        context = exact_keys(unit["operation_context"], {"configuration", "operation", "lifecycle_phase", "named_modes", "assumptions", "input_schema_sha256"}, f"{unit_id}.operation_context")
        require(isinstance(context["configuration"], dict), f"{unit_id}: configuration must be an object")
        require(context["operation"] in {"contract_inference", "sample_apply", "replay_apply", "cache_read", "cache_write", "adjacent_reorder", "training_step"}, f"{unit_id}: invalid operation")
        require(context["lifecycle_phase"] in {"construction", "iteration", "training", "evaluation", "serving"}, f"{unit_id}: invalid lifecycle_phase")
        require(isinstance(context["named_modes"], list) and isinstance(context["assumptions"], list), f"{unit_id}: modes/assumptions must be arrays")
        require(isinstance(context["input_schema_sha256"], str) and HEX64.fullmatch(context["input_schema_sha256"]), f"{unit_id}: bad input_schema_sha256")

        candidate = unit["candidate"]
        require(isinstance(candidate, dict) and set(candidate) in ({"kind", "operators"}, {"kind", "operators", "cost_profile_id"}), f"{unit_id}: candidate keys mismatch")
        kind = candidate["kind"]
        require(kind in {"none", "cache_prefix", "registered_parameter_replay", "adjacent_swap"}, f"{unit_id}: invalid candidate kind")
        require(isinstance(candidate["operators"], list), f"{unit_id}: operators must be an array")

        plan = exact_keys(unit["contract_plan"], {"semantic", "replay_capability", "source_index"}, f"{unit_id}.contract_plan")
        semantic = exact_keys(plan["semantic"], {"analyzer_entrypoint", "required_effect_dimensions"}, f"{unit_id}.semantic")
        require(isinstance(semantic["analyzer_entrypoint"], str) and semantic["analyzer_entrypoint"], f"{unit_id}: analyzer_entrypoint is required")
        require(isinstance(semantic["required_effect_dimensions"], list) and semantic["required_effect_dimensions"], f"{unit_id}: effect dimensions required")

        replay = exact_keys(plan["replay_capability"], {"mechanism", "required_checks", "lineage_operands", "target_dependent_operands"}, f"{unit_id}.replay_capability")
        mechanism = replay["mechanism"]
        require(mechanism in REPLAY_CHECKS, f"{unit_id}: invalid replay mechanism")
        require(isinstance(replay["required_checks"], list) and set(replay["required_checks"]) == REPLAY_CHECKS[mechanism] and len(replay["required_checks"]) == len(REPLAY_CHECKS[mechanism]), f"{unit_id}: replay checks do not exactly match mechanism")
        if kind == "registered_parameter_replay":
            require(mechanism != "none", f"{unit_id}: registered replay needs a replay mechanism")
            replay_denominator += 1
        else:
            require(mechanism == "none", f"{unit_id}: non-replay candidate cannot claim ReplayCapabilityV1")
        require(isinstance(replay["lineage_operands"], list), f"{unit_id}: lineage_operands must be an array")
        names: list[str] = []
        roles: list[str] = []
        for op_index, operand in enumerate(replay["lineage_operands"]):
            operand = exact_keys(operand, {"name", "role"}, f"{unit_id}.lineage_operands[{op_index}]")
            require(isinstance(operand["name"], str) and operand["name"], f"{unit_id}: empty operand name")
            require(operand["role"] in {"primary_input", "secondary_input", "metadata_target", "parameter_record"}, f"{unit_id}: invalid operand role")
            names.append(operand["name"]); roles.append(operand["role"])
        require(len(names) == len(set(names)), f"{unit_id}: duplicate lineage operand")
        targets = replay["target_dependent_operands"]
        require(isinstance(targets, list) and set(targets) <= set(names), f"{unit_id}: target-dependent operand is unbound")
        if mechanism != "none":
            require("primary_input" in roles, f"{unit_id}: replay requires primary_input lineage")
        if mechanism == "stored_parameter_record":
            require("parameter_record" in roles, f"{unit_id}: stored replay requires parameter_record lineage")

        source = exact_keys(plan["source_index"], {"schema_version", "binding_components", "unknown_policy"}, f"{unit_id}.source_index")
        require(source["schema_version"] == "autocontract.executable-source-index.v1", f"{unit_id}: bad source-index schema")
        require(source["unknown_policy"] == "fail_closed", f"{unit_id}: source-index must fail closed")
        require(isinstance(source["binding_components"], list) and source["binding_components"], f"{unit_id}: source binding components cannot be empty")
        component_names: list[str] = []
        for comp_index, component in enumerate(source["binding_components"]):
            component = exact_keys(component, {"name", "callable_slots"}, f"{unit_id}.binding_components[{comp_index}]")
            require(isinstance(component["name"], str) and component["name"], f"{unit_id}: component name required")
            require(isinstance(component["callable_slots"], list) and component["callable_slots"] and all(isinstance(x, str) and x for x in component["callable_slots"]), f"{unit_id}: callable slots cannot be empty")
            component_names.append(component["name"])
        require(len(component_names) == len(set(component_names)), f"{unit_id}: duplicate binding component")

        verification = exact_keys(unit["verification_plan"], {"output_checks", "effect_checks", "replay_capability_checks", "source_checks", "performance_checks"}, f"{unit_id}.verification_plan")
        for field, checks in verification.items():
            require(isinstance(checks, list), f"{unit_id}: {field} must be an array")
        if kind == "registered_parameter_replay":
            require(verification["replay_capability_checks"], f"{unit_id}: registered replay needs capability verification")
        else:
            require(not verification["replay_capability_checks"], f"{unit_id}: non-replay candidate cannot report replay-capability checks")

    require(len(unit_ids) == len(set(unit_ids)), "unit_id values must be unique")
    novel: set[str] = set()
    if strict:
        require(manifest["status"] == "sealed", "strict validation requires status=sealed")
        require(50 <= len(units) <= 80, "sealed corpus must contain 50-80 units")
        require(len(frameworks) >= 3 and len(domains) >= 2, "sealed corpus needs >=3 frameworks and >=2 domains")
        require(task_counts["rewrite_validation"] >= 20 and task_counts["optimizer_workload"] >= 6, "sealed corpus task quotas are not met")
        require(replay_denominator > 0, "sealed corpus needs registered replay units for the replay metric")
        require(all(unit["repository"]["commit_sha"] != "0" * 40 for unit in units), "placeholder commit SHA is forbidden")
        require(all(unit["source_binding"]["binding_sha256"] != "0" * 64 and unit["operation_context"]["input_schema_sha256"] != "0" * 64 for unit in units), "placeholder binding/input hash is forbidden")
        placeholders = [s for s in string_values(manifest) if "replace-with" in s.casefold() or "to_be_frozen" in s.casefold()]
        require(not placeholders, "sealed manifest contains placeholder text")
        if registry is None:
            registry = load_json(DEFAULT_REGISTRY)
        contaminated = {normalized_name(str(e.get("name", ""))) for e in registry.get("development_sources", []) if isinstance(e, dict)}
        novel = {f for f in frameworks if not any(normalized_name(f) == c or normalized_name(f) in c or c in normalized_name(f) for c in contaminated if c)}
        require(len(novel) >= policy["minimum_novel_frameworks"], f"only {len(novel)} novel framework(s); need {policy['minimum_novel_frameworks']}")
    return {"benchmark_id": manifest["benchmark_id"], "unit_count": len(units), "framework_count": len(frameworks), "domain_count": len(domains), "task_counts": task_counts, "registered_replay_count": replay_denominator, "novel_framework_count": len(novel), "canonical_sha256": canonical_sha256(manifest), "strict": strict}


def validate_private(oracle: dict[str, Any], public: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    exact_keys(oracle, TOP_PRIVATE, "private oracle")
    require(oracle["schema_version"] == "autocontract.final-oracle.v2", "bad oracle schema_version")
    require(oracle["artifact_type"] == "private_oracle", "bad oracle artifact_type")
    require(oracle["benchmark_id"] == public["benchmark_id"], "oracle benchmark_id mismatch")
    require(oracle["public_manifest_sha256"] == canonical_sha256(public), "oracle public_manifest_sha256 mismatch")
    require(isinstance(oracle["commitment_salt_hex"], str) and HEX64.fullmatch(oracle["commitment_salt_hex"]) and oracle["commitment_salt_hex"] != "0" * 64, "non-placeholder 32-byte salt required")
    annotators = oracle["annotators"]
    require(isinstance(annotators, list) and len(annotators) >= 2, "at least two annotators required")
    ids: set[str] = set(); reviewers: set[str] = set(); roles: set[str] = set()
    for item in annotators:
        item = exact_keys(item, {"annotator_id", "role", "independent_of_analyzer", "conflict_disclosure"}, "annotator")
        require(isinstance(item["annotator_id"], str) and item["annotator_id"] and item["annotator_id"] not in ids, "invalid/duplicate annotator_id")
        require(item["role"] in {"primary", "reviewer", "adjudicator"}, "invalid annotator role")
        require(item["independent_of_analyzer"] is True, "annotator is not independent of analyzer")
        require(isinstance(item["conflict_disclosure"], str), "conflict disclosure required")
        ids.add(item["annotator_id"]); roles.add(item["role"])
        if item["role"] in {"reviewer", "adjudicator"}: reviewers.add(item["annotator_id"])
    require("primary" in roles and "reviewer" in roles, "primary and reviewer roles required")
    public_by_id = {unit["unit_id"]: unit for unit in public["units"]}
    units = oracle["units"]
    require(isinstance(units, list), "oracle units must be an array")
    private_ids = [u.get("unit_id") for u in units if isinstance(u, dict)]
    require(len(private_ids) == len(units) and len(private_ids) == len(set(private_ids)) and set(private_ids) == set(public_by_id), "public/private unit IDs must match exactly")
    unsafe_count = admit_count = replay_count = 0
    expected_keys = {"unit_id", "expected_semantic_decision", "known_unsafe", "coarse_reason", "expected_replay_capability_status", "replay_capability_reason", "effect_labels", "semantic_oracle", "rationale", "confidence", "evidence_anchors", "reviewed_by"}
    for unit in units:
        unit = exact_keys(unit, expected_keys, f"private[{unit.get('unit_id', '?')}]")
        unit_id = unit["unit_id"]
        decision, unsafe, reason = unit["expected_semantic_decision"], unit["known_unsafe"], unit["coarse_reason"]
        require(decision in {"admit", "reject"} and isinstance(unsafe, bool) and reason in COARSE_REASONS, f"{unit_id}: invalid semantic label")
        require(not unsafe or decision == "reject", f"{unit_id}: known unsafe cannot be admitted")
        require((decision == "admit") == (reason == "none"), f"{unit_id}: admit iff coarse_reason is none")
        status = unit["expected_replay_capability_status"]
        cap_reason = unit["replay_capability_reason"]
        require(status in {"supported", "unsupported", "unknown", "not_applicable"} and isinstance(cap_reason, str) and len(cap_reason) >= 4, f"{unit_id}: invalid replay capability label")
        is_replay = public_by_id[unit_id]["candidate"]["kind"] == "registered_parameter_replay"
        if is_replay:
            require(status in {"supported", "unsupported", "unknown"} and cap_reason != "not_applicable", f"{unit_id}: replay unit needs an applicable capability label")
            replay_count += 1
        else:
            require(status == "not_applicable" and cap_reason == "not_applicable", f"{unit_id}: non-replay unit must be not_applicable")
        semantic = unit["semantic_oracle"]
        require(isinstance(semantic, dict) and set(semantic) == {"output", "rng", "gradient", "lineage", "diversity"}, f"{unit_id}: incomplete semantic_oracle")
        require(isinstance(unit["rationale"], str) and len(unit["rationale"]) >= 10, f"{unit_id}: rationale too short")
        require(unit["confidence"] in {"high", "medium", "low"}, f"{unit_id}: invalid confidence")
        require(isinstance(unit["evidence_anchors"], list) and unit["evidence_anchors"], f"{unit_id}: evidence anchors required")
        require(isinstance(unit["reviewed_by"], list) and set(unit["reviewed_by"]) <= ids and set(unit["reviewed_by"]) & reviewers, f"{unit_id}: independent review required")
        unsafe_count += int(unsafe); admit_count += int(decision == "admit")
    adjudication = exact_keys(oracle["adjudication"], {"status", "disagreement_count", "record_path"}, "adjudication")
    if strict:
        require(adjudication["status"] == "complete" and isinstance(adjudication["disagreement_count"], int), "adjudication must be complete")
    return {"benchmark_id": oracle["benchmark_id"], "unit_count": len(units), "known_unsafe_count_private": unsafe_count, "admit_count_private": admit_count, "registered_replay_count_private": replay_count, "canonical_sha256": canonical_sha256(oracle)}


def validate_commitment(value: dict[str, Any]) -> None:
    exact_keys(value, {"schema_version", "artifact_type", "benchmark_id", "public_manifest_sha256", "oracle_commitment_sha256", "unit_count"}, "commitment")
    require(value["schema_version"] == "autocontract.oracle-commitment.v2" and value["artifact_type"] == "private_oracle_commitment", "bad commitment type/version")
    require(isinstance(value["public_manifest_sha256"], str) and HEX64.fullmatch(value["public_manifest_sha256"]), "bad public hash")
    require(isinstance(value["oracle_commitment_sha256"], str) and HEX64.fullmatch(value["oracle_commitment_sha256"]), "bad oracle hash")
    require(isinstance(value["unit_count"], int) and value["unit_count"] > 0, "bad unit_count")


def build_commitment(oracle_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    public, oracle = load_json(public_path), load_json(oracle_path)
    validate_public(public, strict=True); summary = validate_private(oracle, public, strict=True)
    value = {"schema_version": "autocontract.oracle-commitment.v2", "artifact_type": "private_oracle_commitment", "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public), "oracle_commitment_sha256": oracle_commitment_sha256(oracle), "unit_count": summary["unit_count"]}
    write_json(output_path, value)
    return value


def verify_oracle(oracle_path: Path, public_path: Path, commitment_path: Path) -> dict[str, Any]:
    public, oracle, commitment = load_json(public_path), load_json(oracle_path), load_json(commitment_path)
    validate_public(public, strict=True); validate_private(oracle, public, strict=True); validate_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"], "commitment benchmark_id mismatch")
    require(commitment["public_manifest_sha256"] == canonical_sha256(public), "public manifest changed after commitment")
    require(commitment["oracle_commitment_sha256"] == oracle_commitment_sha256(oracle), "private oracle changed after commitment")
    require(commitment["unit_count"] == len(public["units"]), "commitment unit_count mismatch")
    return {"verified": True, "benchmark_id": public["benchmark_id"], "unit_count": len(public["units"]), "public_manifest_sha256": commitment["public_manifest_sha256"], "oracle_commitment_sha256": commitment["oracle_commitment_sha256"]}


def declared_artifacts(public: dict[str, Any]) -> list[dict[str, str]]:
    bundle = public["analyzer_bundle"]
    return [bundle["systems"][name] for name in ("effect", "replay_capability", "source_index")] + [bundle["runner"]] + list(bundle["adapters"]) + list(bundle["schemas"])


def resolve_artifact(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def seal_bundle(public_path: Path, commitment_path: Path, output_path: Path) -> dict[str, Any]:
    public, commitment = load_json(public_path), load_json(commitment_path)
    summary = validate_public(public, strict=True); validate_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"] and commitment["public_manifest_sha256"] == canonical_sha256(public) and commitment["unit_count"] == len(public["units"]), "commitment does not bind this public manifest")
    frozen = []
    for artifact in declared_artifacts(public):
        path = resolve_artifact(artifact["path"])
        require(path.is_file(), f"declared artifact does not exist: {path}")
        observed = file_sha256(path)
        require(observed == artifact["sha256"], f"declared artifact hash mismatch: {artifact['path']}")
        frozen.append({"path": artifact["path"], "file_sha256": observed})
    freeze = {"schema_version": "autocontract.final-freeze.v2", "artifact_type": "final_public_execution_freeze", "benchmark_id": public["benchmark_id"], "claim_boundary": "Public execution bundle only; private oracle path and contents are excluded.", "public_manifest": {"path": str(public_path), "canonical_sha256": canonical_sha256(public), "file_sha256": file_sha256(public_path)}, "oracle_commitment": {"path": str(commitment_path), "canonical_sha256": canonical_sha256(commitment), "file_sha256": file_sha256(commitment_path)}, "artifacts": frozen, "metric_gates": REQUIRED_GATES, "public_summary": summary}
    write_json(output_path, freeze)
    return freeze


def fixture_artifact(path: str, *, name: str | None = None) -> dict[str, str]:
    value = {"path": path, "sha256": file_sha256(ROOT / path)}
    if name is not None: value["name"] = name
    return value


def make_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for index in range(60):
        if index < 30: task_type, kind = "contract_inference", "none"
        elif index < 42: task_type, kind = "rewrite_validation", "registered_parameter_replay"
        elif index < 48: task_type, kind = "rewrite_validation", "cache_prefix"
        elif index < 54: task_type, kind = "rewrite_validation", "adjacent_swap"
        else: task_type, kind = "optimizer_workload", ("registered_parameter_replay" if index % 2 == 0 else "cache_prefix")
        mechanism = "stored_parameter_record" if kind == "registered_parameter_replay" else "none"
        operands = ([{"name": "sample", "role": "primary_input"}, {"name": "params", "role": "parameter_record"}] if mechanism != "none" else [])
        units.append({
            "unit_id": f"fixture-unit-{index:03d}", "task_type": task_type, "split": "final_blind",
            "framework": ("NovelFrameA", "NovelFrameB", "NovelFrameC")[index % 3], "domain": ("vision", "audio")[index % 2],
            "repository": {"url": f"https://github.com/example/repository-{index % 3}", "release": "v1.0.0", "commit_sha": hashlib.sha1(f"commit-{index}".encode()).hexdigest()},
            "source_binding": {"path": f"package/source_{index}.py", "public_symbol": f"package.Transform{index}", "binding_sha256": hashlib.sha256(f"binding-{index}".encode()).hexdigest()},
            "operation_context": {"configuration": {"fixture": index}, "operation": ("replay_apply" if kind == "registered_parameter_replay" else "contract_inference" if kind == "none" else "cache_write" if kind == "cache_prefix" else "adjacent_reorder"), "lifecycle_phase": "iteration", "named_modes": ["training"], "assumptions": ["synthetic administrative fixture"], "input_schema_sha256": hashlib.sha256(f"schema-{index}".encode()).hexdigest()},
            "candidate": {"kind": kind, "operators": [f"package.Transform{index}"], "cost_profile_id": f"profile-{index:03d}"},
            "contract_plan": {
                "semantic": {"analyzer_entrypoint": "analyze_effect_v7", "required_effect_dimensions": ["rng", "state", "lineage", "targets"]},
                "replay_capability": {"mechanism": mechanism, "required_checks": sorted(REPLAY_CHECKS[mechanism]), "lineage_operands": operands, "target_dependent_operands": (["sample"] if mechanism != "none" else [])},
                "source_index": {"schema_version": "autocontract.executable-source-index.v1", "binding_components": [{"name": "root", "callable_slots": ["__call__"]}], "unknown_policy": "fail_closed"},
            },
            "verification_plan": {"output_checks": ["paired output trace"], "effect_checks": ["paired effect trace"], "replay_capability_checks": (["validate ReplayCapabilityV1 receipt"] if kind == "registered_parameter_replay" else []), "source_checks": ["recompute source index"], "performance_checks": ["paired latency profile"]},
        })
    admin = "experiments/autocontract_final_benchmark_admin_v2.py"
    public = {
        "schema_version": "autocontract.final-public.v2", "artifact_type": "public_manifest", "benchmark_id": "autocontract-final-v2-selftest", "status": "sealed", "created_at": "2026-07-30T00:00:00Z", "selection_author": "synthetic-self-test", "claim_scope": "Administrative self-test only; no benchmark accuracy or system-performance evidence.",
        "analyzer_bundle": {"systems": {"effect": fixture_artifact("experiments/autocontract_h7h_effect_v7.py", name="EffectV7"), "replay_capability": fixture_artifact("experiments/autocontract_replay_capability_v1.py", name="ReplayCapabilityV1"), "source_index": fixture_artifact("experiments/autocontract_r3_source_index_v1.py", name="ExecutableSourceIndexV1")}, "runner": fixture_artifact(admin), "adapters": [fixture_artifact("experiments/autocontract_h7_adapters.py")], "schemas": [fixture_artifact("benchmark/final_v2/public_manifest.schema.json"), fixture_artifact("benchmark/final_v2/private_oracle.schema.json"), fixture_artifact("benchmark/final_v1/replay_capability_v1.schema.json")]},
        "contamination_policy": {"registry_path": "benchmark/final_v1/contamination_registry.json", "selection_cutoff": "2026-07-30T00:00:00Z", "minimum_novel_frameworks": 3}, "metric_gates": REQUIRED_GATES, "units": units,
    }
    oracle_units = []
    for index, unit in enumerate(units):
        reject = index % 3 == 0
        is_replay = unit["candidate"]["kind"] == "registered_parameter_replay"
        oracle_units.append({"unit_id": unit["unit_id"], "expected_semantic_decision": "reject" if reject else "admit", "known_unsafe": reject, "coarse_reason": "hidden_rng_effect" if reject else "none", "expected_replay_capability_status": ("supported" if is_replay and index % 2 == 0 else "unknown" if is_replay else "not_applicable"), "replay_capability_reason": ("synthetic_supported" if is_replay and index % 2 == 0 else "synthetic_unknown" if is_replay else "not_applicable"), "effect_labels": {"randomness": "present" if reject else "absent"}, "semantic_oracle": {"output": "fixture", "rng": "fixture", "gradient": "fixture", "lineage": "fixture", "diversity": "fixture"}, "rationale": "Synthetic self-test rationale only.", "confidence": "high", "evidence_anchors": [f"fixture:{index}"], "reviewed_by": ["reviewer-01"]})
    oracle = {"schema_version": "autocontract.final-oracle.v2", "artifact_type": "private_oracle", "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public), "commitment_salt_hex": hashlib.sha256(b"v2-synthetic-self-test-salt").hexdigest(), "annotators": [{"annotator_id": "primary-01", "role": "primary", "independent_of_analyzer": True, "conflict_disclosure": "synthetic fixture"}, {"annotator_id": "reviewer-01", "role": "reviewer", "independent_of_analyzer": True, "conflict_disclosure": "synthetic fixture"}], "units": oracle_units, "adjudication": {"status": "complete", "disagreement_count": 0, "record_path": "synthetic-fixture"}}
    return public, oracle


def expect_failure(name: str, action: Any, checks: list[dict[str, Any]]) -> None:
    try: action()
    except ValidationError as exc: checks.append({"name": name, "passed": True, "observed": str(exc)})
    else: checks.append({"name": name, "passed": False, "observed": "unexpected acceptance"})


def run_self_test(output_path: Path | None) -> dict[str, Any]:
    public, oracle = make_fixture(); checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="autocontract-final-v2-") as directory:
        temp = Path(directory); public_path = temp / "public.json"; oracle_path = temp / "oracle.json"; commitment_path = temp / "commitment.json"; freeze_path = temp / "freeze.json"
        write_json(public_path, public); write_json(oracle_path, oracle)
        checks.append({"name": "strict public accepted", "passed": validate_public(public, strict=True)["unit_count"] == 60})
        checks.append({"name": "strict private accepted", "passed": validate_private(oracle, public)["unit_count"] == 60})
        build_commitment(oracle_path, public_path, commitment_path); checks.append({"name": "salted commitment created", "passed": commitment_path.is_file()})
        checks.append({"name": "untampered oracle verified", "passed": verify_oracle(oracle_path, public_path, commitment_path)["verified"]})
        leaked = copy.deepcopy(public); leaked["units"][0]["expected_semantic_decision"] = "admit"; expect_failure("public semantic label leak rejected", lambda: validate_public(leaked, strict=True), checks)
        leaked = copy.deepcopy(public); leaked["units"][0]["final_status"] = "admit"; expect_failure("public outcome leak rejected", lambda: validate_public(leaked, strict=True), checks)
        broken = copy.deepcopy(public); del broken["units"][0]["operation_context"]["operation"]; expect_failure("missing exact operation rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["units"][30]["contract_plan"]["replay_capability"]["required_checks"] = ["exact_replay"]; expect_failure("mechanism/check mismatch rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["units"][30]["contract_plan"]["replay_capability"]["lineage_operands"] = [{"name": "sample", "role": "primary_input"}]; expect_failure("stored replay missing parameter record rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["units"][30]["contract_plan"]["replay_capability"]["target_dependent_operands"] = ["mask"]; expect_failure("unbound target operand rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["units"][0]["contract_plan"]["source_index"]["binding_components"] = []; expect_failure("empty source component rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["units"][0]["contract_plan"]["source_index"]["unknown_policy"] = "admit"; expect_failure("non-fail-closed source policy rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["analyzer_bundle"]["runner"]["sha256"] = "0" * 64; expect_failure("placeholder artifact hash rejected", lambda: validate_public(broken, strict=True), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"].pop(); expect_failure("public/private mismatch rejected", lambda: validate_private(broken_oracle, public), checks)
        tampered = copy.deepcopy(oracle); tampered["units"][0]["rationale"] += " tampered"; tampered_path = temp / "tampered.json"; write_json(tampered_path, tampered); expect_failure("post-commit private tampering rejected", lambda: verify_oracle(tampered_path, public_path, commitment_path), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"][0]["expected_replay_capability_status"] = "unknown"; broken_oracle["units"][0]["replay_capability_reason"] = "unknown"; expect_failure("non-replay capability label rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); replay_index = next(i for i, u in enumerate(public["units"]) if u["candidate"]["kind"] == "registered_parameter_replay"); broken_oracle["units"][replay_index]["expected_replay_capability_status"] = "not_applicable"; broken_oracle["units"][replay_index]["replay_capability_reason"] = "not_applicable"; expect_failure("replay not-applicable label rejected", lambda: validate_private(broken_oracle, public), checks)
        broken = copy.deepcopy(public); cache_index = next(i for i, u in enumerate(public["units"]) if u["candidate"]["kind"] == "cache_prefix"); broken["units"][cache_index]["contract_plan"]["replay_capability"] = copy.deepcopy(public["units"][30]["contract_plan"]["replay_capability"]); broken["units"][cache_index]["verification_plan"]["replay_capability_checks"] = ["receipt"]; expect_failure("cache cannot claim ReplayCapabilityV1 rejected", lambda: validate_public(broken, strict=True), checks)
        seal_bundle(public_path, commitment_path, freeze_path); freeze = load_json(freeze_path)
        declared = declared_artifacts(public)
        checks.append({"name": "all declared artifacts frozen", "passed": len(freeze["artifacts"]) == len(declared) and {a["path"] for a in freeze["artifacts"]} == {a["path"] for a in declared}})
        freeze_text = json.dumps(freeze)
        checks.append({"name": "freeze excludes private oracle instance path", "passed": str(oracle_path) not in freeze_text and "private_oracle_path" not in freeze_text and "private_oracle_instance" not in freeze_text})
    result = {"schema_version": "autocontract.final-handoff-selftest.v2", "status": "pass" if all(c["passed"] for c in checks) else "fail", "passed": sum(bool(c["passed"]) for c in checks), "total": len(checks), "checks": checks, "note": "Synthetic administrative fixture only; not benchmark evidence."}
    if output_path: write_json(output_path, result)
    return result


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("self-test"); command.add_argument("--output", type=Path)
    command = sub.add_parser("validate-public"); command.add_argument("public", type=Path); command.add_argument("--strict", action="store_true"); command.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    command = sub.add_parser("commit-oracle"); command.add_argument("private_oracle", type=Path); command.add_argument("public", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("verify-oracle"); command.add_argument("private_oracle", type=Path); command.add_argument("public", type=Path); command.add_argument("commitment", type=Path)
    command = sub.add_parser("seal"); command.add_argument("public", type=Path); command.add_argument("commitment", type=Path); command.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "self-test": result = run_self_test(args.output)
        elif args.command == "validate-public": result = validate_public(load_json(args.public), strict=args.strict, registry=load_json(args.registry) if args.strict else None)
        elif args.command == "commit-oracle": result = build_commitment(args.private_oracle, args.public, args.output)
        elif args.command == "verify-oracle": result = verify_oracle(args.private_oracle, args.public, args.commitment)
        elif args.command == "seal": result = seal_bundle(args.public, args.commitment, args.output)
        else: raise AssertionError(args.command)
    except ValidationError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2)); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    sys.exit(main())
