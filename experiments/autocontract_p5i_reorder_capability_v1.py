#!/usr/bin/env python3
"""Calibrate strict, locally replayable ReorderCapabilityV1 on cedar."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5i_reorder_capability_v1_protocol.json"
SCHEMA = ROOT / "benchmark" / "final_v1" / "reorder_capability_v1.schema.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
FROZEN_INPUTS = {
    "outputs/autocontract_p5h_reorder_receipt_trust.json": "057fda1f173f4f94dce50dc37c17798a3ffa0d5702f09faef0b08ab220390419",
    "benchmark/final_v1/p5h_reorder_receipt_trust_protocol.json": "71bfaaf7b5ad3d86a79a7621a1bf44fdf551de9ed55742fdccda58472af5b238",
    "experiments/autocontract_reorder_capability_v0.py": "77da9d207f62a3e732f5242aebf76bcdae43acebf16baa02cbb3f9879d93a5ae",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_one(value: int) -> int:
    return value + 1


def double(value: int) -> int:
    return value * 2


def subtract_three(value: int) -> int:
    return value - 3


def add_two(value: int) -> int:
    return value + 2


def add_three(value: int) -> int:
    return value + 3


def absolute_value(value: int) -> int:
    return abs(value)


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def make_bundle(compiler: Any, v1: Any, functions: list[Callable[[int], int]]) -> tuple[dict[str, Any], dict[str, Callable[[int], int]]]:
    ids = ["decode", "crop", "normalize"]
    operators = []
    mapping: dict[str, Callable[[int], int]] = {}
    for operator_id, function in zip(ids, functions, strict=True):
        mapping[operator_id] = function
        operators.append(compiler.make_operator(
            operator_id,
            source_index_sha256=v1.callable_source_sha256(function),
            contract_sha256=hashlib.sha256(f"contract:{operator_id}:{function.__name__}".encode("utf-8")).hexdigest(),
        ))
    pipeline = compiler.make_pipeline(operators, operation="adjacent_reorder")
    return compiler.compile_constraints(pipeline), mapping


def ordered_path(graph: dict[int, set[int]], source: int = 3) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        if len(graph[current]) != 1:
            raise ValueError("fixture graph is not linear")
        current = next(iter(graph[current]))
        path.append(current)
    return path


def execute_cedar(
    cedar_root: Path,
    bundle: dict[str, Any],
    functions: list[Callable[[int], int]],
    source: list[int],
    *,
    optimize: bool,
) -> dict[str, Any]:
    from cedar.compose import Feature, OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    recipe = bundle["backends"]["cedar"]["operators"]

    class StrictCapabilityFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, function in zip(recipe, functions, strict=True):
                pipe = MapperPipe(pipe, function, tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
                if item["depends_on"]:
                    pipe = pipe.depends_on(item["depends_on"])
            return pipe

    feature = StrictCapabilityFeature()
    feature.apply(IterSource(source))
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
        iterator = feature.load_from_plan(CedarContext(), plan)
    else:
        path = ordered_path(feature.logical_adj_list)
        iterator = feature.load(CedarContext(), prefetch=False)
    return {
        "candidate_count": len(candidates),
        "path": path,
        "output": [sample.data for sample in iterator],
        "fix": [item["fix"] for item in recipe],
        "regions": bundle["reorder_capability"]["regions"],
    }


def all_verified_receipts(v1: Any, bundle: dict[str, Any], mapping: dict[str, Callable[[int], int]]) -> list[dict[str, Any]]:
    ids = [item["operator_id"] for item in bundle["operators"]]
    return [
        v1.make_verified_receipt(bundle, ids[left], ids[right], mapping)
        for left in range(len(ids))
        for right in range(left + 1, len(ids))
    ]


def one_candidate(bundle: dict[str, Any]) -> bool:
    return [item["fix"] for item in bundle["backends"]["cedar"]["operators"]] == [True, True, True]


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "upstream_worktree_is_clean", status == "", status or "clean")
    frozen = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in FROZEN_INPUTS}
    append_check(checks, "p5h_and_v0_frozen_inputs_unchanged", frozen == FROZEN_INPUTS, frozen)
    p5h = json.loads((ROOT / "outputs" / "autocontract_p5h_reorder_receipt_trust.json").read_text(encoding="utf-8"))
    append_check(checks, "p5h_attack_was_reproduced_as_failure", p5h["system_verdict"] == "fail_unverified_receipt_trust_boundary" and p5h["attack"]["candidate_count"] == 6, p5h["system_verdict"])
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    append_check(checks, "schema_requires_local_replay_assurance", schema["properties"]["assurance_level"]["const"] == "locally_replayed_restricted_static")

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_reorder_capability_v0 as v0
    import autocontract_reorder_capability_v1 as v1

    noncommuting_functions = [add_one, double, subtract_three]
    noncommuting_base, noncommuting_mapping = make_bundle(compiler, v1, noncommuting_functions)
    forged_v0 = [
        v0.make_receipt(noncommuting_base, left, right, proof_label=f"forged:{left}:{right}")
        for left, right in (("decode", "crop"), ("decode", "normalize"), ("crop", "normalize"))
    ]
    forged_rejected = v1.compile_reorder_safe_strict(noncommuting_base, forged_v0, noncommuting_mapping)
    append_check(checks, "strict_v1_rejects_p5h_style_v0_assertions", one_candidate(forged_rejected) and not forged_rejected["proof_verification"]["verified_pairs"], forged_rejected["proof_verification"])

    established: list[dict[str, Any]] = []
    rejected_pairs: list[dict[str, str]] = []
    for left, right in (("decode", "crop"), ("decode", "normalize"), ("crop", "normalize")):
        try:
            established.append(v1.make_verified_receipt(noncommuting_base, left, right, noncommuting_mapping))
        except v1.ReorderCapabilityV1Error as exc:
            rejected_pairs.append({"pair": f"{left}<->{right}", "reason": str(exc)})
    append_check(checks, "noncommuting_pipeline_cannot_obtain_complete_proof_cover", len(established) == 1 and len(rejected_pairs) == 2, {"established": len(established), "rejected": rejected_pairs})
    noncommuting_strict = v1.compile_reorder_safe_strict(noncommuting_base, established, noncommuting_mapping)
    noncommuting_runtime = execute_cedar(cedar_root, noncommuting_strict, noncommuting_functions, [0, 1, 2, 3, 4], optimize=True)
    append_check(checks, "incomplete_noncommuting_proofs_keep_one_safe_plan", noncommuting_runtime["candidate_count"] == 1 and noncommuting_runtime["path"] == [3, 2, 1, 0], noncommuting_runtime)
    append_check(checks, "noncommuting_output_is_preserved", noncommuting_runtime["output"] == [-1, 1, 3, 5, 7], noncommuting_runtime["output"])

    commuting_functions = [add_one, add_two, add_three]
    commuting_base, commuting_mapping = make_bundle(compiler, v1, commuting_functions)
    receipts = all_verified_receipts(v1, commuting_base, commuting_mapping)
    append_check(checks, "three_affine_translation_pairs_are_proved", len(receipts) == 3 and all(receipt["proof_artifact"]["equality"] for receipt in receipts), receipts)
    schema_validation_ok = True
    schema_validation_error = None
    try:
        for receipt in receipts:
            jsonschema.validate(instance=receipt, schema=schema)
    except jsonschema.ValidationError as exc:
        schema_validation_ok = False
        schema_validation_error = exc.message
    append_check(checks, "emitted_receipts_validate_against_public_schema", schema_validation_ok, schema_validation_error)
    admitted = v1.compile_reorder_safe_strict(commuting_base, receipts, commuting_mapping)
    append_check(checks, "strict_local_replay_admits_complete_region", admitted["proof_verification"]["verified_pairs"] == [["crop", "decode"], ["decode", "normalize"], ["crop", "normalize"]] and admitted["reorder_capability"]["regions"] == [{"operator_ids": ["decode", "crop", "normalize"], "admitted": True, "reason": "pairwise_complete_supported"}], admitted["proof_verification"])
    baseline = execute_cedar(cedar_root, v1.compile_reorder_safe_strict(commuting_base, [], commuting_mapping), commuting_functions, [0, 1, 2, 3, 4], optimize=False)
    optimized = execute_cedar(cedar_root, admitted, commuting_functions, [0, 1, 2, 3, 4], optimize=True)
    append_check(checks, "verified_receipts_restore_six_cedar_candidates", optimized["candidate_count"] == 6 and optimized["path"] == [3, 0, 1, 2], optimized)
    append_check(checks, "verified_reorder_preserves_runtime_output", baseline["output"] == optimized["output"] == [6, 7, 8, 9, 10], {"baseline": baseline["output"], "optimized": optimized["output"]})

    artifact_tamper = copy.deepcopy(receipts)
    artifact_tamper[0]["proof_artifact"]["left_ir"]["intercept"]["numerator"] += 10
    artifact_tamper[0]["proof_sha256"] = v0.canonical_sha256(artifact_tamper[0]["proof_artifact"])
    artifact_result = v1.compile_reorder_safe_strict(commuting_base, [artifact_tamper[0]], commuting_mapping)
    append_check(checks, "self_consistent_but_false_artifact_fails_replay", one_candidate(artifact_result) and not artifact_result["proof_verification"]["verified_pairs"], artifact_result["proof_verification"])

    digest_tamper = copy.deepcopy(receipts)
    digest_tamper[0]["proof_sha256"] = "0" * 64
    digest_result = v1.compile_reorder_safe_strict(commuting_base, [digest_tamper[0]], commuting_mapping)
    append_check(checks, "proof_digest_tamper_fails_closed", one_candidate(digest_result), digest_result["proof_verification"])

    version_tamper = copy.deepcopy(receipts)
    version_tamper[0]["verifier"]["version"] = "999.0.0"
    version_result = v1.compile_reorder_safe_strict(commuting_base, [version_tamper[0]], commuting_mapping)
    append_check(checks, "verifier_version_tamper_fails_closed", one_candidate(version_result), version_result["proof_verification"])

    verifier_tamper = copy.deepcopy(receipts)
    verifier_tamper[0]["verifier"]["source_sha256"] = "f" * 64
    verifier_result = v1.compile_reorder_safe_strict(commuting_base, [verifier_tamper[0]], commuting_mapping)
    append_check(checks, "verifier_source_tamper_fails_closed", one_candidate(verifier_result), verifier_result["proof_verification"])

    drifted = copy.deepcopy(commuting_base)
    drift_hash = hashlib.sha256(b"source-drift").hexdigest()
    drifted["operators"][0]["source_index_sha256"] = drift_hash
    drifted["backends"]["cedar"]["operators"][0]["source_index_sha256"] = drift_hash
    drift_result = v1.compile_reorder_safe_strict(drifted, [receipts[1]], commuting_mapping)
    append_check(checks, "source_index_drift_fails_closed", one_candidate(drift_result) and not drift_result["proof_verification"]["verified_pairs"], drift_result["proof_verification"])

    revoked = {receipts[0]["verifier"]["source_sha256"]}
    revoked_result = v1.compile_reorder_safe_strict(commuting_base, receipts, commuting_mapping, revoked_verifier_source_sha256=revoked)
    append_check(checks, "revoked_verifier_build_fails_closed", one_candidate(revoked_result) and not revoked_result["proof_verification"]["verified_pairs"], revoked_result["proof_verification"])

    duplicate_result = v1.compile_reorder_safe_strict(commuting_base, [receipts[0], copy.deepcopy(receipts[0])], commuting_mapping)
    append_check(checks, "duplicate_receipt_is_ambiguous_and_fails_closed", one_candidate(duplicate_result) and not duplicate_result["proof_verification"]["verified_pairs"], duplicate_result["proof_verification"])

    unsupported_base, unsupported_mapping = make_bundle(compiler, v1, [add_one, absolute_value, add_three])
    unsupported_reason = None
    try:
        v1.make_verified_receipt(unsupported_base, "decode", "crop", unsupported_mapping)
    except v1.ReorderCapabilityV1Error as exc:
        unsupported_reason = str(exc)
    unsupported_result = v1.compile_reorder_safe_strict(unsupported_base, [], unsupported_mapping)
    append_check(checks, "unsupported_call_expression_is_unknown_and_fixed", unsupported_reason == "unsupported_expression:Call" and one_candidate(unsupported_result), unsupported_reason)

    append_check(checks, "strict_output_contains_no_optimizer_decisions", not v0.contains_decision_fields(admitted))
    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5i-reorder-capability-v1-result.v0",
        "status": "pass" if passed == len(checks) else "fail",
        "system_verdict": "pass_local_replay_closes_p5h_for_restricted_affine_scope" if passed == len(checks) else "fail_strict_v1_calibration",
        "passed": passed,
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "schema_sha256": file_sha256(SCHEMA),
        "module_sha256": file_sha256(ROOT / "experiments" / "autocontract_reorder_capability_v1.py"),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "checks": checks,
        "cases": {
            "p5h_style_forgery": forged_rejected["proof_verification"],
            "noncommuting_strict": noncommuting_runtime,
            "commuting_baseline": baseline,
            "commuting_verified_optimized": optimized,
        },
        "claim_boundary": "Restricted-static mechanism calibration only. This closes untrusted receipt acceptance for the implemented affine integer subset; real ML operator coverage and independent validation remain open.",
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
    except (OSError, ValueError, KeyError, AttributeError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
