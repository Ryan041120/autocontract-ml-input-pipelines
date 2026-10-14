#!/usr/bin/env python3
"""Check real cedar reordering-plan consumption of P5A fix/depends_on."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5e_cedar_reorder_constraint_consumption_protocol.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
UPSTREAM_BLOBS = {
    "cedar/compose/optimizer.py": "11c70d449ad1fbeccc6f19ca0bcac56fef919e7f464699d96814ae80506de09b",
    "cedar/compose/utils.py": "b6895474650b13b5cd4e8bf429cb5cdf1082a7b0edf7223b90f71a671c669670",
    "tests/data/test_profile_stats.yml": "8fcd2c41df608a60a90efd26698c4ade4c5d428a398e4a2e68c0d74b431685e2",
}
LOCAL_FROZEN = {
    "experiments/autocontract_p5a_constraint_compiler.py": "c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab",
    "outputs/autocontract_p5a_constraint_compiler_selftest.json": "59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a",
    "outputs/autocontract_p5d_cedar_optimizer_consumption.json": "b22523811a844b39ddcd1991866220af275fee42d35370830bdbb0ad0b49c7fe",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str, text: bool = False) -> bytes | str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=text,
    ).stdout


def identity(value: Any) -> Any:
    return value


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


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    head = str(git_output(cedar_root, "rev-parse", "HEAD", text=True)).strip()
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    status = str(git_output(cedar_root, "status", "--porcelain=v1", text=True)).strip()
    append_check(checks, "upstream_worktree_is_clean", status == "", status or "clean")
    blob_observed = {
        path: hashlib.sha256(bytes(git_output(cedar_root, "show", f"HEAD:{path}"))).hexdigest()
        for path in UPSTREAM_BLOBS
    }
    append_check(checks, "upstream_git_blobs_match", blob_observed == UPSTREAM_BLOBS, blob_observed)
    local_observed = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in LOCAL_FROZEN}
    append_check(checks, "frozen_local_inputs_unchanged", local_observed == LOCAL_FROZEN, local_observed)

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_p5a_constraint_compiler as compiler
    from cedar.compose import Feature, OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    fix_pipeline = compiler.make_pipeline([
        compiler.make_operator("decode"),
        compiler.make_operator("crop", semantic_status="unknown", semantic_reason="fixture_unknown"),
        compiler.make_operator("normalize"),
    ])
    dependency_pipeline = compiler.make_pipeline([
        compiler.make_operator("decode"),
        compiler.make_operator("crop"),
        compiler.make_operator("normalize", depends_on=["decode"]),
    ])
    compiled = {
        "fix": compiler.compile_constraints(fix_pipeline)["backends"]["cedar"]["operators"],
        "dependency": compiler.compile_constraints(dependency_pipeline)["backends"]["cedar"]["operators"],
    }
    append_check(checks, "compiler_emits_crop_fix", compiled["fix"][1]["fix"] is True, compiled["fix"])
    append_check(
        checks,
        "compiler_emits_normalize_dependency",
        compiled["dependency"][2]["depends_on"] == ["autocontract:decode"],
        compiled["dependency"],
    )

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
    profile = cedar_root / protocol["fixture"]["official_profile"]
    observations: dict[str, Any] = {}

    for case_name, hints in compiled.items():
        for arm in ("autocontract", "hint_removed"):
            recipe = copy.deepcopy(hints)
            if arm == "hint_removed":
                for item in recipe:
                    item["fix"] = False
                    item["depends_on"] = []

            class ReorderFixture(Feature):
                def _compose(self, source_pipes):
                    pipe = source_pipes[0]
                    for item in recipe:
                        pipe = MapperPipe(pipe, identity, tag=item["tag"], is_random=item["random"])
                        if item["fix"]:
                            pipe = pipe.fix()
                        if item["depends_on"]:
                            pipe = pipe.depends_on(item["depends_on"])
                    return pipe

            feature = ReorderFixture()
            feature.apply(IterSource(range(3)))
            candidates = calculate_reorderings(feature.logical_pipes, feature.logical_adj_list)
            plan = feature.optimize(options, str(profile))
            selected_path = ordered_path(plan.graph)
            expected_count = protocol[f"{case_name}_case"]["expected_candidate_counts"][arm]
            expected_path = protocol[f"{case_name}_case"]["expected_selected_paths"][arm]
            key = f"{case_name}_{arm}"
            observations[key] = {
                "recipe": recipe,
                "candidate_count": len(candidates),
                "selected_path": selected_path,
            }
            append_check(checks, f"{key}_candidate_count_matches", len(candidates) == expected_count, len(candidates))
            append_check(checks, f"{key}_selected_path_matches", selected_path == expected_path, selected_path)

    constrained_dep = observations["dependency_autocontract"]["selected_path"]
    removed_dep = observations["dependency_hint_removed"]["selected_path"]
    append_check(checks, "dependency_constrained_plan_orders_decode_before_normalize", constrained_dep.index(2) < constrained_dep.index(0), constrained_dep)
    append_check(checks, "dependency_removed_optimum_violates_that_order", removed_dep.index(0) < removed_dep.index(2), removed_dep)
    append_check(checks, "fix_constrained_plan_keeps_crop_position", observations["fix_autocontract"]["selected_path"] == [3, 2, 1, 0])

    result = {
        "schema_version": "autocontract.p5e-cedar-reorder-constraint-consumption-result.v0",
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "checks": checks,
        "observations": observations,
        "note": "Actual cedar reorder candidate and selected-plan consumption of compiler-generated fix/depends_on; synthetic calibration only.",
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
