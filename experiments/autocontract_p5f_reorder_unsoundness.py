#!/usr/bin/env python3
"""Reproduce the P5A pure-is-not-commutative cedar counterexample."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5f_reorder_unsoundness_protocol.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
UPSTREAM_BLOBS = {
    "cedar/compose/optimizer.py": "11c70d449ad1fbeccc6f19ca0bcac56fef919e7f464699d96814ae80506de09b",
    "cedar/compose/feature.py": "6d450748bbea8ce53f9360e12c3d776a3805b4f9cccd0400d2d29e4271986aeb",
    "tests/data/test_profile_stats.yml": "8fcd2c41df608a60a90efd26698c4ade4c5d428a398e4a2e68c0d74b431685e2",
}
LOCAL_FROZEN = {
    "experiments/autocontract_p5a_constraint_compiler.py": "c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab",
    "outputs/autocontract_p5a_constraint_compiler_selftest.json": "59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a",
    "outputs/autocontract_p5e_cedar_reorder_constraint_consumption.json": "db80c6d97c27a4c19c4feb1d497fcffcaca5e849ea19dc30c932b2ad8ed01317",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str, text: bool = False) -> bytes | str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=text).stdout


def add_one(value: int) -> int:
    return value + 1


def double(value: int) -> int:
    return value * 2


def subtract_three(value: int) -> int:
    return value - 3


def ordered_path(graph: dict[int, set[int]], source: int = 3) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        current = next(iter(graph[current]))
        path.append(current)
    return path


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    head = str(git_output(cedar_root, "rev-parse", "HEAD", text=True)).strip()
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    status = str(git_output(cedar_root, "status", "--porcelain=v1", text=True)).strip()
    append_check(checks, "upstream_worktree_is_clean", status == "", status or "clean")
    blobs = {path: hashlib.sha256(bytes(git_output(cedar_root, "show", f"HEAD:{path}"))).hexdigest() for path in UPSTREAM_BLOBS}
    append_check(checks, "upstream_git_blobs_match", blobs == UPSTREAM_BLOBS, blobs)
    local = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in LOCAL_FROZEN}
    append_check(checks, "frozen_local_inputs_unchanged", local == LOCAL_FROZEN, local)

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_p5a_constraint_compiler as compiler
    from cedar.compose import Feature, OptimizerOptions
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    pipeline = compiler.make_pipeline([
        compiler.make_operator("decode"),
        compiler.make_operator("crop"),
        compiler.make_operator("normalize"),
    ])
    bundle = compiler.compile_constraints(pipeline)
    recipe = bundle["backends"]["cedar"]["operators"]
    no_constraints = all(not item["random"] and not item["fix"] and item["depends_on"] == [] for item in recipe)
    append_check(checks, "p5a_emits_no_reorder_constraint", no_constraints, recipe)
    append_check(checks, "p5a_marks_full_pipeline_strict_cache_eligible", all(item["strict_cache_eligible"] for item in bundle["operators"]), bundle["operators"])

    functions = [add_one, double, subtract_three]

    class NonCommutativeFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, function in zip(recipe, functions, strict=True):
                pipe = MapperPipe(pipe, function, tag=item["tag"], is_random=item["random"])
                if item["fix"]:
                    pipe = pipe.fix()
                if item["depends_on"]:
                    pipe = pipe.depends_on(item["depends_on"])
            return pipe

    baseline_feature = NonCommutativeFeature()
    baseline_feature.apply(IterSource(protocol["counterexample"]["source"]))
    logical_path = ordered_path(baseline_feature.logical_adj_list)
    baseline_iter = baseline_feature.load(CedarContext(), prefetch=False)
    baseline_output = [sample.data for sample in baseline_iter]

    optimized_feature = NonCommutativeFeature()
    optimized_feature.apply(IterSource(protocol["counterexample"]["source"]))
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
    plan = optimized_feature.optimize(options, str(cedar_root / "tests/data/test_profile_stats.yml"))
    optimized_path = ordered_path(plan.graph)
    optimized_iter = optimized_feature.load_from_plan(CedarContext(), plan)
    optimized_output = [sample.data for sample in optimized_iter]

    expected = protocol["counterexample"]
    append_check(checks, "logical_path_matches", logical_path == expected["expected_logical_path"], logical_path)
    append_check(checks, "optimized_path_matches", optimized_path == expected["expected_optimized_path"], optimized_path)
    append_check(checks, "baseline_output_matches", baseline_output == expected["expected_baseline_output"], baseline_output)
    append_check(checks, "optimized_output_matches", optimized_output == expected["expected_optimized_output"], optimized_output)
    append_check(checks, "reordering_changes_observable_output", optimized_output != baseline_output, {"baseline": baseline_output, "optimized": optimized_output})

    reproduction_pass = all(item["passed"] for item in checks)
    result = {
        "schema_version": "autocontract.p5f-reorder-unsoundness-result.v0",
        "reproduction_status": "pass" if reproduction_pass else "fail",
        "system_verdict": "fail_unsafe_reorder_authorization" if reproduction_pass else "counterexample_not_reproduced",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "checks": checks,
        "baseline": {"path": logical_path, "output": baseline_output},
        "optimized": {"path": optimized_path, "output": optimized_output},
        "claim_effect": protocol["claim_effect"],
        "note": protocol["non_attribution"],
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
    return 0 if result["reproduction_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
