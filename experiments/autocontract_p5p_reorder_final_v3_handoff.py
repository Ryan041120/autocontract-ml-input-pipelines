#!/usr/bin/env python3
"""Administer premise/native-aware final-v3 commit, seal, and reveal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v3" / "p5p_reorder_final_v3_handoff_protocol.json"
PUBLIC_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_public_manifest.schema.json"
PRIVATE_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_private_oracle.schema.json"
PREDICTION_SCHEMA = ROOT / "benchmark" / "final_v3" / "reorder_prediction.schema.json"
PUBLIC_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_public_manifest.template.json"
PRIVATE_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_private_oracle.template.json"
PREDICTION_TEMPLATE = ROOT / "benchmark" / "final_v3" / "reorder_prediction.template.json"
CONTAMINATION_REGISTRY = ROOT / "benchmark" / "final_v1" / "contamination_registry.json"
FORBIDDEN_PUBLIC_KEYS = {"label", "labels", "oracle", "commutes", "noncommutes", "counterexample", "expected", "prediction", "predictions", "receipt", "receipts", "safe", "unsafe"}
FORBIDDEN_PREDICTION_KEYS = {"label", "labels", "oracle", "commutes", "noncommutes", "counterexample", "expected", "safe", "unsafe"}
REQUIRED_PROFILE = {
    "required_runtime_premises": ["type", "layout", "channels", "dtype", "device", "height_min", "width_min"],
    "declaration_only_fields": ["value_min", "value_max", "height_max", "width_max", "allow_nonfinite"],
}


class P5PError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise P5PError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bootstrap_admin() -> Any:
    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_final_benchmark_admin_v2 as admin
    return admin


def canonical_bytes(value: Any) -> bytes:
    return bootstrap_admin().canonical_bytes(value)


def canonical_sha256(value: Any) -> str:
    return bootstrap_admin().canonical_sha256(value)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: object required")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def schema_validate(value: dict[str, Any], path: Path) -> None:
    jsonschema.validate(instance=value, schema=load_json(path))


def answer_keys(value: Any, prefix: str = "$", *, forbidden: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            tokens = set(normalized.split("_"))
            if normalized in forbidden or tokens & forbidden:
                found.append(f"{prefix}.{key}")
            found.extend(answer_keys(item, f"{prefix}.{key}", forbidden=forbidden))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(answer_keys(item, f"{prefix}[{index}]", forbidden=forbidden))
    return found


def normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def expected_profile() -> dict[str, Any]:
    return {**copy.deepcopy(REQUIRED_PROFILE), "profile_sha256": canonical_sha256(REQUIRED_PROFILE)}


def native_policy(native_class: str) -> str:
    return {
        "pure_python": "allow_local_proof",
        "known_versioned_native": "allow_versioned_relation_only",
        "opaque_native": "force_unknown",
        "external_attested_native": "require_external_attestation",
    }[native_class]


def validate_public(public: dict[str, Any], *, verify_artifacts: bool = False) -> dict[str, Any]:
    schema_validate(public, PUBLIC_SCHEMA)
    leaked = answer_keys(public["pairs"], forbidden=FORBIDDEN_PUBLIC_KEYS)
    require(not leaked, "answer-bearing public key(s): " + ", ".join(leaked))
    registry = public["contamination_registry"]
    require(registry["path"] == "benchmark/final_v1/contamination_registry.json" and registry["sha256"] == file_sha256(CONTAMINATION_REGISTRY), "contamination_registry_drift")
    framework_ids = [item["framework_id"] for item in public["frameworks"]]
    require(len(framework_ids) == len(set(framework_ids)), "duplicate_framework_id")
    framework_by_id = {item["framework_id"]: item for item in public["frameworks"]}
    pair_ids = [item["pair_id"] for item in public["pairs"]]
    require(len(pair_ids) == len(set(pair_ids)), "duplicate_pair_id")
    profile = expected_profile()
    for pair in public["pairs"]:
        require(pair["framework_id"] in framework_by_id, f"{pair['pair_id']}:unknown_framework")
        require(pair["left"]["operator_id"] != pair["right"]["operator_id"], f"{pair['pair_id']}:identical_operators")
        require(pair["input_domain"]["premise_profile"] == profile, f"{pair['pair_id']}:premise_profile_drift")
        relation = pair["operation_context"]["observational_relation"]
        require((relation["output"] == "declared_tolerance") == (relation["tolerance_artifact"] is not None), f"{pair['pair_id']}:tolerance_artifact_mismatch")
        for side in ("left", "right"):
            boundary = pair[side]["native_boundary"]
            require(boundary["strict_policy"] == native_policy(boundary["class"]), f"{pair['pair_id']}:{side}:native_policy_mismatch")
    if public["evaluation_mode"] == "development_dry_run":
        require(6 <= len(pair_ids) <= 8, "dry_run_pair_count_outside_6_8")
        require(all(pair["contamination"]["development_fixture"] for pair in public["pairs"]), "dry_run_not_marked_contaminated")
    else:
        require(public["status"] == "sealed" and public["selection_independent_of_analyzer"], "final_independence_or_seal_missing")
        require(20 <= len(pair_ids) <= 40 and len(framework_ids) >= 3, "final_pair_or_framework_quota_missing")
        require(len({item["domain"] for item in public["frameworks"]}) >= 2, "final_domain_quota_missing")
        require(len({pair["pair_family"] for pair in public["pairs"]}) >= 4, "final_family_quota_missing")
        require(all(not pair["contamination"]["development_fixture"] and not pair["contamination"]["registry_match"] for pair in public["pairs"]), "final_contamination_detected")
        require(public["reporting_plan"]["viability_threshold_status"] == "frozen_before_independent_selection", "final_reporting_not_frozen")
        known = {normalized_name(item["name"]) for item in load_json(CONTAMINATION_REGISTRY)["development_sources"] if item["kind"] == "framework"}
        require(not ({normalized_name(item) for item in framework_ids} & known), "known_development_framework_in_final")
    artifact_names = [item["name"] for item in public["analyzer_bundle"]]
    artifact_paths = [item["path"] for item in public["analyzer_bundle"]]
    require(len(artifact_names) == len(set(artifact_names)) and len(artifact_paths) == len(set(artifact_paths)), "duplicate_analyzer_artifact")
    if verify_artifacts:
        for artifact in public["analyzer_bundle"]:
            path = (ROOT / artifact["path"]).resolve()
            require(path.is_relative_to(ROOT) and path.is_file(), f"artifact_missing_or_escape:{artifact['path']}")
            require(file_sha256(path) == artifact["sha256"], f"artifact_drift:{artifact['path']}")
    return {
        "benchmark_id": public["benchmark_id"], "evaluation_mode": public["evaluation_mode"], "pair_count": len(pair_ids),
        "framework_count": len(framework_ids), "domain_count": len({item["domain"] for item in public["frameworks"]}),
        "family_count": len({pair["pair_family"] for pair in public["pairs"]}), "canonical_sha256": canonical_sha256(public),
    }


def validate_private(oracle: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    schema_validate(oracle, PRIVATE_SCHEMA)
    require(oracle["benchmark_id"] == public["benchmark_id"] and oracle["public_manifest_sha256"] == canonical_sha256(public), "oracle_public_binding_mismatch")
    roles = {item["role"] for item in oracle["annotators"]}
    require({"primary", "reviewer"} <= roles, "primary_and_reviewer_required")
    require(len({item["annotator_id"] for item in oracle["annotators"]}) == len(oracle["annotators"]), "duplicate_annotator")
    require([unit["pair_id"] for unit in oracle["units"]] == [pair["pair_id"] for pair in public["pairs"]], "oracle_pair_order_mismatch")
    disagreements = 0
    labels = {"commutes": 0, "noncommutes": 0, "unknown": 0}
    adjudicators = {item["annotator_id"] for item in oracle["annotators"] if item["role"] == "adjudicator"}
    reviewer_ids = {item["annotator_id"] for item in oracle["annotators"] if item["role"] in {"reviewer", "adjudicator"}}
    for unit in oracle["units"]:
        label, checks = unit["adjudicated_label"], unit["observation_checks"]
        labels[label] += 1
        require(set(unit["reviewed_by"]) <= reviewer_ids, f"{unit['pair_id']}:invalid_reviewer")
        if unit["primary_label"] != unit["reviewer_label"]:
            disagreements += 1
            require(bool(set(unit["reviewed_by"]) & adjudicators), f"{unit['pair_id']}:disagreement_without_adjudicator")
        if label == "commutes":
            require(unit["proof_kind"] in {"formal", "manual_source_proof"} and unit["premises"] and unit["counterexample"] is None, f"{unit['pair_id']}:bad_commutes_evidence")
            require(all(value in {"verified", "not_applicable"} for value in checks.values()), f"{unit['pair_id']}:commutes_observation_unresolved")
        elif label == "noncommutes":
            require(unit["proof_kind"] == "counterexample" and unit["counterexample"] is not None and "violated" in checks.values(), f"{unit['pair_id']}:bad_noncommutes_evidence")
            witness = unit["counterexample"]
            require(witness["original_outcome_sha256"] != witness["swapped_outcome_sha256"], f"{unit['pair_id']}:identical_witness_outcomes")
        else:
            require(unit["proof_kind"] == "unresolved" and unit["counterexample"] is None and "unresolved" in checks.values(), f"{unit['pair_id']}:bad_unknown_evidence")
    require(oracle["adjudication"]["disagreement_count"] == disagreements, "adjudication_count_mismatch")
    return {"pair_count": len(oracle["units"]), "label_counts": labels, "disagreements": disagreements, "canonical_sha256": canonical_sha256(oracle)}


def validate_prediction(prediction: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    schema_validate(prediction, PREDICTION_SCHEMA)
    leaked = answer_keys(prediction["pairs"], forbidden=FORBIDDEN_PREDICTION_KEYS)
    require(not leaked, "answer-bearing prediction key(s): " + ", ".join(leaked))
    require(prediction["benchmark_id"] == public["benchmark_id"] and prediction["public_manifest_sha256"] == canonical_sha256(public), "prediction_public_binding_mismatch")
    require(prediction["producer_bundle_sha256"] == canonical_sha256(public["analyzer_bundle"]), "producer_bundle_mismatch")
    by_id = {pair["pair_id"]: pair for pair in public["pairs"]}
    require([item["pair_id"] for item in prediction["pairs"]] == list(by_id), "prediction_pair_order_mismatch")
    adapter_total = 0.0
    for item in prediction["pairs"]:
        pair = by_id[item["pair_id"]]
        adapter_total += float(item["adapter_minutes"])
        domain = item["domain_assurance"]
        require(domain["premise_profile_sha256"] == pair["input_domain"]["premise_profile"]["profile_sha256"], f"{item['pair_id']}:domain_profile_mismatch")
        public_classes = {pair["left"]["native_boundary"]["class"], pair["right"]["native_boundary"]["class"]}
        predicted_classes = {item["native_decision"]["left_class"], item["native_decision"]["right_class"]}
        require(public_classes == predicted_classes, f"{item['pair_id']}:native_class_mismatch")
        if item["status"] == "supported":
            require(item["receipt_sha256"] is not None and item["assurance_level"] != "none", f"{item['pair_id']}:supported_without_receipt")
            require(domain["mode"] in {"batch_boundary", "per_sample", "external_attestation"} and domain["violations"] == 0, f"{item['pair_id']}:supported_without_runtime_domain_assurance")
            require("opaque_native" not in public_classes or item["native_decision"]["policy"] == "external_attestation", f"{item['pair_id']}:opaque_native_supported_without_attestation")
            relation = pair["operation_context"]["observational_relation"]
            require(relation["output"] != "declared_tolerance" or item["assurance_level"] == "trusted_revocable_external_proof", f"{item['pair_id']}:local_proof_used_for_tolerance_relation")
        else:
            require(item["receipt_sha256"] is None and item["assurance_level"] == "none", f"{item['pair_id']}:non_supported_carries_receipt")
    require(abs(adapter_total - float(prediction["burden"]["total_adapter_minutes"])) <= 1e-9, "adapter_burden_total_mismatch")
    return {"pair_count": len(prediction["pairs"]), "supported": sum(item["status"] == "supported" for item in prediction["pairs"]), "canonical_sha256": canonical_sha256(prediction)}


def oracle_commitment_sha256(oracle: dict[str, Any]) -> str:
    return hashlib.sha256(b"autocontract.reorder-final-oracle.v1\0" + canonical_bytes(oracle)).hexdigest()


def prediction_commitment_sha256(prediction: dict[str, Any]) -> str:
    return hashlib.sha256(b"autocontract.reorder-final-prediction.v1\0" + canonical_bytes(prediction)).hexdigest()


def commit_oracle(private_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    public, oracle = load_json(public_path), load_json(private_path)
    validate_public(public); validate_private(oracle, public)
    value = {"schema_version": "autocontract.reorder-oracle-commitment.v1", "artifact_type": "reorder_private_oracle_commitment", "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public), "oracle_commitment_sha256": oracle_commitment_sha256(oracle), "pair_count": len(public["pairs"])}
    write_json(output_path, value)
    return value


def validate_oracle_commitment(value: dict[str, Any]) -> None:
    expected = {"schema_version", "artifact_type", "benchmark_id", "public_manifest_sha256", "oracle_commitment_sha256", "pair_count"}
    require(set(value) == expected and value["schema_version"] == "autocontract.reorder-oracle-commitment.v1" and value["artifact_type"] == "reorder_private_oracle_commitment", "bad_oracle_commitment")


def freeze_public(public_path: Path, commitment_path: Path, output_path: Path) -> dict[str, Any]:
    public, commitment = load_json(public_path), load_json(commitment_path)
    summary = validate_public(public, verify_artifacts=True); validate_oracle_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"] and commitment["public_manifest_sha256"] == canonical_sha256(public), "commitment_does_not_bind_public")
    value = {
        "schema_version": "autocontract.reorder-public-freeze.v1", "artifact_type": "reorder_public_execution_freeze", "benchmark_id": public["benchmark_id"],
        "evaluation_mode": public["evaluation_mode"], "public_manifest": {"path": str(public_path), "canonical_sha256": canonical_sha256(public), "file_sha256": file_sha256(public_path)},
        "oracle_commitment": {"path": str(commitment_path), "canonical_sha256": canonical_sha256(commitment), "file_sha256": file_sha256(commitment_path)},
        "analyzer_artifacts": copy.deepcopy(public["analyzer_bundle"]), "reporting_plan": copy.deepcopy(public["reporting_plan"]), "public_summary": summary,
        "claim_boundary": "Public execution artifacts and oracle commitment only; private labels, rationale, and witnesses are excluded.",
    }
    write_json(output_path, value)
    return value


def seal_prediction(prediction_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    public, prediction = load_json(public_path), load_json(prediction_path)
    validate_public(public); summary = validate_prediction(prediction, public)
    value = {"schema_version": "autocontract.reorder-prediction-seal.v1", "artifact_type": "reorder_prediction_seal", "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public), "producer_bundle_sha256": prediction["producer_bundle_sha256"], "prediction_commitment_sha256": prediction_commitment_sha256(prediction), "pair_count": summary["pair_count"]}
    write_json(output_path, value)
    return value


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> dict[str, Any]:
    if total == 0:
        return {"successes": successes, "total": total, "rate": None, "low": None, "high": None}
    rate = successes / total
    denominator = 1.0 + z * z / total
    centre = (rate + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4.0 * total * total)) / denominator
    return {"successes": successes, "total": total, "rate": rate, "low": max(0.0, centre - margin), "high": min(1.0, centre + margin)}


def reveal_score(public_path: Path, private_path: Path, commitment_path: Path, prediction_path: Path, seal_path: Path) -> dict[str, Any]:
    public, oracle, commitment = load_json(public_path), load_json(private_path), load_json(commitment_path)
    prediction, seal = load_json(prediction_path), load_json(seal_path)
    validate_public(public); validate_private(oracle, public); validate_prediction(prediction, public); validate_oracle_commitment(commitment)
    require(commitment["public_manifest_sha256"] == canonical_sha256(public) and commitment["oracle_commitment_sha256"] == oracle_commitment_sha256(oracle), "oracle_commitment_mismatch")
    require(seal["schema_version"] == "autocontract.reorder-prediction-seal.v1" and seal["public_manifest_sha256"] == canonical_sha256(public) and seal["prediction_commitment_sha256"] == prediction_commitment_sha256(prediction), "prediction_seal_mismatch")
    labels = {unit["pair_id"]: unit["adjudicated_label"] for unit in oracle["units"]}
    statuses = {item["pair_id"]: item["status"] for item in prediction["pairs"]}
    unsafe = [pair_id for pair_id, label in labels.items() if label == "noncommutes" and statuses[pair_id] == "supported"]
    unresolved = [pair_id for pair_id, label in labels.items() if label == "unknown" and statuses[pair_id] == "supported"]
    family: dict[str, dict[str, Any]] = {}; rng: dict[str, dict[str, Any]] = {}
    for pair in public["pairs"]:
        pair_id, label = pair["pair_id"], labels[pair["pair_id"]]
        for key, bucket in ((pair["pair_family"], family), (pair["operation_context"]["rng_assignment"], rng)):
            row = bucket.setdefault(key, {"commutes": 0, "supported_commutes": 0})
            if label == "commutes":
                row["commutes"] += 1; row["supported_commutes"] += statuses[pair_id] == "supported"
    for bucket in (family, rng):
        for row in bucket.values():
            row["wilson"] = wilson(row["supported_commutes"], row["commutes"])
    commutes = sum(label == "commutes" for label in labels.values())
    supported_commutes = sum(label == "commutes" and statuses[pair_id] == "supported" for pair_id, label in labels.items())
    completion = len(statuses) / len(public["pairs"])
    safety_pass = not unsafe and not unresolved
    coverage = supported_commutes / commutes if commutes else 0.0
    gates = public["reporting_plan"]
    gate_pass = safety_pass and completion >= gates["prediction_completion_min"] and coverage >= gates["commutes_coverage_pilot_floor"]
    supported_pairs = [pair for pair in public["pairs"] if statuses[pair["pair_id"]] == "supported"]
    scientific_eligible = public["evaluation_mode"] == "independent_final" and public["selection_independent_of_analyzer"] and all(not pair["contamination"]["development_fixture"] and not pair["contamination"]["registry_match"] for pair in public["pairs"])
    return {
        "unsafe_supported": {"count": len(unsafe), "pair_ids": unsafe, "pass": not unsafe},
        "unresolved_supported": {"count": len(unresolved), "pair_ids": unresolved, "pass": not unresolved},
        "completion": completion, "overall_commutes_coverage": wilson(supported_commutes, commutes),
        "family_strata": family, "rng_strata": rng,
        "non_identity_supported": sum(pair["pair_family"] != "identity" for pair in supported_pairs),
        "supported_framework_count": len({pair["framework_id"] for pair in supported_pairs}),
        "burden": copy.deepcopy(prediction["burden"]), "gate_pass": gate_pass,
        "scientific_evidence_eligible": scientific_eligible,
        "claim_boundary": "Safety/coverage/burden report only; system benefit requires a separately frozen workload execution.",
    }


def expect_failure(name: str, action: Callable[[], Any], checks: list[dict[str, Any]]) -> None:
    try:
        action()
    except (P5PError, jsonschema.ValidationError, KeyError, TypeError, ValueError) as exc:
        checks.append({"name": name, "passed": True, "reason": f"{type(exc).__name__}:{exc}"})
    else:
        checks.append({"name": name, "passed": False, "reason": "unexpected_accept"})


def run_self_test(output_path: Path | None) -> dict[str, Any]:
    protocol = load_json(PROTOCOL)
    checks: list[dict[str, Any]] = []
    frozen = {path: file_sha256(ROOT / path) for path in protocol["frozen_predecessors"]}
    checks.append({"name": "frozen predecessors exact", "passed": frozen == protocol["frozen_predecessors"], "observed": frozen})
    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_p5o_domain_native_assurance as p5o
    public, oracle, prediction = p5o.make_dry_run_fixture()
    with tempfile.TemporaryDirectory(prefix="autocontract-p5p-") as directory:
        temp = Path(directory)
        public_path, private_path, prediction_path = temp / "public.json", temp / "private.json", temp / "prediction.json"
        commitment_path, freeze_path, seal_path = temp / "commitment.json", temp / "freeze.json", temp / "seal.json"
        write_json(public_path, public); write_json(private_path, oracle); write_json(prediction_path, prediction)
        schema_validate(load_json(PUBLIC_TEMPLATE), PUBLIC_SCHEMA); checks.append({"name": "public template validates", "passed": True})
        schema_validate(load_json(PRIVATE_TEMPLATE), PRIVATE_SCHEMA); checks.append({"name": "private template validates", "passed": True})
        schema_validate(load_json(PREDICTION_TEMPLATE), PREDICTION_SCHEMA); checks.append({"name": "prediction template validates", "passed": True})
        checks.append({"name": "dry-run public invariants accepted", "passed": validate_public(public, verify_artifacts=True)["pair_count"] == 8})
        checks.append({"name": "observation-explicit oracle accepted", "passed": validate_private(oracle, public)["pair_count"] == 8})
        checks.append({"name": "domain/native-aware prediction accepted", "passed": validate_prediction(prediction, public)["pair_count"] == 8})
        commit_oracle(private_path, public_path, commitment_path); checks.append({"name": "oracle commitment created", "passed": commitment_path.is_file()})
        freeze = freeze_public(public_path, commitment_path, freeze_path); checks.append({"name": "public freeze binds analyzer and excludes oracle", "passed": freeze_path.is_file() and str(private_path) not in json.dumps(freeze) and "adjudicated_label" not in json.dumps(freeze)})
        seal_prediction(prediction_path, public_path, seal_path); checks.append({"name": "prediction seal created", "passed": seal_path.is_file()})
        score = reveal_score(public_path, private_path, commitment_path, prediction_path, seal_path)
        checks.append({"name": "reveal is safety-first and gate-complete", "passed": list(score)[:2] == ["unsafe_supported", "unresolved_supported"] and score["gate_pass"]})
        checks.append({"name": "contaminated dry-run never becomes scientific evidence", "passed": score["scientific_evidence_eligible"] is False})
        checks.append({"name": "family RNG Wilson and burden are reported", "passed": len(score["family_strata"]) >= 4 and len(score["rng_strata"]) >= 2 and score["non_identity_supported"] >= 1 and score["supported_framework_count"] >= 2 and score["burden"]["all_pairs_timed"]})

        broken = copy.deepcopy(public); broken["pairs"][0]["oracle_label"] = "commutes"
        expect_failure("public answer leak rejected", lambda: validate_public(broken), checks)
        broken = copy.deepcopy(public); broken["evaluation_mode"] = "independent_final"; broken["selection_independent_of_analyzer"] = True; broken["reporting_plan"]["viability_threshold_status"] = "frozen_before_independent_selection"
        expect_failure("eight-pair fixture cannot masquerade as independent final", lambda: validate_public(broken), checks)
        broken_oracle = copy.deepcopy(oracle); commute = next(i for i, unit in enumerate(broken_oracle["units"]) if unit["adjudicated_label"] == "commutes"); broken_oracle["units"][commute]["observation_checks"]["definedness"] = "unresolved"
        expect_failure("Commutes with unresolved observation rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); non = next(i for i, unit in enumerate(broken_oracle["units"]) if unit["adjudicated_label"] == "noncommutes"); broken_oracle["units"][non]["observation_checks"] = {key: "verified" for key in broken_oracle["units"][non]["observation_checks"]}
        expect_failure("Noncommutes without violated dimension rejected", lambda: validate_private(broken_oracle, public), checks)
        tampered_oracle = copy.deepcopy(oracle); tampered_oracle["units"][0]["rationale"] += " tampered"; tampered_private = temp / "tampered-private.json"; write_json(tampered_private, tampered_oracle)
        expect_failure("post-commit oracle tampering rejected", lambda: reveal_score(public_path, tampered_private, commitment_path, prediction_path, seal_path), checks)
        tampered_prediction = copy.deepcopy(prediction); tampered_prediction["pairs"][0]["reason"] += " tampered"; tampered_prediction_path = temp / "tampered-prediction.json"; write_json(tampered_prediction_path, tampered_prediction)
        expect_failure("post-seal prediction tampering rejected", lambda: reveal_score(public_path, private_path, commitment_path, tampered_prediction_path, seal_path), checks)
        broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"].pop()
        expect_failure("missing prediction rejected", lambda: validate_prediction(broken_prediction, public), checks)
        broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"][0], broken_prediction["pairs"][1] = broken_prediction["pairs"][1], broken_prediction["pairs"][0]
        expect_failure("prediction order mismatch rejected", lambda: validate_prediction(broken_prediction, public), checks)
        broken_prediction = copy.deepcopy(prediction); broken_prediction["burden"]["total_adapter_minutes"] += 1.0
        expect_failure("burden arithmetic mismatch rejected", lambda: validate_prediction(broken_prediction, public), checks)
        opaque = 7; broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"][opaque].update({"status": "supported", "assurance_level": "locally_replayed_versioned_relation_algebra", "receipt_sha256": hashlib.sha256(b"opaque").hexdigest()})
        expect_failure("opaque native Supported rejected", lambda: validate_prediction(broken_prediction, public), checks)
        supported = next(i for i, item in enumerate(prediction["pairs"]) if item["status"] == "supported"); broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"][supported]["domain_assurance"]["violations"] = 1
        expect_failure("runtime premise violation Supported rejected", lambda: validate_prediction(broken_prediction, public), checks)
        broken_public = copy.deepcopy(public); broken_public["analyzer_bundle"][0]["sha256"] = "0" * 64
        expect_failure("analyzer artifact drift rejected at freeze", lambda: validate_public(broken_public, verify_artifacts=True), checks)

    require(len(checks) == 25, f"self-test definition drift:{len(checks)}")
    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5p-reorder-final-v3-handoff-selftest.v0", "status": "pass" if passed == len(checks) else "fail",
        "passed": passed, "total": len(checks), "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
        "schema_sha256": {"public": file_sha256(PUBLIC_SCHEMA), "private": file_sha256(PRIVATE_SCHEMA), "prediction": file_sha256(PREDICTION_SCHEMA)},
        "synthetic_fixture": {"pairs": 8, "contaminated": True, "scientific_evidence": False}, "checks": checks, "claim_boundary": protocol["claim_boundary"],
    }
    if output_path is not None:
        write_json(output_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    command = sub.add_parser("validate-public"); command.add_argument("public", type=Path); command.add_argument("--verify-artifacts", action="store_true")
    command = sub.add_parser("validate-private"); command.add_argument("private", type=Path); command.add_argument("public", type=Path)
    command = sub.add_parser("validate-prediction"); command.add_argument("prediction", type=Path); command.add_argument("public", type=Path)
    command = sub.add_parser("commit-oracle"); command.add_argument("private", type=Path); command.add_argument("public", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("freeze-public"); command.add_argument("public", type=Path); command.add_argument("commitment", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("seal-prediction"); command.add_argument("prediction", type=Path); command.add_argument("public", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("reveal-score"); command.add_argument("public", type=Path); command.add_argument("private", type=Path); command.add_argument("commitment", type=Path); command.add_argument("prediction", type=Path); command.add_argument("seal", type=Path)
    command = sub.add_parser("self-test"); command.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate-public": value = validate_public(load_json(args.public), verify_artifacts=args.verify_artifacts)
        elif args.command == "validate-private": value = validate_private(load_json(args.private), load_json(args.public))
        elif args.command == "validate-prediction": value = validate_prediction(load_json(args.prediction), load_json(args.public))
        elif args.command == "commit-oracle": value = commit_oracle(args.private, args.public, args.output)
        elif args.command == "freeze-public": value = freeze_public(args.public, args.commitment, args.output)
        elif args.command == "seal-prediction": value = seal_prediction(args.prediction, args.public, args.output)
        elif args.command == "reveal-score": value = reveal_score(args.public, args.private, args.commitment, args.prediction, args.seal)
        else: value = run_self_test(args.output)
    except (OSError, P5PError, jsonschema.ValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if not isinstance(value, dict) or value.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
