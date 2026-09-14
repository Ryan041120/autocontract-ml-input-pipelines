#!/usr/bin/env python3
"""Calibrate ReorderCapabilityV0 and its fail-closed cedar integration."""

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


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5g_reorder_capability_protocol.json"
SCHEMA = ROOT / "benchmark" / "final_v1" / "reorder_capability_v0.schema.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
LOCAL_FROZEN = {
    "outputs/autocontract_p5f_reorder_unsoundness.json": "83076a5667e219c334e10402ddad8b1ef813a3ab6264ed5f5a67e175cca16eff",
    "experiments/autocontract_p5a_constraint_compiler.py": "c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_digest(function: Callable[[int], int]) -> str:
    return hashlib.sha256(inspect.getsource(function).encode("utf-8")).hexdigest()


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


def ordered_path(graph: dict[int, set[int]], source: int = 3) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        if len(graph[current]) != 1:
            raise ValueError("fixture graph is not linear")
        current = next(iter(graph[current]))
        path.append(current)
    return path


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def make_bound_bundle(compiler: Any, functions: list[Callable[[int], int]], *, barrier_index: int | None = None, dependency: bool = False) -> dict[str, Any]:
    ids = ["decode", "crop", "normalize"]
    operators = []
    for index, (operator_id, function) in enumerate(zip(ids, functions, strict=True)):
        updates: dict[str, Any] = {
            "source_index_sha256": source_digest(function),
            "contract_sha256": hashlib.sha256(f"contract:{operator_id}:{function.__name__}".encode("utf-8")).hexdigest(),
        }
        if index == barrier_index:
            updates.update(semantic_status="unknown", semantic_reason="fixture_unknown")
        if dependency and operator_id == "normalize":
            updates["depends_on"] = ["decode"]
        operators.append(compiler.make_operator(operator_id, **updates))
    return compiler.compile_constraints(compiler.make_pipeline(operators, operation="adjacent_reorder"))


def all_pair_receipts(capability: Any, bundle: dict[str, Any], *, status: str = "supported") -> list[dict[str, Any]]:
    ids = [item["operator_id"] for item in bundle["operators"]]
    return [
        capability.make_receipt(bundle, ids[left], ids[right], status=status, proof_label=f"pair:{ids[left]}:{ids[right]}:{status}")
        for left in range(len(ids))
        for right in range(left + 1, len(ids))
    ]


def execute_cedar_case(
    cedar_root: Path,
    safe_bundle: dict[str, Any],
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

    recipe = safe_bundle["backends"]["cedar"]["operators"]

    class CapabilityFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, function in zip(recipe, functions, strict=True):
                pipe = MapperPipe(pipe, function, tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
                if item["depends_on"]:
                    pipe = pipe.depends_on(item["depends_on"])
            return pipe

    feature = CapabilityFeature()
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
        "depends_on": [item["depends_on"] for item in recipe],
        "regions": safe_bundle["reorder_capability"]["regions"],
    }


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    status = subprocess.run(["git", "-C", str(cedar_root), "status", "--porcelain=v1"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "upstream_worktree_is_clean", status == "", status or "clean")
    local = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in LOCAL_FROZEN}
    append_check(checks, "frozen_failure_and_compiler_unchanged", local == LOCAL_FROZEN, local)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    append_check(checks, "schema_declares_exact_receipt_version", schema["properties"]["schema_version"]["const"] == "autocontract.reorder-capability.v0")

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_reorder_capability_v0 as capability
    from cedar.compose.utils import calculate_reorderings

    noncommuting_functions = [add_one, double, subtract_three]
    noncommuting_base = make_bound_bundle(compiler, noncommuting_functions)
    fail_closed = capability.compile_reorder_safe(noncommuting_base, [])
    append_check(checks, "no_receipt_fixes_all_noncommutative_operators", [item["fix"] for item in fail_closed["backends"]["cedar"]["operators"]] == [True, True, True])
    baseline = execute_cedar_case(cedar_root, fail_closed, noncommuting_functions, [0, 1, 2, 3, 4], optimize=False)
    repaired = execute_cedar_case(cedar_root, fail_closed, noncommuting_functions, [0, 1, 2, 3, 4], optimize=True)
    append_check(checks, "p5f_repaired_candidate_space_is_one", repaired["candidate_count"] == 1, repaired)
    append_check(checks, "p5f_repaired_plan_preserves_order", repaired["path"] == [3, 2, 1, 0], repaired["path"])
    append_check(checks, "p5f_repaired_output_matches_baseline", repaired["output"] == baseline["output"] == [-1, 1, 3, 5, 7], {"baseline": baseline["output"], "repaired": repaired["output"]})

    commuting_functions = [add_one, add_two, add_three]
    commuting_base = make_bound_bundle(compiler, commuting_functions)
    receipts = all_pair_receipts(capability, commuting_base)
    capability.validate_receipt(receipts[0])
    append_check(checks, "standard_library_validator_accepts_valid_receipt", True, receipts[0])
    admitted = capability.compile_reorder_safe(commuting_base, receipts)
    append_check(checks, "complete_receipts_admit_three_operator_region", admitted["reorder_capability"]["regions"] == [{"operator_ids": ["decode", "crop", "normalize"], "admitted": True, "reason": "pairwise_complete_supported"}], admitted["reorder_capability"]["regions"])
    commuting_baseline_safe = capability.compile_reorder_safe(commuting_base, [])
    commuting_baseline = execute_cedar_case(cedar_root, commuting_baseline_safe, commuting_functions, [0, 1, 2, 3, 4], optimize=False)
    commuting_optimized = execute_cedar_case(cedar_root, admitted, commuting_functions, [0, 1, 2, 3, 4], optimize=True)
    append_check(checks, "commuting_receipts_restore_six_plan_space", commuting_optimized["candidate_count"] == 6, commuting_optimized)
    append_check(checks, "commuting_optimizer_reorders", commuting_optimized["path"] == [3, 0, 1, 2], commuting_optimized["path"])
    append_check(checks, "commuting_reorder_preserves_output", commuting_optimized["output"] == commuting_baseline["output"] == [6, 7, 8, 9, 10], {"baseline": commuting_baseline["output"], "optimized": commuting_optimized["output"]})

    missing = capability.compile_reorder_safe(commuting_base, receipts[:-1])
    append_check(checks, "missing_pair_prevents_full_three_operator_region", not any(region["admitted"] and len(region["operator_ids"]) == 3 for region in missing["reorder_capability"]["regions"]), missing["reorder_capability"]["regions"])

    drifted = copy.deepcopy(commuting_base)
    drift_hash = hashlib.sha256(b"drifted-source").hexdigest()
    drifted["operators"][0]["source_index_sha256"] = drift_hash
    drifted["backends"]["cedar"]["operators"][0]["source_index_sha256"] = drift_hash
    drift_result = capability.compile_reorder_safe(drifted, receipts)
    append_check(checks, "source_drift_invalidates_affected_receipts", [item["fix"] for item in drift_result["backends"]["cedar"]["operators"]][0] is True and len(drift_result["reorder_capability"]["supported_pairs"]) < 3, drift_result["reorder_capability"])

    unsupported = capability.compile_reorder_safe(commuting_base, all_pair_receipts(capability, commuting_base, status="unsupported"))
    append_check(checks, "unsupported_receipts_fail_closed", [item["fix"] for item in unsupported["backends"]["cedar"]["operators"]] == [True, True, True])
    duplicated = capability.compile_reorder_safe(commuting_base, receipts + [copy.deepcopy(receipts[0])])
    append_check(checks, "duplicate_receipts_fail_closed_for_pair", len(duplicated["reorder_capability"]["supported_pairs"]) == 2 and not any(len(region["operator_ids"]) == 3 and region["admitted"] for region in duplicated["reorder_capability"]["regions"]), duplicated["reorder_capability"])

    barrier_base = make_bound_bundle(compiler, commuting_functions, barrier_index=1)
    barrier_receipts = all_pair_receipts(capability, barrier_base)
    barrier_result = capability.compile_reorder_safe(barrier_base, barrier_receipts)
    append_check(checks, "p5a_barrier_is_never_cleared", barrier_result["backends"]["cedar"]["operators"][1]["fix"] is True, barrier_result["backends"]["cedar"]["operators"])
    dependency_base = make_bound_bundle(compiler, commuting_functions, dependency=True)
    dependency_result = capability.compile_reorder_safe(dependency_base, all_pair_receipts(capability, dependency_base))
    append_check(checks, "explicit_dependencies_are_preserved", dependency_result["backends"]["cedar"]["operators"][2]["depends_on"] == ["autocontract:decode"], dependency_result["backends"]["cedar"]["operators"])
    append_check(checks, "output_contains_no_optimizer_decision_fields", not capability.contains_decision_fields(admitted))

    result = {
        "schema_version": "autocontract.p5g-reorder-capability-result.v0",
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "schema_sha256": file_sha256(SCHEMA),
        "module_sha256": file_sha256(ROOT / "experiments/autocontract_reorder_capability_v0.py"),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "checks": checks,
        "cases": {
            "noncommutative_baseline": baseline,
            "noncommutative_repaired": repaired,
            "commuting_baseline": commuting_baseline,
            "commuting_admitted": commuting_optimized,
        },
        "note": "Synthetic mechanism calibration. Receipts are supplied, not inferred; independent final and real operator proofs remain open.",
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
