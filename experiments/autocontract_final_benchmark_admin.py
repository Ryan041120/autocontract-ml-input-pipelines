#!/usr/bin/env python3
"""Administrative guardrails for the AutoContract final blind benchmark.

This tool deliberately does not score predictions.  Its job is to keep public
inputs, private labels, cryptographic commitments, and the frozen execution
bundle separate before a one-shot evaluation.
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

# Exact key matching avoids rejecting legitimate public metric names such as
# oracle_benefit_coverage_min while still preventing answer-bearing fields.
FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "coarse_reason",
    "confidence",
    "decision",
    "effect_labels",
    "expected_decision",
    "expected_effects",
    "expected_output",
    "expected_reason",
    "gold",
    "ground_truth",
    "is_safe",
    "is_unsafe",
    "known_unsafe",
    "label",
    "labels",
    "oracle",
    "outcome",
    "rationale",
    "reference_answer",
    "safe",
    "semantic_oracle",
    "target_decision",
    "unsafe",
    "verdict",
}

REQUIRED_GATES = {
    "known_unsafe_false_accepts_max": 0,
    "safe_recall_min": 0.8,
    "coarse_reason_accuracy_min": 0.9,
    "analyzer_coverage_min": 0.9,
    "oracle_benefit_coverage_min": 0.9,
}

COARSE_REASONS = {
    "none",
    "hidden_rng_effect",
    "external_state_drift",
    "state_mutation",
    "mode_dependent_effect",
    "lineage_or_binding_mismatch",
    "augmentation_diversity_frozen",
    "gradient_or_autograd_change",
    "unsupported_or_ambiguous",
}


class ValidationError(ValueError):
    """Raised when an artifact violates the final-benchmark protocol."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def oracle_commitment_sha256(oracle: dict[str, Any]) -> str:
    """Domain-separated digest; the required random salt lives in oracle."""
    payload = b"autocontract.final-oracle.v1\0" + canonical_bytes(oracle)
    return hashlib.sha256(payload).hexdigest()


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
    if not isinstance(value, dict):
        raise ValidationError(f"top-level JSON must be an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def find_forbidden_keys(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if key.lower() in FORBIDDEN_PUBLIC_KEYS:
                findings.append(child_path)
            findings.extend(find_forbidden_keys(child, child_path))
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


def validate_public(
    manifest: dict[str, Any], *, strict: bool = False, registry: dict[str, Any] | None = None
) -> dict[str, Any]:
    require(manifest.get("schema_version") == "autocontract.final-public.v1", "bad public schema_version")
    require(manifest.get("artifact_type") == "public_manifest", "bad public artifact_type")
    require(isinstance(manifest.get("benchmark_id"), str), "benchmark_id is required")
    require(manifest.get("status") in {"draft", "sealed"}, "status must be draft or sealed")
    require(isinstance(manifest.get("created_at"), str) and manifest["created_at"], "created_at is required")
    require(isinstance(manifest.get("selection_author"), str) and manifest["selection_author"], "selection_author is required")
    require(isinstance(manifest.get("claim_scope"), str) and len(manifest["claim_scope"]) >= 20, "claim_scope is too short")

    analyzer = manifest.get("analyzer_bundle")
    require(isinstance(analyzer, dict), "analyzer_bundle must be an object")
    require(isinstance(analyzer.get("effect_system"), str) and analyzer["effect_system"], "effect_system is required")
    require(isinstance(analyzer.get("optimizer_policy"), str) and analyzer["optimizer_policy"], "optimizer_policy is required")
    require(isinstance(analyzer.get("runner_path"), str) and analyzer["runner_path"], "runner_path is required")
    require(isinstance(analyzer.get("adapter_paths"), list) and analyzer["adapter_paths"], "adapter_paths are required")
    require(all(isinstance(path, str) and path for path in analyzer["adapter_paths"]), "adapter_paths must be non-empty strings")

    leaked = find_forbidden_keys(manifest)
    require(not leaked, "answer-bearing key(s) in public manifest: " + ", ".join(leaked))

    gates = manifest.get("metric_gates")
    require(isinstance(gates, dict), "metric_gates must be an object")
    require(gates == REQUIRED_GATES, f"metric_gates must remain frozen at {REQUIRED_GATES}")

    policy = manifest.get("contamination_policy")
    require(isinstance(policy, dict), "contamination_policy must be an object")
    require(isinstance(policy.get("registry_path"), str) and policy["registry_path"], "registry_path is required")
    require(isinstance(policy.get("selection_cutoff"), str) and policy["selection_cutoff"], "selection_cutoff is required")
    require(int(policy.get("minimum_novel_frameworks", 0)) >= 1, "at least one novel framework is required")

    units = manifest.get("units")
    require(isinstance(units, list) and units, "units must be a non-empty array")
    unit_ids: list[str] = []
    frameworks: set[str] = set()
    domains: set[str] = set()
    task_counts = {"contract_inference": 0, "rewrite_validation": 0, "optimizer_workload": 0}

    for index, unit in enumerate(units):
        where = f"units[{index}]"
        require(isinstance(unit, dict), f"{where} must be an object")
        unit_id = unit.get("unit_id")
        require(isinstance(unit_id, str) and ID_PATTERN.fullmatch(unit_id) is not None, f"{where}.unit_id is invalid")
        unit_ids.append(unit_id)
        require(unit.get("split") == "final_blind", f"{unit_id}: split must be final_blind")
        task_type = unit.get("task_type")
        require(task_type in task_counts, f"{unit_id}: invalid task_type")
        task_counts[task_type] += 1
        framework = unit.get("framework")
        domain = unit.get("domain")
        require(isinstance(framework, str) and framework.strip(), f"{unit_id}: framework is required")
        require(isinstance(domain, str) and domain.strip(), f"{unit_id}: domain is required")
        frameworks.add(framework.casefold())
        domains.add(domain.casefold())

        repository = unit.get("repository")
        require(isinstance(repository, dict), f"{unit_id}: repository must be an object")
        require(str(repository.get("url", "")).startswith("https://"), f"{unit_id}: repository URL must use https")
        require(isinstance(repository.get("release"), str) and repository["release"], f"{unit_id}: release is required")
        commit = repository.get("commit_sha")
        require(isinstance(commit, str) and HEX40.fullmatch(commit) is not None, f"{unit_id}: commit_sha must be 40 lowercase hex characters")

        binding = unit.get("source_binding")
        require(isinstance(binding, dict), f"{unit_id}: source_binding must be an object")
        require(bool(binding.get("path")) and bool(binding.get("public_symbol")), f"{unit_id}: incomplete source binding")
        binding_hash = binding.get("binding_sha256")
        require(isinstance(binding_hash, str) and HEX64.fullmatch(binding_hash) is not None, f"{unit_id}: binding_sha256 must be 64 lowercase hex characters")

        context = unit.get("context")
        require(isinstance(context, dict), f"{unit_id}: context must be an object")
        require(isinstance(context.get("configuration"), dict), f"{unit_id}: configuration must be an object")
        require(context.get("phase") in {"construction", "iteration", "training", "evaluation", "serving"}, f"{unit_id}: invalid phase")
        require(isinstance(context.get("named_modes"), list), f"{unit_id}: named_modes must be an array")
        require(isinstance(context.get("assumptions"), list), f"{unit_id}: assumptions must be an array")
        candidate = unit.get("candidate")
        require(isinstance(candidate, dict), f"{unit_id}: candidate must be an object")
        require(candidate.get("kind") in {"none", "cache_prefix", "registered_parameter_replay", "adjacent_swap"}, f"{unit_id}: invalid candidate kind")
        require(isinstance(candidate.get("operators"), list), f"{unit_id}: candidate operators must be an array")
        verification = unit.get("verification_plan")
        require(isinstance(verification, dict), f"{unit_id}: verification_plan must be an object")
        for check_name in ("output_checks", "effect_checks", "performance_checks"):
            require(isinstance(verification.get(check_name), list), f"{unit_id}: missing {check_name}")

    require(len(unit_ids) == len(set(unit_ids)), "unit_id values must be unique")

    if strict:
        require(manifest.get("status") == "sealed", "strict validation requires status=sealed")
        require(50 <= len(units) <= 80, "sealed corpus must contain 50-80 units")
        require(len(frameworks) >= 3, "sealed corpus must contain at least 3 frameworks")
        require(len(domains) >= 2, "sealed corpus must contain at least 2 domains")
        require(task_counts["rewrite_validation"] >= 20, "sealed corpus needs at least 20 rewrite_validation units")
        require(task_counts["optimizer_workload"] >= 6, "sealed corpus needs at least 6 optimizer_workload units")
        require(all(unit["repository"]["commit_sha"] != "0" * 40 for unit in units), "placeholder commit SHA is forbidden")
        require(all(unit["source_binding"]["binding_sha256"] != "0" * 64 for unit in units), "placeholder binding hash is forbidden")
        placeholders = [text for text in string_values(manifest) if "replace-with" in text.lower() or "to_be_frozen" in text.lower()]
        require(not placeholders, "sealed manifest contains placeholder text")

        if registry is None:
            registry = load_json(DEFAULT_REGISTRY)
        contaminated = {
            normalized_name(str(entry.get("name", "")))
            for entry in registry.get("development_sources", [])
            if isinstance(entry, dict)
        }
        novel = {
            framework
            for framework in frameworks
            if not any(
                normalized_name(framework) == contaminated_name
                or normalized_name(framework) in contaminated_name
                or contaminated_name in normalized_name(framework)
                for contaminated_name in contaminated
                if contaminated_name
            )
        }
        minimum_novel = int(policy["minimum_novel_frameworks"])
        require(len(novel) >= minimum_novel, f"only {len(novel)} novel framework(s); need {minimum_novel}")
    else:
        novel = set()

    return {
        "benchmark_id": manifest["benchmark_id"],
        "unit_count": len(units),
        "framework_count": len(frameworks),
        "domain_count": len(domains),
        "task_counts": task_counts,
        "novel_framework_count": len(novel),
        "canonical_sha256": canonical_sha256(manifest),
        "strict": strict,
    }


def validate_private(
    oracle: dict[str, Any], public: dict[str, Any], *, strict: bool = True
) -> dict[str, Any]:
    require(oracle.get("schema_version") == "autocontract.final-oracle.v1", "bad oracle schema_version")
    require(oracle.get("artifact_type") == "private_oracle", "bad oracle artifact_type")
    require(oracle.get("benchmark_id") == public.get("benchmark_id"), "oracle benchmark_id does not match public manifest")
    public_hash = canonical_sha256(public)
    require(oracle.get("public_manifest_sha256") == public_hash, "oracle public_manifest_sha256 does not match")
    salt = oracle.get("commitment_salt_hex")
    require(isinstance(salt, str) and HEX64.fullmatch(salt) is not None and salt != "0" * 64, "oracle needs a non-placeholder 32-byte salt")

    annotators = oracle.get("annotators")
    require(isinstance(annotators, list) and len(annotators) >= 2, "at least two annotators are required")
    annotator_ids: set[str] = set()
    reviewer_ids: set[str] = set()
    roles: set[str] = set()
    for annotator in annotators:
        require(isinstance(annotator, dict), "annotator entries must be objects")
        annotator_id = annotator.get("annotator_id")
        role = annotator.get("role")
        require(isinstance(annotator_id, str) and annotator_id, "annotator_id is required")
        require(annotator_id not in annotator_ids, "annotator_id values must be unique")
        require(role in {"primary", "reviewer", "adjudicator"}, f"invalid role for {annotator_id}")
        require(annotator.get("independent_of_analyzer") is True, f"{annotator_id} is not independent of analyzer")
        require("conflict_disclosure" in annotator, f"{annotator_id} lacks conflict disclosure")
        annotator_ids.add(annotator_id)
        roles.add(role)
        if role in {"reviewer", "adjudicator"}:
            reviewer_ids.add(annotator_id)
    require("primary" in roles and "reviewer" in roles, "primary and reviewer roles are both required")

    public_ids = [unit["unit_id"] for unit in public.get("units", [])]
    units = oracle.get("units")
    require(isinstance(units, list), "oracle units must be an array")
    private_ids = [unit.get("unit_id") for unit in units if isinstance(unit, dict)]
    require(len(private_ids) == len(units), "oracle unit entries must be objects")
    require(len(private_ids) == len(set(private_ids)), "oracle unit_id values must be unique")
    require(set(private_ids) == set(public_ids) and len(private_ids) == len(public_ids), "oracle and public unit IDs must match exactly")

    unsafe_count = 0
    admit_count = 0
    for unit in units:
        unit_id = unit["unit_id"]
        decision = unit.get("expected_decision")
        unsafe = unit.get("known_unsafe")
        reason = unit.get("coarse_reason")
        require(decision in {"admit", "reject"}, f"{unit_id}: invalid expected_decision")
        require(isinstance(unsafe, bool), f"{unit_id}: known_unsafe must be boolean")
        require(reason in COARSE_REASONS, f"{unit_id}: invalid coarse_reason")
        require(not unsafe or decision == "reject", f"{unit_id}: known unsafe unit cannot be admitted")
        require((decision == "admit") == (reason == "none"), f"{unit_id}: admit iff coarse_reason is none")
        require(not (decision == "reject" and reason == "none"), f"{unit_id}: rejected unit needs a reason")
        semantic = unit.get("semantic_oracle")
        require(isinstance(semantic, dict), f"{unit_id}: semantic_oracle is required")
        require(set(semantic) == {"output", "rng", "gradient", "lineage", "diversity"}, f"{unit_id}: incomplete semantic_oracle")
        require(isinstance(unit.get("rationale"), str) and len(unit["rationale"]) >= 10, f"{unit_id}: rationale is too short")
        require(unit.get("confidence") in {"high", "medium", "low"}, f"{unit_id}: invalid confidence")
        anchors = unit.get("evidence_anchors")
        require(isinstance(anchors, list) and anchors, f"{unit_id}: evidence anchors are required")
        reviewed_by = unit.get("reviewed_by")
        require(isinstance(reviewed_by, list) and set(reviewed_by) & reviewer_ids, f"{unit_id}: independent review is required")
        require(set(reviewed_by) <= annotator_ids, f"{unit_id}: unknown reviewer ID")
        unsafe_count += int(unsafe)
        admit_count += int(decision == "admit")

    adjudication = oracle.get("adjudication")
    require(isinstance(adjudication, dict), "adjudication must be an object")
    if strict:
        require(adjudication.get("status") == "complete", "adjudication must be complete before commitment")
        require(isinstance(adjudication.get("disagreement_count"), int), "disagreement_count must be an integer")

    return {
        "benchmark_id": oracle["benchmark_id"],
        "unit_count": len(units),
        "known_unsafe_count_private": unsafe_count,
        "admit_count_private": admit_count,
        "canonical_sha256": canonical_sha256(oracle),
    }


def build_commitment(
    oracle_path: Path, public_path: Path, output_path: Path
) -> dict[str, Any]:
    public = load_json(public_path)
    validate_public(public, strict=True)
    oracle = load_json(oracle_path)
    private_summary = validate_private(oracle, public, strict=True)
    commitment = {
        "schema_version": "autocontract.oracle-commitment.v1",
        "artifact_type": "private_oracle_commitment",
        "benchmark_id": public["benchmark_id"],
        "public_manifest_sha256": canonical_sha256(public),
        "oracle_commitment_sha256": oracle_commitment_sha256(oracle),
        "unit_count": private_summary["unit_count"],
    }
    write_json(output_path, commitment)
    return commitment


def validate_commitment(commitment: dict[str, Any]) -> None:
    require(commitment.get("schema_version") == "autocontract.oracle-commitment.v1", "bad commitment schema_version")
    require(commitment.get("artifact_type") == "private_oracle_commitment", "bad commitment artifact_type")
    require(isinstance(commitment.get("benchmark_id"), str), "commitment benchmark_id is required")
    require(isinstance(commitment.get("public_manifest_sha256"), str) and HEX64.fullmatch(commitment["public_manifest_sha256"]) is not None, "bad public manifest hash")
    require(isinstance(commitment.get("oracle_commitment_sha256"), str) and HEX64.fullmatch(commitment["oracle_commitment_sha256"]) is not None, "bad oracle commitment hash")
    require(isinstance(commitment.get("unit_count"), int) and commitment["unit_count"] > 0, "bad commitment unit_count")


def verify_oracle(
    oracle_path: Path, public_path: Path, commitment_path: Path
) -> dict[str, Any]:
    public = load_json(public_path)
    validate_public(public, strict=True)
    oracle = load_json(oracle_path)
    validate_private(oracle, public, strict=True)
    commitment = load_json(commitment_path)
    validate_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"], "commitment benchmark_id mismatch")
    require(commitment["public_manifest_sha256"] == canonical_sha256(public), "public manifest changed after commitment")
    require(commitment["oracle_commitment_sha256"] == oracle_commitment_sha256(oracle), "private oracle changed after commitment")
    require(commitment["unit_count"] == len(public["units"]), "commitment unit_count mismatch")
    return {
        "verified": True,
        "benchmark_id": public["benchmark_id"],
        "unit_count": len(public["units"]),
        "public_manifest_sha256": commitment["public_manifest_sha256"],
        "oracle_commitment_sha256": commitment["oracle_commitment_sha256"],
    }


def seal_bundle(
    public_path: Path,
    commitment_path: Path,
    runner_path: Path,
    adapter_paths: list[Path],
    output_path: Path,
) -> dict[str, Any]:
    public = load_json(public_path)
    summary = validate_public(public, strict=True)
    commitment = load_json(commitment_path)
    validate_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"], "commitment benchmark_id mismatch")
    require(commitment["public_manifest_sha256"] == canonical_sha256(public), "commitment is for another public manifest")
    require(commitment["unit_count"] == len(public["units"]), "commitment unit_count mismatch")
    require(runner_path.is_file(), f"runner does not exist: {runner_path}")
    require(adapter_paths, "at least one adapter must be frozen")
    for adapter in adapter_paths:
        require(adapter.is_file(), f"adapter does not exist: {adapter}")
    declared_runner = Path(public["analyzer_bundle"]["runner_path"])
    if not declared_runner.is_absolute():
        declared_runner = ROOT / declared_runner
    require(declared_runner.resolve() == runner_path.resolve(), "runner does not match analyzer_bundle.runner_path")
    declared_adapters = []
    for declared in public["analyzer_bundle"]["adapter_paths"]:
        path = Path(declared)
        declared_adapters.append((ROOT / path if not path.is_absolute() else path).resolve())
    require(
        set(declared_adapters) == {path.resolve() for path in adapter_paths},
        "adapters do not match analyzer_bundle.adapter_paths",
    )

    freeze = {
        "schema_version": "autocontract.final-freeze.v1",
        "artifact_type": "final_public_execution_freeze",
        "benchmark_id": public["benchmark_id"],
        "claim_boundary": "Public execution bundle only; private oracle was not read while sealing.",
        "public_manifest": {
            "path": str(public_path),
            "canonical_sha256": canonical_sha256(public),
            "file_sha256": file_sha256(public_path),
        },
        "oracle_commitment": {
            "path": str(commitment_path),
            "canonical_sha256": canonical_sha256(commitment),
            "file_sha256": file_sha256(commitment_path),
        },
        "runner": {"path": str(runner_path), "file_sha256": file_sha256(runner_path)},
        "adapters": [
            {"path": str(path), "file_sha256": file_sha256(path)} for path in adapter_paths
        ],
        "metric_gates": REQUIRED_GATES,
        "public_summary": summary,
    }
    write_json(output_path, freeze)
    return freeze


def make_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for index in range(60):
        unit_id = f"fixture-unit-{index:03d}"
        if index < 30:
            task_type = "contract_inference"
            kind = "none"
        elif index < 54:
            task_type = "rewrite_validation"
            kind = "cache_prefix"
        else:
            task_type = "optimizer_workload"
            kind = "registered_parameter_replay"
        units.append(
            {
                "unit_id": unit_id,
                "task_type": task_type,
                "split": "final_blind",
                "framework": ("NovelFrameA", "NovelFrameB", "NovelFrameC")[index % 3],
                "domain": ("vision", "audio")[index % 2],
                "repository": {
                    "url": f"https://github.com/example/repository-{index % 3}",
                    "release": "v1.0.0",
                    "commit_sha": hashlib.sha1(f"commit-{index}".encode()).hexdigest(),
                },
                "source_binding": {
                    "path": f"package/source_{index}.py",
                    "public_symbol": f"package.Transform{index}",
                    "binding_sha256": hashlib.sha256(f"binding-{index}".encode()).hexdigest(),
                },
                "context": {
                    "configuration": {"fixture": index},
                    "phase": "iteration",
                    "named_modes": ["training"],
                    "assumptions": ["fixture-only; not a benchmark label"],
                },
                "candidate": {
                    "kind": kind,
                    "operators": [f"package.Transform{index}"],
                    "cost_profile_id": f"profile-{index:03d}",
                },
                "verification_plan": {
                    "output_checks": ["paired output trace"],
                    "effect_checks": ["paired effect trace"],
                    "performance_checks": ["paired latency profile"],
                },
            }
        )

    public = {
        "schema_version": "autocontract.final-public.v1",
        "artifact_type": "public_manifest",
        "benchmark_id": "autocontract-final-v1-selftest",
        "status": "sealed",
        "created_at": "2026-07-29T00:00:00Z",
        "selection_author": "self-test",
        "claim_scope": "Protocol-only self-test fixture for final blind benchmark administrative invariants.",
        "analyzer_bundle": {
            "effect_system": "EffectV7-frozen",
            "optimizer_policy": "hybrid-fail-closed-v0",
            "runner_path": "experiments/autocontract_final_benchmark_admin.py",
            "adapter_paths": ["experiments/autocontract_final_benchmark_admin.py"],
        },
        "contamination_policy": {
            "registry_path": "benchmark/final_v1/contamination_registry.json",
            "selection_cutoff": "2026-07-29T00:00:00Z",
            "minimum_novel_frameworks": 1,
        },
        "metric_gates": REQUIRED_GATES,
        "units": units,
    }

    oracle_units = []
    for index, public_unit in enumerate(units):
        reject = index % 3 == 0
        oracle_units.append(
            {
                "unit_id": public_unit["unit_id"],
                "expected_decision": "reject" if reject else "admit",
                "known_unsafe": reject,
                "coarse_reason": "hidden_rng_effect" if reject else "none",
                "effect_labels": {"randomness": "present" if reject else "absent"},
                "semantic_oracle": {
                    "output": "fixture observation",
                    "rng": "fixture observation",
                    "gradient": "fixture observation",
                    "lineage": "fixture observation",
                    "diversity": "fixture observation",
                },
                "rationale": "Self-test rationale with sufficient length.",
                "confidence": "high",
                "evidence_anchors": [f"fixture:{index}"],
                "reviewed_by": ["reviewer-01"],
            }
        )
    oracle = {
        "schema_version": "autocontract.final-oracle.v1",
        "artifact_type": "private_oracle",
        "benchmark_id": public["benchmark_id"],
        "public_manifest_sha256": canonical_sha256(public),
        "commitment_salt_hex": hashlib.sha256(b"fixed-self-test-salt").hexdigest(),
        "annotators": [
            {
                "annotator_id": "primary-01",
                "role": "primary",
                "independent_of_analyzer": True,
                "conflict_disclosure": "fixture",
            },
            {
                "annotator_id": "reviewer-01",
                "role": "reviewer",
                "independent_of_analyzer": True,
                "conflict_disclosure": "fixture",
            },
        ],
        "units": oracle_units,
        "adjudication": {"status": "complete", "disagreement_count": 0, "record_path": "fixture"},
    }
    return public, oracle


def expect_failure(name: str, action: Any, checks: list[dict[str, Any]]) -> None:
    try:
        action()
    except ValidationError as exc:
        checks.append({"name": name, "passed": True, "observed": str(exc)})
    else:
        checks.append({"name": name, "passed": False, "observed": "unexpected acceptance"})


def run_self_test(output_path: Path | None) -> dict[str, Any]:
    public, oracle = make_fixture()
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="autocontract-final-admin-") as temp_dir:
        temp = Path(temp_dir)
        public_path = temp / "public.json"
        oracle_path = temp / "oracle.json"
        commitment_path = temp / "commitment.json"
        freeze_path = temp / "freeze.json"
        write_json(public_path, public)
        write_json(oracle_path, oracle)

        summary = validate_public(public, strict=True)
        checks.append({"name": "strict public fixture accepted", "passed": summary["unit_count"] == 60})
        private_summary = validate_private(oracle, public, strict=True)
        checks.append({"name": "strict private fixture accepted", "passed": private_summary["unit_count"] == 60})
        build_commitment(oracle_path, public_path, commitment_path)
        checks.append({"name": "salted commitment created", "passed": commitment_path.is_file()})
        verified = verify_oracle(oracle_path, public_path, commitment_path)
        checks.append({"name": "untampered oracle verified", "passed": verified["verified"]})

        leaked_public = copy.deepcopy(public)
        leaked_public["units"][0]["expected_decision"] = "admit"
        expect_failure("public label leakage rejected", lambda: validate_public(leaked_public, strict=True), checks)

        tampered_oracle = copy.deepcopy(oracle)
        tampered_oracle["units"][0]["rationale"] += " tampered"
        tampered_path = temp / "tampered-oracle.json"
        write_json(tampered_path, tampered_oracle)
        expect_failure(
            "post-commit oracle tampering rejected",
            lambda: verify_oracle(tampered_path, public_path, commitment_path),
            checks,
        )

        mismatched_oracle = copy.deepcopy(oracle)
        mismatched_oracle["units"].pop()
        expect_failure(
            "public/private unit mismatch rejected",
            lambda: validate_private(mismatched_oracle, public, strict=True),
            checks,
        )

        modified_public = copy.deepcopy(public)
        modified_public["claim_scope"] += " changed"
        modified_public_path = temp / "modified-public.json"
        write_json(modified_public_path, modified_public)
        expect_failure(
            "post-commit public tampering rejected",
            lambda: verify_oracle(oracle_path, modified_public_path, commitment_path),
            checks,
        )

        placeholder_public = copy.deepcopy(public)
        placeholder_public["units"][0]["repository"]["commit_sha"] = "0" * 40
        expect_failure(
            "placeholder source binding rejected",
            lambda: validate_public(placeholder_public, strict=True),
            checks,
        )

        seal_bundle(
            public_path,
            commitment_path,
            Path(__file__).resolve(),
            [Path(__file__).resolve()],
            freeze_path,
        )
        freeze = load_json(freeze_path)
        checks.append(
            {
                "name": "public execution bundle sealed without private path",
                "passed": freeze_path.is_file() and "oracle" not in freeze and "private_oracle" not in json.dumps(freeze),
            }
        )

    result = {
        "schema_version": "autocontract.final-handoff-selftest.v1",
        "status": "pass" if all(check["passed"] for check in checks) else "fail",
        "passed": sum(bool(check["passed"]) for check in checks),
        "total": len(checks),
        "checks": checks,
        "note": "Synthetic protocol fixture only; this is not benchmark evidence.",
    }
    if output_path is not None:
        write_json(output_path, result)
    return result


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    self_test = subparsers.add_parser("self-test", help="exercise leakage and tamper guardrails")
    self_test.add_argument("--output", type=Path)

    validate = subparsers.add_parser("validate-public", help="validate a public manifest")
    validate.add_argument("public", type=Path)
    validate.add_argument("--strict", action="store_true")
    validate.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)

    commit = subparsers.add_parser("commit-oracle", help="create a non-label-leaking salted commitment")
    commit.add_argument("private_oracle", type=Path)
    commit.add_argument("public", type=Path)
    commit.add_argument("output", type=Path)

    verify = subparsers.add_parser("verify-oracle", help="verify a disclosed private oracle")
    verify.add_argument("private_oracle", type=Path)
    verify.add_argument("public", type=Path)
    verify.add_argument("commitment", type=Path)

    seal = subparsers.add_parser("seal", help="freeze public inputs and execution code only")
    seal.add_argument("public", type=Path)
    seal.add_argument("commitment", type=Path)
    seal.add_argument("runner", type=Path)
    seal.add_argument("output", type=Path)
    seal.add_argument("--adapter", action="append", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "self-test":
            result = run_self_test(args.output)
        elif args.command == "validate-public":
            manifest = load_json(args.public)
            registry = load_json(args.registry) if args.strict else None
            result = validate_public(manifest, strict=args.strict, registry=registry)
        elif args.command == "commit-oracle":
            result = build_commitment(args.private_oracle, args.public, args.output)
        elif args.command == "verify-oracle":
            result = verify_oracle(args.private_oracle, args.public, args.commitment)
        elif args.command == "seal":
            result = seal_bundle(args.public, args.commitment, args.runner, args.adapter, args.output)
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except ValidationError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
