#!/usr/bin/env python3
"""Administer a role-separated, committed reorder-final handoff and reveal."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v2" / "p5n_reorder_final_handoff_protocol.json"
PUBLIC_SCHEMA = ROOT / "benchmark" / "final_v2" / "reorder_public_manifest.schema.json"
PRIVATE_SCHEMA = ROOT / "benchmark" / "final_v2" / "reorder_private_oracle.schema.json"
PREDICTION_SCHEMA = ROOT / "benchmark" / "final_v2" / "reorder_prediction.schema.json"
PUBLIC_TEMPLATE = ROOT / "benchmark" / "final_v2" / "reorder_public_manifest.template.json"
PRIVATE_TEMPLATE = ROOT / "benchmark" / "final_v2" / "reorder_private_oracle.template.json"
PREDICTION_TEMPLATE = ROOT / "benchmark" / "final_v2" / "reorder_prediction.template.json"
CONTAMINATION_REGISTRY = ROOT / "benchmark" / "final_v1" / "contamination_registry.json"
FORBIDDEN_ANSWER_KEYS = {
    "label", "labels", "oracle", "commutes", "noncommutes", "counterexample",
    "expected", "prediction", "predictions", "receipt", "receipts", "safe", "unsafe",
}
PREDICTION_FORBIDDEN_KEYS = {
    "label", "labels", "oracle", "commutes", "noncommutes", "counterexample",
    "expected", "safe", "unsafe",
}
REQUIRED_GATES = {
    "unsafe_supported_max": 0,
    "unresolved_supported_max": 0,
    "commutes_coverage_min": 0.3,
    "prediction_completion_min": 1.0,
    "minimum_pairs": 20,
    "maximum_pairs": 40,
    "minimum_frameworks": 3,
    "minimum_domains": 2,
}


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path}: top-level object required")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bootstrap_admin() -> Any:
    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_final_benchmark_admin_v2 as final_admin
    return final_admin


def canonical_sha256(value: Any) -> str:
    return bootstrap_admin().canonical_sha256(value)


def canonical_bytes(value: Any) -> bytes:
    return bootstrap_admin().canonical_bytes(value)


def oracle_commitment_sha256(oracle: dict[str, Any]) -> str:
    return hashlib.sha256(b"autocontract.reorder-final-oracle.v0\0" + canonical_bytes(oracle)).hexdigest()


def prediction_commitment_sha256(prediction: dict[str, Any]) -> str:
    return hashlib.sha256(b"autocontract.reorder-final-prediction.v0\0" + canonical_bytes(prediction)).hexdigest()


def schema_validate(value: dict[str, Any], schema_path: Path) -> None:
    jsonschema.validate(instance=value, schema=load_json(schema_path))


def answer_keys(value: Any, prefix: str = "$", *, forbidden: set[str] | None = None) -> list[str]:
    forbidden = FORBIDDEN_ANSWER_KEYS if forbidden is None else forbidden
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


def resolve_artifact(path_text: str) -> Path:
    path = (ROOT / path_text).resolve()
    require(path.is_relative_to(ROOT), f"artifact escapes workspace: {path_text}")
    require(path.is_file(), f"artifact missing: {path_text}")
    return path


def validate_public(public: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    schema_validate(public, PUBLIC_SCHEMA)
    require(public["metric_gates"] == REQUIRED_GATES, "metric gates changed")
    leaked = answer_keys(public["pairs"])
    require(not leaked, "answer-bearing public pair key(s): " + ", ".join(leaked))
    registry = public["contamination_registry"]
    require(registry["path"] == "benchmark/final_v1/contamination_registry.json", "wrong contamination registry path")
    require(registry["sha256"] == file_sha256(CONTAMINATION_REGISTRY), "contamination registry drift")
    framework_ids = [item["framework_id"] for item in public["frameworks"]]
    require(len(framework_ids) == len(set(framework_ids)), "duplicate framework_id")
    framework_by_id = {item["framework_id"]: item for item in public["frameworks"]}
    pair_ids = [item["pair_id"] for item in public["pairs"]]
    require(len(pair_ids) == len(set(pair_ids)), "duplicate pair_id")
    for pair in public["pairs"]:
        require(pair["framework_id"] in framework_by_id, f"{pair['pair_id']}: unknown framework")
        require(pair["left"]["operator_id"] != pair["right"]["operator_id"], f"{pair['pair_id']}: identical operator ids")
    artifact_names = [item["name"] for item in public["analyzer_bundle"]]
    artifact_paths = [item["path"] for item in public["analyzer_bundle"]]
    require(len(artifact_names) == len(set(artifact_names)) and len(artifact_paths) == len(set(artifact_paths)), "duplicate analyzer artifact")
    if strict:
        require(public["status"] == "sealed", "strict public manifest must be sealed")
        require(public["selection_independent_of_analyzer"] is True, "selector is not independent of analyzer")
        require(REQUIRED_GATES["minimum_pairs"] <= len(pair_ids) <= REQUIRED_GATES["maximum_pairs"], "pair quota not met")
        domains = {item["domain"] for item in public["frameworks"]}
        require(len(framework_ids) >= REQUIRED_GATES["minimum_frameworks"] and len(domains) >= REQUIRED_GATES["minimum_domains"], "framework/domain quota not met")
        known = {normalized_name(item["name"]) for item in load_json(CONTAMINATION_REGISTRY)["development_sources"] if item["kind"] == "framework"}
        require(not ({normalized_name(item) for item in framework_ids} & known), "contaminated framework_id in final manifest")
        require("replace-with" not in json.dumps(public, ensure_ascii=False).casefold(), "sealed manifest contains placeholder")
        for framework in public["frameworks"]:
            require(framework["commit_sha"] != "0" * 40 and framework["source_tree_sha256"] != "0" * 64, "placeholder framework source binding")
        for pair in public["pairs"]:
            require(pair["contamination"] == {"seen_during_p5k_p5m": False, "registry_match": False}, f"{pair['pair_id']}: contaminated pair")
            require(pair["left"]["source_index_sha256"] != "0" * 64 and pair["right"]["source_index_sha256"] != "0" * 64, f"{pair['pair_id']}: placeholder operator source binding")
            require(pair["input_domain"]["sha256"] != "0" * 64, f"{pair['pair_id']}: placeholder input-domain binding")
        for artifact in public["analyzer_bundle"]:
            require(artifact["sha256"] != "0" * 64, "placeholder analyzer artifact hash")
    return {
        "benchmark_id": public["benchmark_id"], "pair_count": len(pair_ids),
        "framework_count": len(framework_ids), "domain_count": len({item["domain"] for item in public["frameworks"]}),
        "canonical_sha256": canonical_sha256(public), "strict": strict,
    }


def validate_private(oracle: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    schema_validate(oracle, PRIVATE_SCHEMA)
    require(oracle["benchmark_id"] == public["benchmark_id"], "oracle benchmark mismatch")
    require(oracle["public_manifest_sha256"] == canonical_sha256(public), "oracle public manifest hash mismatch")
    require(oracle["commitment_salt_hex"] != "0" * 64, "placeholder oracle salt")
    roles = {item["role"] for item in oracle["annotators"]}
    require({"primary", "reviewer"} <= roles, "primary and reviewer required")
    annotator_ids = {item["annotator_id"] for item in oracle["annotators"]}
    reviewer_ids = {item["annotator_id"] for item in oracle["annotators"] if item["role"] in {"reviewer", "adjudicator"}}
    require(len(annotator_ids) == len(oracle["annotators"]), "duplicate annotator_id")
    public_ids = [item["pair_id"] for item in public["pairs"]]
    private_ids = [item["pair_id"] for item in oracle["units"]]
    require(private_ids == public_ids, "private pair ids/order do not exactly match public manifest")
    disagreements = 0
    label_counts = {"commutes": 0, "noncommutes": 0, "unknown": 0}
    for unit in oracle["units"]:
        label = unit["adjudicated_label"]
        label_counts[label] += 1
        require(set(unit["reviewed_by"]) <= reviewer_ids and unit["reviewed_by"], f"{unit['pair_id']}: invalid reviewed_by")
        if unit["primary_label"] != unit["reviewer_label"]:
            disagreements += 1
            adjudicators = {item["annotator_id"] for item in oracle["annotators"] if item["role"] == "adjudicator"}
            require(bool(set(unit["reviewed_by"]) & adjudicators), f"{unit['pair_id']}: disagreement lacks adjudicator")
        if label == "commutes":
            require(unit["proof_kind"] in {"formal", "manual_source_proof"} and unit["premises"], f"{unit['pair_id']}: Commutes lacks proof premises")
            require(unit["counterexample"] is None, f"{unit['pair_id']}: Commutes cannot carry counterexample")
        elif label == "noncommutes":
            require(unit["proof_kind"] == "counterexample" and unit["counterexample"] is not None, f"{unit['pair_id']}: Noncommutes requires witness")
            witness = unit["counterexample"]
            require(witness["original_outcome_sha256"] != witness["swapped_outcome_sha256"], f"{unit['pair_id']}: witness outcomes are identical")
        else:
            require(unit["proof_kind"] == "unresolved" and unit["counterexample"] is None, f"{unit['pair_id']}: Unknown must remain unresolved")
    require(oracle["adjudication"]["disagreement_count"] == disagreements, "adjudication disagreement count mismatch")
    require(oracle["adjudication"]["record_sha256"] != "0" * 64, "placeholder adjudication record hash")
    return {"benchmark_id": oracle["benchmark_id"], "pair_count": len(private_ids), "label_counts": label_counts, "disagreements": disagreements, "canonical_sha256": canonical_sha256(oracle)}


def validate_prediction(prediction: dict[str, Any], public: dict[str, Any]) -> dict[str, Any]:
    schema_validate(prediction, PREDICTION_SCHEMA)
    leaked = answer_keys(prediction["pairs"], forbidden=PREDICTION_FORBIDDEN_KEYS)
    require(not leaked, "answer-bearing prediction key(s): " + ", ".join(leaked))
    require(prediction["benchmark_id"] == public["benchmark_id"], "prediction benchmark mismatch")
    require(prediction["public_manifest_sha256"] == canonical_sha256(public), "prediction public manifest hash mismatch")
    require(prediction["producer_bundle_sha256"] == canonical_sha256(public["analyzer_bundle"]), "producer bundle mismatch")
    public_ids = [item["pair_id"] for item in public["pairs"]]
    prediction_ids = [item["pair_id"] for item in prediction["pairs"]]
    require(prediction_ids == public_ids, "prediction ids/order do not exactly match public manifest")
    for item in prediction["pairs"]:
        if item["status"] == "supported":
            require(item["receipt_sha256"] is not None and item["assurance_level"] != "none", f"{item['pair_id']}: Supported lacks verified receipt")
        else:
            require(item["receipt_sha256"] is None and item["assurance_level"] == "none", f"{item['pair_id']}: non-Supported carries receipt/assurance")
    adapter_total = sum(float(item["adapter_minutes"]) for item in prediction["pairs"])
    require(abs(adapter_total - float(prediction["burden"]["total_adapter_minutes"])) <= 1e-9, "adapter burden total mismatch")
    return {"benchmark_id": prediction["benchmark_id"], "pair_count": len(prediction_ids), "supported": sum(item["status"] == "supported" for item in prediction["pairs"]), "canonical_sha256": canonical_sha256(prediction)}


def build_oracle_commitment(oracle_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    public, oracle = load_json(public_path), load_json(oracle_path)
    validate_public(public, strict=True)
    summary = validate_private(oracle, public)
    value = {
        "schema_version": "autocontract.reorder-oracle-commitment.v0", "artifact_type": "reorder_private_oracle_commitment",
        "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public),
        "oracle_commitment_sha256": oracle_commitment_sha256(oracle), "pair_count": summary["pair_count"],
    }
    write_json(output_path, value)
    return value


def validate_oracle_commitment(value: dict[str, Any]) -> None:
    require(set(value) == {"schema_version", "artifact_type", "benchmark_id", "public_manifest_sha256", "oracle_commitment_sha256", "pair_count"}, "bad oracle commitment shape")
    require(value["schema_version"] == "autocontract.reorder-oracle-commitment.v0" and value["artifact_type"] == "reorder_private_oracle_commitment", "bad oracle commitment type")
    for key in ("public_manifest_sha256", "oracle_commitment_sha256"):
        require(isinstance(value[key], str) and len(value[key]) == 64 and set(value[key]) <= set("0123456789abcdef"), f"bad {key}")


def verify_oracle(oracle: dict[str, Any], public: dict[str, Any], commitment: dict[str, Any]) -> None:
    validate_private(oracle, public)
    validate_oracle_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"], "oracle commitment benchmark mismatch")
    require(commitment["public_manifest_sha256"] == canonical_sha256(public), "public changed after oracle commitment")
    require(commitment["oracle_commitment_sha256"] == oracle_commitment_sha256(oracle), "oracle changed after commitment")
    require(commitment["pair_count"] == len(public["pairs"]), "oracle commitment pair count mismatch")


def freeze_public(public_path: Path, commitment_path: Path, output_path: Path) -> dict[str, Any]:
    public, commitment = load_json(public_path), load_json(commitment_path)
    summary = validate_public(public, strict=True)
    validate_oracle_commitment(commitment)
    require(commitment["benchmark_id"] == public["benchmark_id"] and commitment["public_manifest_sha256"] == canonical_sha256(public), "oracle commitment does not bind public manifest")
    artifacts = []
    for item in public["analyzer_bundle"]:
        path = resolve_artifact(item["path"])
        observed = file_sha256(path)
        require(observed == item["sha256"], f"artifact drift: {item['path']}")
        artifacts.append({"name": item["name"], "path": item["path"], "sha256": observed})
    value = {
        "schema_version": "autocontract.reorder-public-freeze.v0", "artifact_type": "reorder_public_execution_freeze",
        "benchmark_id": public["benchmark_id"], "claim_boundary": "Public execution artifacts only; private oracle path, labels, rationale, and witness are excluded.",
        "public_manifest": {"path": str(public_path), "canonical_sha256": canonical_sha256(public), "file_sha256": file_sha256(public_path)},
        "oracle_commitment": {"path": str(commitment_path), "canonical_sha256": canonical_sha256(commitment), "file_sha256": file_sha256(commitment_path)},
        "analyzer_artifacts": artifacts, "metric_gates": copy.deepcopy(REQUIRED_GATES), "public_summary": summary,
    }
    write_json(output_path, value)
    return value


def seal_prediction(prediction_path: Path, public_path: Path, output_path: Path) -> dict[str, Any]:
    public, prediction = load_json(public_path), load_json(prediction_path)
    validate_public(public, strict=True)
    summary = validate_prediction(prediction, public)
    value = {
        "schema_version": "autocontract.reorder-prediction-seal.v0", "artifact_type": "reorder_prediction_seal",
        "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public),
        "producer_bundle_sha256": prediction["producer_bundle_sha256"], "prediction_commitment_sha256": prediction_commitment_sha256(prediction),
        "pair_count": summary["pair_count"],
    }
    write_json(output_path, value)
    return value


def validate_prediction_seal(value: dict[str, Any]) -> None:
    expected = {"schema_version", "artifact_type", "benchmark_id", "public_manifest_sha256", "producer_bundle_sha256", "prediction_commitment_sha256", "pair_count"}
    require(set(value) == expected, "bad prediction seal shape")
    require(value["schema_version"] == "autocontract.reorder-prediction-seal.v0" and value["artifact_type"] == "reorder_prediction_seal", "bad prediction seal type")


def reveal_score(public_path: Path, oracle_path: Path, commitment_path: Path, prediction_path: Path, prediction_seal_path: Path) -> dict[str, Any]:
    public, oracle = load_json(public_path), load_json(oracle_path)
    commitment, prediction, prediction_seal = load_json(commitment_path), load_json(prediction_path), load_json(prediction_seal_path)
    validate_public(public, strict=True)
    verify_oracle(oracle, public, commitment)
    validate_prediction(prediction, public)
    validate_prediction_seal(prediction_seal)
    require(prediction_seal["benchmark_id"] == public["benchmark_id"] and prediction_seal["public_manifest_sha256"] == canonical_sha256(public), "prediction seal public mismatch")
    require(prediction_seal["producer_bundle_sha256"] == prediction["producer_bundle_sha256"], "prediction seal producer mismatch")
    require(prediction_seal["prediction_commitment_sha256"] == prediction_commitment_sha256(prediction), "prediction changed after seal")
    require(prediction_seal["pair_count"] == len(prediction["pairs"]), "prediction seal pair count mismatch")
    labels = {item["pair_id"]: item["adjudicated_label"] for item in oracle["units"]}
    predictions = {item["pair_id"]: item["status"] for item in prediction["pairs"]}
    unsafe_supported = sorted(pair_id for pair_id, status in predictions.items() if status == "supported" and labels[pair_id] == "noncommutes")
    unresolved_supported = sorted(pair_id for pair_id, status in predictions.items() if status == "supported" and labels[pair_id] == "unknown")
    commutes_ids = [pair_id for pair_id, label in labels.items() if label == "commutes"]
    supported_commutes = sum(predictions[pair_id] == "supported" for pair_id in commutes_ids)
    coverage = supported_commutes / len(commutes_ids) if commutes_ids else 0.0
    completion = len(predictions) / len(public["pairs"])
    gate_results = {
        "unsafe_supported": len(unsafe_supported) <= REQUIRED_GATES["unsafe_supported_max"],
        "unresolved_supported": len(unresolved_supported) <= REQUIRED_GATES["unresolved_supported_max"],
        "commutes_coverage": coverage >= REQUIRED_GATES["commutes_coverage_min"],
        "prediction_completion": completion >= REQUIRED_GATES["prediction_completion_min"],
    }
    return {
        "unsafe_supported": {"count": len(unsafe_supported), "pair_ids": unsafe_supported},
        "unresolved_supported": {"count": len(unresolved_supported), "pair_ids": unresolved_supported},
        "denominators": {
            "all_pairs": len(labels), "commutes": sum(label == "commutes" for label in labels.values()),
            "noncommutes": sum(label == "noncommutes" for label in labels.values()), "unknown": sum(label == "unknown" for label in labels.values()),
            "prediction_unknown": sum(status == "unknown" for status in predictions.values()), "prediction_unsupported": sum(status == "unsupported" for status in predictions.values()),
        },
        "commutes_supported_coverage": coverage, "prediction_completion": completion,
        "gate_results": gate_results, "gate_pass": all(gate_results.values()),
        "burden": copy.deepcopy(prediction["burden"]),
        "claim_boundary": "Reveal score only; backend benefit and statistical generalization require separate frozen evaluation.",
    }


def make_fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    analyzer_paths = [
        ("ReorderCapabilityV2", "experiments/autocontract_reorder_capability_v2.py"),
        ("P5MRunner", "experiments/autocontract_p5m_relation_boundary_falsification.py"),
        ("P5NAdmin", "experiments/autocontract_p5n_reorder_final_handoff.py"),
        ("ReorderPublicSchema", "benchmark/final_v2/reorder_public_manifest.schema.json"),
        ("ReorderPrivateSchema", "benchmark/final_v2/reorder_private_oracle.schema.json"),
        ("ReorderPredictionSchema", "benchmark/final_v2/reorder_prediction.schema.json"),
    ]
    frameworks = [
        {"framework_id": f"novelframe-{index}", "domain": "vision" if index < 2 else "audio", "repository_url": f"https://example.com/novelframe-{index}", "release": "v1.0.0", "commit_sha": hashlib.sha1(f"framework-{index}".encode()).hexdigest(), "source_tree_sha256": hashlib.sha256(f"tree-{index}".encode()).hexdigest()}
        for index in range(3)
    ]
    pairs = []
    for index in range(24):
        framework = frameworks[index % 3]
        pairs.append({
            "pair_id": f"final-pair-{index:02d}", "framework_id": framework["framework_id"],
            "left": {"operator_id": f"left-{index:02d}", "type": f"novel.Left{index}", "configuration": {"index": index}, "source_index_sha256": hashlib.sha256(f"left-source-{index}".encode()).hexdigest()},
            "right": {"operator_id": f"right-{index:02d}", "type": f"novel.Right{index}", "configuration": {"index": index}, "source_index_sha256": hashlib.sha256(f"right-source-{index}".encode()).hexdigest()},
            "input_domain": {"description": "Synthetic administrative input-domain statement only.", "artifact_path": "benchmark/final_v1/reorder_capability_v2.schema.json", "sha256": file_sha256(ROOT / "benchmark/final_v1/reorder_capability_v2.schema.json")},
            "operation_context": {"scope": "one_invocation_each_order", "rng_assignment": "global_sequential" if index % 2 == 0 else "operator_keyed", "state_reset": "same_pre_pair_state", "comparison": "exact_output_definedness_exception_and_rng_post_state", "optimizer_reorder_scope": "adjacent_swap"},
            "source_anchors": [f"synthetic-source:{index}"], "inclusion_reason": "Synthetic quota and workflow coverage only.",
            "contamination": {"seen_during_p5k_p5m": False, "registry_match": False},
        })
    public = {
        "schema_version": "autocontract.reorder-final-public.v0", "artifact_type": "reorder_public_manifest",
        "benchmark_id": "autocontract-reorder-final-selftest", "status": "sealed", "created_at": "2026-07-30T00:00:00Z",
        "selection_author": "synthetic-independent-selftest", "selection_independent_of_analyzer": True,
        "claim_scope": "Synthetic administrative fixture only; no accuracy, independence, or system-benefit evidence.",
        "parent_final_manifest_sha256": None,
        "contamination_registry": {"path": "benchmark/final_v1/contamination_registry.json", "sha256": file_sha256(CONTAMINATION_REGISTRY), "selection_cutoff": "2026-07-30T00:00:00Z"},
        "visibility_policy": {"selector_forbidden": ["analyzer_predictions", "reorder_receipts", "private_oracle", "p5k_p5m_pair_labels"], "annotator_forbidden": ["analyzer_predictions", "reorder_receipts"], "analyzer_allowed": ["sealed_public_manifest", "public_source", "oracle_commitment"], "reveal_precondition": "sealed_predictions_and_verified_commitment"},
        "metric_gates": copy.deepcopy(REQUIRED_GATES), "frameworks": frameworks, "pairs": pairs,
        "analyzer_bundle": [{"name": name, "path": path, "sha256": file_sha256(ROOT / path)} for name, path in analyzer_paths],
    }
    units = []
    for index, pair in enumerate(pairs):
        label = ("commutes", "noncommutes", "unknown")[index % 3]
        witness = None
        premises: list[str] = []
        proof_kind = "unresolved"
        if label == "commutes":
            proof_kind, premises = "manual_source_proof", ["synthetic_premise_only"]
        elif label == "noncommutes":
            proof_kind = "counterexample"
            witness = {"seed": index, "input_sha256": hashlib.sha256(f"input-{index}".encode()).hexdigest(), "original_outcome_sha256": hashlib.sha256(f"original-{index}".encode()).hexdigest(), "swapped_outcome_sha256": hashlib.sha256(f"swapped-{index}".encode()).hexdigest(), "reproduction_command_sha256": hashlib.sha256(f"command-{index}".encode()).hexdigest()}
        units.append({"pair_id": pair["pair_id"], "primary_label": label, "reviewer_label": label, "adjudicated_label": label, "confidence": "high" if label != "unknown" else "low", "proof_kind": proof_kind, "rationale": "Synthetic private rationale for administrative self-test only.", "premises": premises, "evidence_anchors": [f"synthetic-private:{index}"], "counterexample": witness, "reviewed_by": ["reviewer-01"]})
    oracle = {
        "schema_version": "autocontract.reorder-final-oracle.v0", "artifact_type": "reorder_private_oracle",
        "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public),
        "commitment_salt_hex": hashlib.sha256(b"p5n-synthetic-private-salt").hexdigest(),
        "annotators": [{"annotator_id": "primary-01", "role": "primary", "independent_of_analyzer": True, "conflict_disclosure": "synthetic fixture"}, {"annotator_id": "reviewer-01", "role": "reviewer", "independent_of_analyzer": True, "conflict_disclosure": "synthetic fixture"}],
        "units": units, "adjudication": {"status": "complete", "disagreement_count": 0, "record_sha256": hashlib.sha256(b"synthetic-adjudication-record").hexdigest()},
    }
    prediction_pairs = []
    for index, pair in enumerate(pairs):
        supported = index % 3 == 0
        prediction_pairs.append({"pair_id": pair["pair_id"], "status": "supported" if supported else "unknown", "assurance_level": "locally_replayed_versioned_relation_algebra" if supported else "none", "reason": "synthetic_supported" if supported else "synthetic_unknown", "receipt_sha256": hashlib.sha256(f"receipt-{index}".encode()).hexdigest() if supported else None, "generation_ms": 1.0 + index, "adapter_minutes": 0.5})
    prediction = {
        "schema_version": "autocontract.reorder-final-prediction.v0", "artifact_type": "reorder_prediction",
        "benchmark_id": public["benchmark_id"], "public_manifest_sha256": canonical_sha256(public),
        "producer_bundle_sha256": canonical_sha256(public["analyzer_bundle"]), "created_at": "2026-07-30T01:00:00Z", "status": "sealed",
        "pairs": prediction_pairs, "burden": {"total_adapter_minutes": 12.0, "all_pairs_timed": True},
    }
    return public, oracle, prediction


def expect_failure(name: str, action: Callable[[], Any], checks: list[dict[str, Any]]) -> None:
    try:
        action()
    except (ValidationError, jsonschema.ValidationError, KeyError, TypeError, ValueError) as exc:
        checks.append({"name": name, "passed": True, "reason": f"{type(exc).__name__}:{exc}"})
    else:
        checks.append({"name": name, "passed": False, "reason": "unexpected_accept"})


def run_self_test(output_path: Path | None) -> dict[str, Any]:
    protocol = load_json(PROTOCOL)
    checks: list[dict[str, Any]] = []
    observed_frozen = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in protocol["frozen_predecessors"]}
    checks.append({"name": "frozen predecessors exact", "passed": observed_frozen == protocol["frozen_predecessors"], "observed": observed_frozen})
    public, oracle, prediction = make_fixture()
    with tempfile.TemporaryDirectory(prefix="autocontract-p5n-") as directory:
        temp = Path(directory)
        public_path, oracle_path, prediction_path = temp / "public.json", temp / "oracle.json", temp / "prediction.json"
        commitment_path, freeze_path, prediction_seal_path = temp / "commitment.json", temp / "freeze.json", temp / "prediction-seal.json"
        write_json(public_path, public); write_json(oracle_path, oracle); write_json(prediction_path, prediction)
        schema_validate(load_json(PUBLIC_TEMPLATE), PUBLIC_SCHEMA)
        checks.append({"name": "strict public schema and invariants accepted", "passed": validate_public(public, strict=True)["pair_count"] == 24})
        schema_validate(load_json(PRIVATE_TEMPLATE), PRIVATE_SCHEMA)
        checks.append({"name": "strict private schema and invariants accepted", "passed": validate_private(oracle, public)["pair_count"] == 24})
        build_oracle_commitment(oracle_path, public_path, commitment_path)
        checks.append({"name": "oracle commitment created", "passed": commitment_path.is_file()})
        verify_oracle(oracle, public, load_json(commitment_path))
        checks.append({"name": "untampered oracle commitment verified", "passed": True})
        freeze = freeze_public(public_path, commitment_path, freeze_path)
        checks.append({"name": "public freeze binds every analyzer artifact", "passed": len(freeze["analyzer_artifacts"]) == len(public["analyzer_bundle"]) and all(item["sha256"] == file_sha256(ROOT / item["path"]) for item in freeze["analyzer_artifacts"])})
        freeze_text = json.dumps(freeze, ensure_ascii=False)
        checks.append({"name": "public freeze excludes private oracle", "passed": str(oracle_path) not in freeze_text and "adjudicated_label" not in freeze_text and "counterexample" not in freeze_text})
        schema_validate(load_json(PREDICTION_TEMPLATE), PREDICTION_SCHEMA)
        checks.append({"name": "strict prediction schema and invariants accepted", "passed": validate_prediction(prediction, public)["pair_count"] == 24})
        seal_prediction(prediction_path, public_path, prediction_seal_path)
        checks.append({"name": "prediction seal created", "passed": prediction_seal_path.is_file()})
        score = reveal_score(public_path, oracle_path, commitment_path, prediction_path, prediction_seal_path)
        checks.append({"name": "safe reveal passes frozen gates in safety-first order", "passed": score["gate_pass"] and list(score)[:2] == ["unsafe_supported", "unresolved_supported"] and score["denominators"]["unknown"] == 8})

        broken = copy.deepcopy(public); broken["pairs"][0]["label"] = "commutes"
        expect_failure("public label leak rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"][0]["counterexample"] = {"seed": 1}
        expect_failure("public counterexample leak rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["selection_independent_of_analyzer"] = False
        expect_failure("selector independence violation rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"] = broken["pairs"][:19]
        expect_failure("sealed pair quota violation rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"][1]["pair_id"] = broken["pairs"][0]["pair_id"]
        expect_failure("duplicate public pair rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"][0]["contamination"]["registry_match"] = True
        expect_failure("contaminated pair rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"][0]["framework_id"] = "missing-framework"
        expect_failure("unknown framework reference rejected", lambda: validate_public(broken, strict=True), checks)
        broken = copy.deepcopy(public); broken["pairs"][0]["left"]["source_index_sha256"] = "0" * 64
        expect_failure("placeholder source binding rejected", lambda: validate_public(broken, strict=True), checks)

        broken_oracle = copy.deepcopy(oracle); broken_oracle["public_manifest_sha256"] = "f" * 64
        expect_failure("private public-hash mismatch rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"].pop()
        expect_failure("missing private unit rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["annotators"][0]["independent_of_analyzer"] = False
        expect_failure("annotator independence violation rejected", lambda: validate_private(broken_oracle, public), checks)
        non_index = next(index for index, item in enumerate(oracle["units"]) if item["adjudicated_label"] == "noncommutes")
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"][non_index]["counterexample"] = None
        expect_failure("Noncommutes without witness rejected", lambda: validate_private(broken_oracle, public), checks)
        commute_index = next(index for index, item in enumerate(oracle["units"]) if item["adjudicated_label"] == "commutes")
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"][commute_index]["counterexample"] = copy.deepcopy(oracle["units"][non_index]["counterexample"])
        expect_failure("Commutes with counterexample rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["units"][0]["reviewer_label"] = "unknown"; broken_oracle["adjudication"]["disagreement_count"] = 1
        expect_failure("disagreement without adjudicator rejected", lambda: validate_private(broken_oracle, public), checks)
        broken_oracle = copy.deepcopy(oracle); broken_oracle["adjudication"]["disagreement_count"] = 1
        expect_failure("adjudication disagreement count mismatch rejected", lambda: validate_private(broken_oracle, public), checks)
        tampered_oracle = copy.deepcopy(oracle); tampered_oracle["units"][0]["rationale"] += " tampered"
        expect_failure("post-commit oracle tampering rejected", lambda: verify_oracle(tampered_oracle, public, load_json(commitment_path)), checks)

        broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"][0]["oracle_label"] = "commutes"
        expect_failure("prediction label leak rejected", lambda: validate_prediction(broken_prediction, public), checks)
        broken_prediction = copy.deepcopy(prediction); broken_prediction["pairs"].pop()
        expect_failure("missing prediction pair rejected", lambda: validate_prediction(broken_prediction, public), checks)
        tampered_prediction = copy.deepcopy(prediction); tampered_prediction["pairs"][0]["reason"] += " tampered"
        tampered_path = temp / "tampered-prediction.json"; write_json(tampered_path, tampered_prediction)
        expect_failure("post-seal prediction tampering rejected", lambda: reveal_score(public_path, oracle_path, commitment_path, tampered_path, prediction_seal_path), checks)
        unsafe_prediction = copy.deepcopy(prediction)
        unsafe_prediction["pairs"][non_index].update({"status": "supported", "assurance_level": "trusted_revocable_external_proof", "receipt_sha256": hashlib.sha256(b"unsafe-synthetic-receipt").hexdigest(), "reason": "synthetic_unsafe_supported"})
        unsafe_path, unsafe_seal_path = temp / "unsafe-prediction.json", temp / "unsafe-seal.json"
        write_json(unsafe_path, unsafe_prediction); seal_prediction(unsafe_path, public_path, unsafe_seal_path)
        unsafe_score = reveal_score(public_path, oracle_path, commitment_path, unsafe_path, unsafe_seal_path)
        checks.append({"name": "unsafe Supported prediction fails safety gate", "passed": not unsafe_score["gate_pass"] and unsafe_score["unsafe_supported"]["count"] == 1})

    require(len(checks) == 30, f"self-test definition drift: expected 30 checks, got {len(checks)}")
    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5n-reorder-final-handoff-selftest.v0",
        "status": "pass" if passed == len(checks) else "fail", "passed": passed, "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL), "runner_sha256": file_sha256(Path(__file__).resolve()),
        "public_schema_sha256": file_sha256(PUBLIC_SCHEMA), "private_schema_sha256": file_sha256(PRIVATE_SCHEMA), "prediction_schema_sha256": file_sha256(PREDICTION_SCHEMA),
        "synthetic_fixture": {"pairs": 24, "frameworks": 3, "domains": 2, "scientific_evidence": False},
        "checks": checks, "claim_boundary": protocol["claim_boundary"],
    }
    if output_path is not None:
        write_json(output_path, result)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    command = sub.add_parser("validate-public"); command.add_argument("public", type=Path)
    command = sub.add_parser("validate-private"); command.add_argument("private", type=Path); command.add_argument("public", type=Path)
    command = sub.add_parser("commit-oracle"); command.add_argument("private", type=Path); command.add_argument("public", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("freeze-public"); command.add_argument("public", type=Path); command.add_argument("commitment", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("seal-prediction"); command.add_argument("prediction", type=Path); command.add_argument("public", type=Path); command.add_argument("output", type=Path)
    command = sub.add_parser("reveal-score"); command.add_argument("public", type=Path); command.add_argument("private", type=Path); command.add_argument("commitment", type=Path); command.add_argument("prediction", type=Path); command.add_argument("prediction_seal", type=Path)
    command = sub.add_parser("self-test"); command.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate-public": value = validate_public(load_json(args.public), strict=True)
        elif args.command == "validate-private": value = validate_private(load_json(args.private), load_json(args.public))
        elif args.command == "commit-oracle": value = build_oracle_commitment(args.private, args.public, args.output)
        elif args.command == "freeze-public": value = freeze_public(args.public, args.commitment, args.output)
        elif args.command == "seal-prediction": value = seal_prediction(args.prediction, args.public, args.output)
        elif args.command == "reveal-score": value = reveal_score(args.public, args.private, args.commitment, args.prediction, args.prediction_seal)
        else: value = run_self_test(args.output)
    except (OSError, ValidationError, jsonschema.ValidationError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if not isinstance(value, dict) or value.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
