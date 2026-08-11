#!/usr/bin/env python3
"""Compile frozen AutoContract decisions into backend-shaped safety hints.

The output is deliberately not an optimizer plan.  It contains no cost,
placement, tier, storage-size, worker-count, or ILP decisions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5a_constraint_compiler_protocol_v2.json"
SCHEMA = ROOT / "benchmark" / "final_v1" / "optimizer_constraint_bundle_v0.schema.json"
HEX64 = set("0123456789abcdef")

FROZEN_INPUTS = {
    "experiments/autocontract_h7h_effect_v7.py": "3aa49f7d40e1b4f09d61ed42364a338a0892f25f2b0f1006749159ac82e84b84",
    "benchmark/final_v1/replay_capability_v1.schema.json": "40cd2d57c266631f73a34efe535d584cbf316eb98c20f14b5479aca6a739e667",
    "experiments/autocontract_r3_source_index_v1.py": "7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c",
    "benchmark/final_v2/public_manifest.schema.json": "3fadc4bf051cbc96bd20009580a309ab8df6831f2d72eb8dc5508987392704a6",
    ".research/semantics_safe_reconfiguration/p4_literature_and_github_pressure_test_2026-07-30.zh-CN.md": "8b92b235b3b6853aa0355422e1e4a40c549bdbcbece0cbfe76db3d0116c86777",
}

INPUT_TOP_KEYS = {"pipeline_id", "operation_context", "input_schema_sha256", "operators"}
CONTEXT_KEYS = {"operation", "lifecycle_phase", "configuration_sha256"}
OPERATOR_KEYS = {
    "operator_id", "symbol_id", "semantic_status", "semantic_reason",
    "randomness", "execution_state", "external_io", "cardinality",
    "source_status", "source_index_sha256", "contract_sha256", "depends_on",
    "replay_capability_status",
}


class ConstraintError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ConstraintError(message)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX64


def exact_keys(value: Any, keys: set[str], where: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{where}_must_be_object")
    require(set(value) == keys, f"{where}_keys_mismatch")
    return value


def validate_input(pipeline: dict[str, Any]) -> None:
    exact_keys(pipeline, INPUT_TOP_KEYS, "pipeline")
    require(isinstance(pipeline["pipeline_id"], str) and pipeline["pipeline_id"], "pipeline_id_required")
    context = exact_keys(pipeline["operation_context"], CONTEXT_KEYS, "operation_context")
    require(context["operation"] in {"contract_inference", "sample_apply", "replay_apply", "cache_write", "adjacent_reorder", "training_step"}, "bad_operation")
    require(context["lifecycle_phase"] in {"construction", "iteration", "training", "evaluation", "serving"}, "bad_lifecycle_phase")
    require(is_sha256(context["configuration_sha256"]), "bad_configuration_sha256")
    require(is_sha256(pipeline["input_schema_sha256"]), "bad_input_schema_sha256")
    operators = pipeline["operators"]
    require(isinstance(operators, list) and operators, "operators_required")
    ids: list[str] = []
    for index, operator in enumerate(operators):
        where = f"operators[{index}]"
        exact_keys(operator, OPERATOR_KEYS, where)
        for name in ("operator_id", "symbol_id", "semantic_reason"):
            require(isinstance(operator[name], str) and operator[name], f"{where}_{name}_required")
        ids.append(operator["operator_id"])
        require(operator["semantic_status"] in {"admit", "reject", "unknown"}, f"{where}_bad_semantic_status")
        require(operator["randomness"] in {"none", "sampling", "replay_only", "unknown"}, f"{where}_bad_randomness")
        require(operator["execution_state"] in {"none", "read", "write", "unknown"}, f"{where}_bad_execution_state")
        require(operator["external_io"] in {"none", "read", "write", "unknown"}, f"{where}_bad_external_io")
        require(operator["cardinality"] in {"one_to_one", "one_to_many", "many_to_one", "filter", "unknown"}, f"{where}_bad_cardinality")
        require(operator["source_status"] in {"supported", "reject", "unknown"}, f"{where}_bad_source_status")
        require(operator["replay_capability_status"] in {"supported", "unsupported", "unknown", "not_applicable"}, f"{where}_bad_replay_status")
        require(is_sha256(operator["source_index_sha256"]) and is_sha256(operator["contract_sha256"]), f"{where}_bad_digest")
        require(isinstance(operator["depends_on"], list) and all(isinstance(dep, str) for dep in operator["depends_on"]), f"{where}_bad_dependencies")
    require(len(ids) == len(set(ids)), "duplicate_operator_id")
    known = set(ids)
    for operator in operators:
        require(set(operator["depends_on"]) <= known, f"{operator['operator_id']}_unknown_dependency")
        require(operator["operator_id"] not in operator["depends_on"], f"{operator['operator_id']}_self_dependency")


def barrier_reasons(operator: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if operator["semantic_status"] != "admit":
        reasons.append(f"semantic_{operator['semantic_status']}:{operator['semantic_reason']}")
    if operator["source_status"] != "supported":
        reasons.append(f"source_{operator['source_status']}")
    for name in ("randomness", "execution_state", "external_io", "cardinality"):
        if operator[name] == "unknown":
            reasons.append(f"{name}_unknown")
    if operator["execution_state"] in {"read", "write"}:
        reasons.append(f"execution_state_{operator['execution_state']}")
    if operator["external_io"] in {"read", "write"}:
        reasons.append(f"external_io_{operator['external_io']}")
    if operator["cardinality"] != "one_to_one" and operator["cardinality"] != "unknown":
        reasons.append(f"cardinality_{operator['cardinality']}")
    return reasons


def strict_cache_eligible(operator: dict[str, Any]) -> bool:
    return (
        operator["semantic_status"] == "admit"
        and operator["source_status"] == "supported"
        and operator["randomness"] == "none"
        and operator["execution_state"] == "none"
        and operator["external_io"] == "none"
        and operator["cardinality"] == "one_to_one"
    )


def compile_constraints(pipeline: dict[str, Any]) -> dict[str, Any]:
    validate_input(pipeline)
    context_digest = canonical_sha256(pipeline["operation_context"])
    contract_digest = canonical_sha256({
        "pipeline_id": pipeline["pipeline_id"],
        "operation_context": pipeline["operation_context"],
        "input_schema_sha256": pipeline["input_schema_sha256"],
        "operators": pipeline["operators"],
    })
    normalized: list[dict[str, Any]] = []
    cedar_operators: list[dict[str, Any]] = []
    hycache_steps: list[dict[str, Any]] = []
    safe_prefix: list[str] = []
    prefix_open = True
    first_prefix_blocker: str | None = None
    for operator in pipeline["operators"]:
        eligible = strict_cache_eligible(operator)
        reasons = barrier_reasons(operator)
        barrier = bool(reasons)
        parameter_key = operator["randomness"] == "replay_only"
        effective_cache_point = prefix_open and eligible
        if not eligible and prefix_open:
            first_prefix_blocker = operator["operator_id"]
        normalized.append({
            "operator_id": operator["operator_id"],
            "strict_cache_eligible": effective_cache_point,
            "barrier": barrier,
            "barrier_reasons": reasons,
            "parameter_key_required": parameter_key,
            "contract_sha256": operator["contract_sha256"],
            "source_index_sha256": operator["source_index_sha256"],
        })
        cedar_operators.append({
            "operator_id": operator["operator_id"],
            "tag": f"autocontract:{operator['operator_id']}",
            "random": operator["randomness"] in {"sampling", "unknown"},
            "fix": barrier,
            "depends_on": [f"autocontract:{dep}" for dep in operator["depends_on"]],
            "contract_sha256": operator["contract_sha256"],
            "source_index_sha256": operator["source_index_sha256"],
        })
        backend_reasons = ([] if eligible else reasons + (["sampling_rng"] if operator["randomness"] == "sampling" else []) + (["parameter_key_not_supported"] if parameter_key else []))
        if eligible and not prefix_open:
            backend_reasons = [f"upstream_noncacheable:{first_prefix_blocker}"]
        hycache_steps.append({
            "operator_id": operator["operator_id"],
            "online_only": not effective_cache_point,
            "reason_codes": backend_reasons,
        })
        if prefix_open and eligible:
            safe_prefix.append(operator["operator_id"])
        else:
            prefix_open = False
    boundary = safe_prefix[-1] if safe_prefix else None
    return {
        "schema_version": "autocontract.optimizer-constraint-bundle.v0",
        "pipeline_id": pipeline["pipeline_id"],
        "operation_context_sha256": context_digest,
        "contract_bundle_sha256": contract_digest,
        "input_schema_sha256": pipeline["input_schema_sha256"],
        "operators": normalized,
        "backends": {
            "cedar": {
                "interface": "random/fix/depends_on hints",
                "operators": cedar_operators,
                "constraint_only": True,
            },
            "hycache": {
                "interface": "online_only plus cache_steps boundary",
                "steps": hycache_steps,
                "safe_contiguous_prefix": safe_prefix,
                "cache_steps_boundary_after": boundary,
                "constraint_only": True,
            },
            "cachew": {
                "interface": "autocache boundary",
                "safe_contiguous_prefix": safe_prefix,
                "autocache_after": boundary,
                "constraint_only": True,
            },
        },
        "claim_boundary": "Safety constraints only; the target optimizer retains all cost, placement, tier, capacity, and execution decisions.",
    }


def validate_output(bundle: dict[str, Any]) -> None:
    exact_keys(bundle, {"schema_version", "pipeline_id", "operation_context_sha256", "contract_bundle_sha256", "input_schema_sha256", "operators", "backends", "claim_boundary"}, "output")
    require(bundle["schema_version"] == "autocontract.optimizer-constraint-bundle.v0", "bad_output_version")
    for key in ("operation_context_sha256", "contract_bundle_sha256", "input_schema_sha256"):
        require(is_sha256(bundle[key]), f"bad_output_{key}")
    exact_keys(bundle["backends"], {"cedar", "hycache", "cachew"}, "output_backends")
    require(isinstance(bundle["operators"], list) and bundle["operators"], "output_operators_required")
    for item in bundle["operators"]:
        exact_keys(item, {"operator_id", "strict_cache_eligible", "barrier", "barrier_reasons", "parameter_key_required", "contract_sha256", "source_index_sha256"}, "output_operator")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_operator(operator_id: str, **updates: Any) -> dict[str, Any]:
    value = {
        "operator_id": operator_id,
        "symbol_id": f"fixture.{operator_id}",
        "semantic_status": "admit",
        "semantic_reason": "all_effect_obligations_satisfied",
        "randomness": "none",
        "execution_state": "none",
        "external_io": "none",
        "cardinality": "one_to_one",
        "source_status": "supported",
        "source_index_sha256": digest(f"source:{operator_id}"),
        "contract_sha256": digest(f"contract:{operator_id}"),
        "depends_on": [],
        "replay_capability_status": "not_applicable",
    }
    value.update(updates)
    return value


def make_pipeline(operators: list[dict[str, Any]], *, operation: str = "sample_apply", phase: str = "iteration") -> dict[str, Any]:
    return {
        "pipeline_id": "synthetic-interface-fixture",
        "operation_context": {"operation": operation, "lifecycle_phase": phase, "configuration_sha256": digest(f"config:{operation}:{phase}")},
        "input_schema_sha256": digest("input-schema"),
        "operators": operators,
    }


def frozen_inputs_unchanged() -> dict[str, bool]:
    return {relative: (ROOT / relative).is_file() and file_sha256(ROOT / relative) == expected for relative, expected in FROZEN_INPUTS.items()}


def no_decision_fields(value: Any) -> bool:
    forbidden = {"cost", "placement", "tier", "worker_count", "cache_size", "ilp_solution"}
    if isinstance(value, dict):
        return not (set(value) & forbidden) and all(no_decision_fields(child) for child in value.values())
    if isinstance(value, list):
        return all(no_decision_fields(child) for child in value)
    return True


def run_self_test(output_path: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    pure = make_pipeline([make_operator("decode"), make_operator("resize", depends_on=["decode"]), make_operator("normalize", depends_on=["resize"])])
    pure_out = compile_constraints(pure); validate_output(pure_out)
    checks.append({"name": "pure_three_step_pipeline_exposes_full_safe_prefix", "passed": pure_out["backends"]["hycache"]["safe_contiguous_prefix"] == ["decode", "resize", "normalize"] and pure_out["backends"]["cachew"]["autocache_after"] == "normalize"})

    sampling = make_pipeline([make_operator("decode"), make_operator("crop", randomness="sampling"), make_operator("normalize")])
    sampling_out = compile_constraints(sampling)
    crop_hint = sampling_out["backends"]["cedar"]["operators"][1]
    checks.append({"name": "sampling_rng_marks_cedar_random_and_stops_cache_prefix", "passed": crop_hint["random"] is True and sampling_out["backends"]["hycache"]["cache_steps_boundary_after"] == "decode"})

    replay = make_pipeline([make_operator("random_affine", randomness="replay_only", replay_capability_status="supported")], operation="replay_apply")
    replay_out = compile_constraints(replay)
    checks.append({"name": "replay_only_requires_parameter_key_and_does_not_become_plain_cacheable", "passed": replay_out["operators"][0]["parameter_key_required"] is True and replay_out["operators"][0]["strict_cache_eligible"] is False and replay_out["backends"]["hycache"]["steps"][0]["online_only"] is True})

    semantic_unknown = compile_constraints(make_pipeline([make_operator("opaque", semantic_status="unknown", semantic_reason="unresolved_dispatch")]))
    checks.append({"name": "semantic_unknown_emits_fix_barrier", "passed": semantic_unknown["operators"][0]["barrier"] is True and semantic_unknown["backends"]["cedar"]["operators"][0]["fix"] is True})

    source_unknown = compile_constraints(make_pipeline([make_operator("native", source_status="unknown")]))
    checks.append({"name": "source_unknown_emits_fix_barrier", "passed": source_unknown["operators"][0]["barrier"] is True and "source_unknown" in source_unknown["operators"][0]["barrier_reasons"]})

    external = compile_constraints(make_pipeline([make_operator("file_lookup", external_io="read")]))
    checks.append({"name": "external_io_blocks_cache", "passed": external["operators"][0]["strict_cache_eligible"] is False and external["backends"]["cachew"]["autocache_after"] is None})

    stateful = compile_constraints(make_pipeline([make_operator("counter", execution_state="write")]))
    checks.append({"name": "execution_state_write_blocks_cache", "passed": stateful["operators"][0]["strict_cache_eligible"] is False and stateful["backends"]["cedar"]["operators"][0]["fix"] is True})

    dependency = compile_constraints(pure)
    checks.append({"name": "explicit_dependencies_are_preserved", "passed": dependency["backends"]["cedar"]["operators"][1]["depends_on"] == ["autocontract:decode"] and dependency["backends"]["cedar"]["operators"][2]["depends_on"] == ["autocontract:resize"]})

    sample_phase = compile_constraints(make_pipeline([make_operator("affine", symbol_id="fixture.RandomAffine", randomness="sampling")], operation="sample_apply"))
    replay_phase = compile_constraints(make_pipeline([make_operator("affine", symbol_id="fixture.RandomAffine", randomness="replay_only", replay_capability_status="supported")], operation="replay_apply"))
    checks.append({"name": "operation_phase_contrast_changes_hints_without_changing_symbol_identity", "passed": sample_phase["backends"]["cedar"]["operators"][0]["random"] is True and replay_phase["backends"]["cedar"]["operators"][0]["random"] is False and replay_phase["operators"][0]["parameter_key_required"] is True and sample_phase["operation_context_sha256"] != replay_phase["operation_context_sha256"]})

    dimensions = ["randomness", "execution_state", "external_io", "cardinality"]
    monotone = True
    observations = []
    base_count = len(pure_out["backends"]["hycache"]["safe_contiguous_prefix"])
    for dimension in dimensions:
        weakened = copy.deepcopy(pure)
        weakened["operators"][1][dimension] = "unknown"
        out = compile_constraints(weakened)
        count = len(out["backends"]["hycache"]["safe_contiguous_prefix"])
        observations.append({"dimension": dimension, "safe_prefix_count": count})
        monotone = monotone and count <= base_count and count == 1
    checks.append({"name": "weakening_any_dimension_to_unknown_never_increases_cache_candidates", "passed": monotone, "observed": observations})

    checks.append({"name": "output_contains_no_cost_or_placement_decision_fields", "passed": no_decision_fields(pure_out)})
    frozen = frozen_inputs_unchanged()
    checks.append({"name": "frozen_inputs_unchanged", "passed": all(frozen.values()), "observed": frozen})

    checks.append({"name": "sampling_rng_taints_all_downstream_materialization_points", "passed": sampling_out["backends"]["hycache"]["steps"][1]["online_only"] is True and sampling_out["backends"]["hycache"]["steps"][2]["online_only"] is True and sampling_out["operators"][2]["strict_cache_eligible"] is False and sampling_out["backends"]["hycache"]["steps"][2]["reason_codes"] == ["upstream_noncacheable:crop"]})

    replay_chain = compile_constraints(make_pipeline([make_operator("decode"), make_operator("affine", randomness="replay_only", replay_capability_status="supported"), make_operator("normalize")], operation="replay_apply"))
    checks.append({"name": "replay_only_taints_all_downstream_plain_cache_points", "passed": replay_chain["operators"][1]["parameter_key_required"] is True and replay_chain["backends"]["hycache"]["steps"][2]["online_only"] is True and replay_chain["backends"]["cachew"]["autocache_after"] == "decode"})

    unknown_chain = compile_constraints(make_pipeline([make_operator("decode"), make_operator("opaque", semantic_status="unknown", semantic_reason="unresolved_dispatch"), make_operator("normalize")]))
    checks.append({"name": "unknown_taints_all_downstream_materialization_points", "passed": unknown_chain["backends"]["hycache"]["steps"][1]["online_only"] is True and unknown_chain["backends"]["hycache"]["steps"][2]["online_only"] is True and unknown_chain["backends"]["cachew"]["autocache_after"] == "decode"})

    result = {
        "schema_version": "autocontract.p5a-constraint-compiler-selftest.v0",
        "status": "pass" if all(check["passed"] for check in checks) else "fail",
        "passed": sum(bool(check["passed"]) for check in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "schema_sha256": file_sha256(SCHEMA),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "checks": checks,
        "example_bundle": sampling_out,
        "note": "Synthetic interface conformance only; target backends were not imported or executed.",
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "top_level_must_be_object")
    return value


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("self-test")
    command.add_argument("--output", type=Path)
    command = sub.add_parser("compile")
    command.add_argument("input", type=Path)
    command.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.command == "self-test":
            result = run_self_test(args.output)
        else:
            result = compile_constraints(load_json(args.input))
            validate_output(result)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ConstraintError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
