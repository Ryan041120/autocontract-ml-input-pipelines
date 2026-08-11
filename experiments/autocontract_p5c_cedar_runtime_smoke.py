#!/usr/bin/env python3
"""Run a commit-bound cedar runtime/API smoke test for the P5B recipe.

The test imports the official checkout, constructs the public API recipe, and
executes an optimizer-disabled synthetic data path.  It does not execute the
cedar optimizer or make a performance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5c_cedar_runtime_smoke_protocol_v2.json"
BASE_PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5c_cedar_runtime_smoke_protocol.json"
P5B_RESULT = ROOT / "outputs" / "autocontract_p5b_cedar_api_conformance.json"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
UPSTREAM_SOURCES = {
    "cedar/pipes/map.py": "dc99e3646996ab306071da3cab7f3fb8063486645f884c986a366277d8c572b2",
    "cedar/pipes/pipe.py": "4ecac2a92e5100f6419a7a9f5247f9a2a058fbad5f76f5cb1df5ebac26b2710c",
}
LOCAL_FROZEN = {
    "outputs/autocontract_p5b_cedar_api_conformance.json": "217a4060fbe16326365102611968bf8ecbc9a4fa2697ebb5ea18c85b577766d9",
    "benchmark/final_v1/p5b_cedar_api_conformance_protocol_v1.json": "c666b44548f935b64a30058aede7478eed0ea70c6f37477d1c15d2424ecaa84f",
    "experiments/autocontract_p5b_cedar_api_conformance.py": "ff1d40fc788e1edc983b52412acdef818bfbfe61b12de86829b825b753f37570",
}
EXPECTED_VERSIONS = {
    "python": "3.11.9",
    "torch": "2.0.1+cpu",
    "tensorflow": "2.14.0",
    "ray": "2.7.0",
    "numpy": "1.26.0",
    "torchvision": "0.15.2+cpu",
    "torchdata": "0.6.1",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_blob_bytes(path: Path, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(path), "show", f"HEAD:{relative_path}"],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def git_status(path: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def add_one(value: int) -> int:
    return value + 1


def double(value: int) -> int:
    return value * 2


def subtract_three(value: int) -> int:
    return value - 3


def distribution_fingerprint() -> dict[str, Any]:
    rows = sorted(
        {
            f"{dist.metadata['Name'].lower()}=={dist.version}"
            for dist in importlib.metadata.distributions()
            if dist.metadata.get("Name")
        }
    )
    payload = "\n".join(rows).encode("utf-8")
    return {"count": len(rows), "sha256": hashlib.sha256(payload).hexdigest(), "packages": rows}


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def run(cedar_root: Path, output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    base_protocol = json.loads(BASE_PROTOCOL.read_text(encoding="utf-8"))
    p5b = json.loads(P5B_RESULT.read_text(encoding="utf-8"))
    recipe = p5b["recipe"]
    checks: list[dict[str, Any]] = []

    head = git_head(cedar_root)
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    source_observed: dict[str, Any] = {}
    source_ok = True
    for path, expected_hash in UPSTREAM_SOURCES.items():
        blob = git_blob_bytes(cedar_root, path)
        worktree = (cedar_root / path).read_bytes()
        blob_hash = hashlib.sha256(blob).hexdigest()
        worktree_hash = hashlib.sha256(worktree).hexdigest()
        normalized_hash = hashlib.sha256(worktree.replace(b"\r\n", b"\n")).hexdigest()
        item = {
            "git_blob_sha256": blob_hash,
            "worktree_sha256": worktree_hash,
            "normalized_worktree_sha256": normalized_hash,
            "git_blob_matches": blob_hash == expected_hash,
            "normalized_worktree_matches": normalized_hash == expected_hash,
        }
        source_observed[path] = item
        source_ok = source_ok and item["git_blob_matches"] and item["normalized_worktree_matches"]
    append_check(
        checks,
        "upstream_git_blob_and_worktree_normalization_match",
        source_ok,
        source_observed,
    )
    status = git_status(cedar_root)
    append_check(checks, "upstream_worktree_is_clean", status == "", status or "clean")
    local_observed = {
        path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None
        for path in LOCAL_FROZEN
    }
    append_check(checks, "frozen_local_inputs_unchanged", local_observed == LOCAL_FROZEN, local_observed)

    sys.path.insert(0, str(cedar_root))
    import numpy
    import ray
    import tensorflow
    import torch
    import torchdata
    import torchvision

    versions = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "torch": torch.__version__,
        "tensorflow": tensorflow.__version__,
        "ray": ray.__version__,
        "numpy": numpy.__version__,
        "torchvision": torchvision.__version__,
        "torchdata": torchdata.__version__,
    }
    append_check(checks, "core_runtime_versions_match", versions == EXPECTED_VERSIONS, versions)

    from cedar.client import DataSet
    from cedar.compose import Feature
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    append_check(checks, "cedar_public_imports_succeed", True)
    public_methods = {
        call["method"]
        for operator in recipe["operators"]
        for call in operator["public_post_construction_calls"]
    }
    append_check(checks, "p5b_recipe_is_non_vacuous", public_methods == {"fix", "depends_on"}, sorted(public_methods))

    functions: list[Callable[[int], int]] = [add_one, double, subtract_three]
    captured: list[Any] = []

    class RuntimeFeature(Feature):
        def _compose(self, source_pipes):
            pipe = source_pipes[0]
            for item, function in zip(recipe["operators"], functions, strict=True):
                pipe = MapperPipe(pipe, function, **item["constructor_kwargs"])
                for call in item["public_post_construction_calls"]:
                    pipe = getattr(pipe, call["method"])(*call["args"])
                captured.append(pipe)
            return pipe

    feature = RuntimeFeature()
    feature.apply(IterSource(base_protocol["fixture"]["source"]))
    append_check(checks, "three_mapper_objects_construct", len(captured) == 3, len(captured))

    expected_tags = [item["constructor_kwargs"]["tag"] for item in recipe["operators"]]
    observed_tags = [item.tag for item in captured]
    append_check(checks, "constructor_tag_state_matches_recipe", observed_tags == expected_tags, observed_tags)
    expected_random = [item["constructor_kwargs"]["is_random"] for item in recipe["operators"]]
    observed_random = [item.is_random() for item in captured]
    append_check(checks, "constructor_random_state_matches_recipe", observed_random == expected_random, observed_random)

    expected_fix = [
        any(call["method"] == "fix" for call in item["public_post_construction_calls"])
        for item in recipe["operators"]
    ]
    observed_fix = [item._fix_order for item in captured]
    append_check(checks, "public_fix_state_matches_recipe", observed_fix == expected_fix, observed_fix)
    expected_depends = []
    for item in recipe["operators"]:
        calls = [call for call in item["public_post_construction_calls"] if call["method"] == "depends_on"]
        expected_depends.append(calls[0]["args"][0] if calls else None)
    observed_depends = [item._depends_on_tags for item in captured]
    append_check(checks, "public_depends_on_state_matches_recipe", observed_depends == expected_depends, observed_depends)

    chain_ok = all(captured[index].input_pipes[0] is captured[index - 1] for index in range(1, len(captured)))
    append_check(checks, "logical_chain_preserves_operator_order", chain_ok)
    append_check(checks, "optimizer_is_disabled", base_protocol["fixture"]["optimizer_enabled"] is False, False)

    dataset = DataSet(
        CedarContext(),
        {"autocontract": feature},
        prefetch=False,
        enable_controller=False,
        enable_optimizer=False,
    )
    observed_output = [sample.data if hasattr(sample, "data") else sample for sample in dataset]
    append_check(
        checks,
        "synthetic_data_path_matches_expected_output",
        observed_output == base_protocol["fixture"]["expected_output"],
        observed_output,
    )

    result = {
        "schema_version": "autocontract.p5c-cedar-runtime-smoke-result.v0",
        "status": "pass" if all(item["passed"] for item in checks) else "fail",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": head,
        "runtime": versions,
        "resolved_environment": distribution_fingerprint(),
        "checks": checks,
        "note": "Runtime public API and optimizer-disabled data path only; no cedar optimizer or performance claim.",
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
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
