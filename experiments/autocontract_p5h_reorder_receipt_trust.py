#!/usr/bin/env python3
"""Audit the untrusted-receipt boundary of ReorderCapabilityV0."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5h_reorder_receipt_trust_protocol.json"
LOCAL_FROZEN = {
    "outputs/autocontract_p5f_reorder_unsoundness.json": "83076a5667e219c334e10402ddad8b1ef813a3ab6264ed5f5a67e175cca16eff",
    "outputs/autocontract_p5g_reorder_capability.json": "0922f625d24880719aa4d1e148b5288297bea0759d41eff6be81114685c6d060",
    "experiments/autocontract_reorder_capability_v0.py": "77da9d207f62a3e732f5242aebf76bcdae43acebf16baa02cbb3f9879d93a5ae",
}
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"


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
    head = subprocess.run(["git", "-C", str(cedar_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    append_check(checks, "upstream_checkout_matches_commit", head == UPSTREAM_COMMIT, head)
    local = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in LOCAL_FROZEN}
    append_check(checks, "frozen_inputs_unchanged", local == LOCAL_FROZEN, local)

    sys.path.insert(0, str(ROOT / "experiments"))
    sys.path.insert(0, str(cedar_root))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_reorder_capability_v0 as capability
    from cedar.compose import Feature, OptimizerOptions
    from cedar.compose.utils import calculate_reorderings
    from cedar.config import CedarContext
    from cedar.pipes import MapperPipe
    from cedar.sources import IterSource

    functions = [add_one, double, subtract_three]
    ids = ["decode", "crop", "normalize"]
    operators = []
    for operator_id, function in zip(ids, functions, strict=True):
        operators.append(compiler.make_operator(
            operator_id,
            source_index_sha256=hashlib.sha256(inspect.getsource(function).encode("utf-8")).hexdigest(),
            contract_sha256=hashlib.sha256(f"contract:{operator_id}:{function.__name__}".encode("utf-8")).hexdigest(),
        ))
    base = compiler.compile_constraints(compiler.make_pipeline(operators, operation="adjacent_reorder"))
    forged = [
        capability.make_receipt(base, ids[left], ids[right], status="supported", proof_method="differential", proof_label=f"unverified-assertion:{left}:{right}")
        for left in range(3)
        for right in range(left + 1, 3)
    ]
    for receipt in forged:
        capability.validate_receipt(receipt)
    append_check(checks, "forged_receipts_are_syntactically_valid", True, forged)
    fail_closed = capability.compile_reorder_safe(base, [])
    attacked = capability.compile_reorder_safe(base, forged)
    append_check(checks, "v0_admits_forged_complete_region", attacked["reorder_capability"]["regions"] == [{"operator_ids": ids, "admitted": True, "reason": "pairwise_complete_supported"}], attacked["reorder_capability"])

    def execute(bundle: dict[str, Any], optimize: bool) -> dict[str, Any]:
        recipe = bundle["backends"]["cedar"]["operators"]

        class AttackFeature(Feature):
            def _compose(self, source_pipes):
                pipe = source_pipes[0]
                for item, function in zip(recipe, functions, strict=True):
                    pipe = MapperPipe(pipe, function, tag=item["tag"], is_random=item["random"])
                    if item["fix"]:
                        pipe = pipe.fix()
                return pipe

        feature = AttackFeature()
        feature.apply(IterSource([0, 1, 2, 3, 4]))
        count = len(calculate_reorderings(feature.logical_pipes, feature.logical_adj_list))
        if optimize:
            options = OptimizerOptions(enable_prefetch=False, available_local_cpus=1, enable_offload=False, enable_reorder=True, enable_local_parallelism=False, enable_fusion=False, enable_caching=False, disable_physical_opt=True, num_samples=100)
            plan = feature.optimize(options, str(cedar_root / "tests/data/test_profile_stats.yml"))
            path = ordered_path(plan.graph)
            iterator = feature.load_from_plan(CedarContext(), plan)
        else:
            path = ordered_path(feature.logical_adj_list)
            iterator = feature.load(CedarContext(), prefetch=False)
        return {"candidate_count": count, "path": path, "output": [sample.data for sample in iterator]}

    baseline = execute(fail_closed, False)
    attack = execute(attacked, True)
    append_check(checks, "fail_closed_baseline_matches", baseline == {"candidate_count": 1, "path": [3, 2, 1, 0], "output": [-1, 1, 3, 5, 7]}, baseline)
    append_check(checks, "forged_receipts_restore_six_candidates", attack["candidate_count"] == 6, attack)
    append_check(checks, "forged_receipts_enable_reordered_plan", attack["path"] == [3, 0, 1, 2], attack["path"])
    append_check(checks, "forged_receipts_change_output", attack["output"] == [-5, -3, -1, 1, 3] and attack["output"] != baseline["output"], {"baseline": baseline["output"], "attack": attack["output"]})

    reproduced = all(item["passed"] for item in checks)
    result = {
        "schema_version": "autocontract.p5h-reorder-receipt-trust-result.v0",
        "reproduction_status": "pass" if reproduced else "fail",
        "system_verdict": "fail_unverified_receipt_trust_boundary" if reproduced else "attack_not_reproduced",
        "passed": sum(bool(item["passed"]) for item in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "checks": checks,
        "baseline": baseline,
        "attack": attack,
        "required_v1": protocol["interpretation"]["required_v1"],
        "note": "P5G remains a composition mechanism under a trusted-receipt assumption; V0 is not a proof verifier and must not accept arbitrary caller assertions."
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
