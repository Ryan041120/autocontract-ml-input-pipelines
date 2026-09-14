#!/usr/bin/env python3
"""Check real cedar cache-plan consumption of the P5A randomness hint."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5d_cedar_optimizer_consumption_protocol.json"
P5A_RESULT = ROOT / "outputs" / "autocontract_p5a_constraint_compiler_selftest.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
UPSTREAM_BLOBS = {
    "cedar/compose/optimizer.py": "11c70d449ad1fbeccc6f19ca0bcac56fef919e7f464699d96814ae80506de09b",
    "cedar/compose/feature.py": "6d450748bbea8ce53f9360e12c3d776a3805b4f9cccd0400d2d29e4271986aeb",
    "tests/data/test_cache_optimizer_stats.yml": "d01369996e5a4c7cbc6d0dadacca8c99880ba3af9b134b2c363667f85051ac5d",
}
LOCAL_FROZEN = {
    "outputs/autocontract_p5a_constraint_compiler_selftest.json": "59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a",
    "outputs/autocontract_p5c_cedar_runtime_smoke.json": "776f62f171d84d87d87e5fb56367cd00db8cb36d59494b3ecbff5b5dec881cdc",
    "experiments/autocontract_p5c_cedar_runtime_smoke.py": "1d4ea01a1107df72238e2bf2e08f72904956be0eb5ffaaf46838f794dae4eaf4",
    "benchmark/final_v1/p5c_cedar_runtime_smoke_protocol_v2.json": "7098c1bc91d44829f3f1d73615cc3a70a2637df3ee3c63d6e68808cf3ac3c8de",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str, text: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def add_one(value: int) -> int:
    return value + 1


def ordered_path(graph: dict[int, set[int]], source: int) -> list[int]:
    path = [source]
    current = source
    while graph[current]:
        if len(graph[current]) != 1:
            raise ValueError("fixture plan is not linear")
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
    p5a = json.loads(P5A_RESULT.read_text(encoding="utf-8"))
    recipe = p5a["example_bundle"]["backends"]["cedar"]["operators"]
    by_id = {item["operator_id"]: item for item in recipe}
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
    append_check(checks, "p5a_recipe_is_constraint_only", p5a["example_bundle"]["backends"]["cedar"]["constraint_only"] is True)
    append_check(checks, "p5a_crop_hint_is_random", by_id["crop"]["random"] is True, by_id["crop"])

    sys.path.insert(0, str(cedar_root))
    from cedar.compose import Feature, OptimizerOptions
    from cedar.pipes import BatcherPipe, MapperPipe, NoopPipe
    from cedar.sources import IterSource

    options = OptimizerOptions(
        enable_prefetch=False,
        available_local_cpus=1,
        enable_offload=False,
        enable_reorder=False,
        enable_local_parallelism=False,
        enable_fusion=False,
        enable_caching=True,
        disable_physical_opt=True,
        num_samples=100,
    )
    profile = cedar_root / protocol["fixture"]["official_profile"]

    class CacheFixture(Feature):
        def __init__(self, crop_random: bool):
            super().__init__()
            self.crop_random = crop_random

        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            pipe = MapperPipe(
                pipe,
                add_one,
                tag=by_id["decode"]["tag"],
                is_random=by_id["decode"]["random"],
            )
            pipe = MapperPipe(
                pipe,
                add_one,
                tag=by_id["crop"]["tag"],
                is_random=self.crop_random,
            )
            pipe = MapperPipe(
                pipe,
                add_one,
                tag=by_id["normalize"]["tag"],
                is_random=by_id["normalize"]["random"],
            )
            pipe = NoopPipe(pipe)
            pipe = MapperPipe(pipe, add_one, is_random=True)
            return BatcherPipe(pipe, batch_size=3).fix()

    arms: dict[str, Any] = {}
    for arm_name, arm_protocol in protocol["arms"].items():
        feature = CacheFixture(arm_protocol["crop_is_random"])
        feature.apply(IterSource(range(100)))
        logical_path = ordered_path(feature.logical_adj_list, 6)
        random_ids = [pipe_id for pipe_id in logical_path if feature.logical_pipes[pipe_id].is_random()]
        plan = feature.optimize(options, str(profile))
        optimized_path = ordered_path(plan.graph, 6)
        cache_ids = [
            pipe_id
            for pipe_id, description in plan.pipe_descs.items()
            if "Cache" in description.name
        ]
        edges = [[source, target] for source, targets in plan.graph.items() for target in targets]
        expected_edges = arm_protocol["expected_cache_edges"]
        arms[arm_name] = {
            "logical_path": logical_path,
            "random_ids": random_ids,
            "first_random_id": random_ids[0],
            "optimized_path": optimized_path,
            "cache_ids": cache_ids,
            "cache_edges": [edge for edge in edges if 7 in edge],
            "all_edges": sorted(edges),
        }
        append_check(checks, f"{arm_name}_logical_path_matches_fixture", logical_path == protocol["fixture"]["logical_path_ids"], logical_path)
        append_check(checks, f"{arm_name}_first_random_matches", random_ids[0] == arm_protocol["expected_first_random_id"], random_ids)
        append_check(checks, f"{arm_name}_one_cache_pipe_selected", cache_ids == [7], cache_ids)
        append_check(checks, f"{arm_name}_cache_boundary_matches", all(edge in edges for edge in expected_edges), [edge for edge in edges if 7 in edge])

    contract = arms["autocontract"]
    counterfactual = arms["single_hint_removed_counterfactual"]
    append_check(checks, "single_variable_changes_only_crop_randomness_boundary", contract["random_ids"] == [4, 1] and counterfactual["random_ids"] == [1], {"contract": contract["random_ids"], "counterfactual": counterfactual["random_ids"]})
    append_check(checks, "cedar_plan_changes_when_hint_is_removed", contract["optimized_path"] != counterfactual["optimized_path"], {"contract": contract["optimized_path"], "counterfactual": counterfactual["optimized_path"]})
    append_check(checks, "autocontract_cache_stays_before_declared_random_crop", contract["optimized_path"].index(7) < contract["optimized_path"].index(4), contract["optimized_path"])

    result = {
        "schema_version": "autocontract.p5d-cedar-optimizer-consumption-result.v0",
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "checks": checks,
        "arms": arms,
        "note": "Actual cedar cache-plan consumption of is_random on an official synthetic profile; no executed cache or benefit claim.",
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
