#!/usr/bin/env python3
"""Systematic mutation and monotonicity audit for ReorderCapabilityV1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import sys
import types
from itertools import combinations
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5j_reorder_v1_mutation_protocol.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_one(value: int) -> int:
    return value + 1


def add_two(value: int) -> int:
    return value + 2


def add_three(value: int) -> int:
    return value + 3


def double(value: int) -> int:
    return value * 2


def append_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any = None) -> None:
    item: dict[str, Any] = {"name": name, "passed": bool(passed)}
    if observed is not None:
        item["observed"] = observed
    checks.append(item)


def make_bundle(compiler: Any, v1: Any, functions: list[Callable[[int], int]]) -> tuple[dict[str, Any], dict[str, Callable[[int], int]]]:
    ids = ["decode", "crop", "normalize"]
    operators = []
    mapping = {}
    for operator_id, function in zip(ids, functions, strict=True):
        mapping[operator_id] = function
        operators.append(compiler.make_operator(
            operator_id,
            source_index_sha256=v1.callable_source_sha256(function),
            contract_sha256=hashlib.sha256(f"contract:{operator_id}:{function.__name__}".encode()).hexdigest(),
        ))
    return compiler.compile_constraints(compiler.make_pipeline(operators, operation="adjacent_reorder")), mapping


def all_fixed(bundle: dict[str, Any]) -> bool:
    return all(item["fix"] for item in bundle["backends"]["cedar"]["operators"])


def unfixed_ids(bundle: dict[str, Any]) -> set[str]:
    return {item["operator_id"] for item in bundle["backends"]["cedar"]["operators"] if not item["fix"]}


def mutate(receipt: dict[str, Any], label: str, action: Callable[[dict[str, Any]], None], v0: Any, *, rehash: bool = False) -> tuple[str, dict[str, Any]]:
    value = copy.deepcopy(receipt)
    action(value)
    if rehash and isinstance(value.get("proof_artifact"), dict):
        value["proof_sha256"] = v0.canonical_sha256(value["proof_artifact"])
    return label, value


def run(output: Path | None) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    frozen_expected = protocol["frozen_predecessor"]
    frozen_observed = {path: file_sha256(ROOT / path) if (ROOT / path).is_file() else None for path in frozen_expected}
    append_check(checks, "p5i_predecessor_is_frozen", frozen_observed == frozen_expected, frozen_observed)

    sys.path.insert(0, str(ROOT / "experiments"))
    import autocontract_p5a_constraint_compiler as compiler
    import autocontract_reorder_capability_v0 as v0
    import autocontract_reorder_capability_v1 as v1

    base, mapping = make_bundle(compiler, v1, [add_one, add_two, add_three])
    ids = ["decode", "crop", "normalize"]
    receipts = [
        v1.make_verified_receipt(base, ids[left], ids[right], mapping)
        for left in range(3) for right in range(left + 1, 3)
    ]
    complete = v1.compile_reorder_safe_strict(base, receipts, mapping)
    append_check(checks, "unmutated_complete_cover_verifies", len(complete["proof_verification"]["verified_pairs"]) == 3 and unfixed_ids(complete) == set(ids))

    seed = receipts[0]
    mutations: list[tuple[str, dict[str, Any]]] = []
    simple = [
        ("schema_version", lambda r: r.__setitem__("schema_version", "autocontract.reorder-capability.v999")),
        ("operation_context", lambda r: r.__setitem__("operation_context_sha256", "0" * 64)),
        ("input_schema", lambda r: r.__setitem__("input_schema_sha256", "1" * 64)),
        ("left_contract", lambda r: r["left"].__setitem__("contract_sha256", "2" * 64)),
        ("left_source", lambda r: r["left"].__setitem__("source_index_sha256", "3" * 64)),
        ("right_contract", lambda r: r["right"].__setitem__("contract_sha256", "4" * 64)),
        ("right_source", lambda r: r["right"].__setitem__("source_index_sha256", "5" * 64)),
        ("relation", lambda r: r.__setitem__("relation", "equivalent")),
        ("status", lambda r: r.__setitem__("status", "unknown")),
        ("assurance", lambda r: r.__setitem__("assurance_level", "caller_asserted")),
        ("verifier_id", lambda r: r["verifier"].__setitem__("verifier_id", "attacker")),
        ("verifier_version", lambda r: r["verifier"].__setitem__("version", "9.9.9")),
        ("verifier_source", lambda r: r["verifier"].__setitem__("source_sha256", "6" * 64)),
        ("proof_kind", lambda r: r["proof_artifact"].__setitem__("kind", "caller_claim")),
        ("proof_domain", lambda r: r["proof_artifact"].__setitem__("domain", "all_python_values")),
        ("proof_equality", lambda r: r["proof_artifact"].__setitem__("equality", False)),
        ("proof_digest", lambda r: r.__setitem__("proof_sha256", "7" * 64)),
        ("proof_scope", lambda r: r.__setitem__("proof_scope", "All operators and domains.")),
        ("extra_top_key", lambda r: r.__setitem__("trusted", True)),
        ("extra_verifier_key", lambda r: r["verifier"].__setitem__("signature", "fake")),
        ("extra_proof_key", lambda r: r["proof_artifact"].__setitem__("note", "fake")),
        ("extra_ir_key", lambda r: r["proof_artifact"]["left_ir"].__setitem__("quadratic", 1)),
        ("zero_denominator", lambda r: r["proof_artifact"]["left_ir"]["coefficient"].__setitem__("denominator", 0)),
    ]
    mutations.extend(mutate(seed, label, action, v0) for label, action in simple)
    semantic = [
        ("left_ir_rehashed", lambda r: r["proof_artifact"]["left_ir"]["intercept"].__setitem__("numerator", 99)),
        ("right_ir_rehashed", lambda r: r["proof_artifact"]["right_ir"]["coefficient"].__setitem__("numerator", 9)),
        ("left_then_right_rehashed", lambda r: r["proof_artifact"]["left_then_right_ir"]["intercept"].__setitem__("numerator", -8)),
        ("right_then_left_rehashed", lambda r: r["proof_artifact"]["right_then_left_ir"]["intercept"].__setitem__("numerator", -8)),
    ]
    mutations.extend(mutate(seed, label, action, v0, rehash=True) for label, action in semantic)
    for key in sorted(seed):
        mutations.append(mutate(seed, f"delete_top:{key}", lambda r, key=key: r.pop(key), v0))
    for key in sorted(seed["verifier"]):
        mutations.append(mutate(seed, f"delete_verifier:{key}", lambda r, key=key: r["verifier"].pop(key), v0))
    for key in sorted(seed["proof_artifact"]):
        mutations.append(mutate(seed, f"delete_proof:{key}", lambda r, key=key: r["proof_artifact"].pop(key), v0, rehash=True))
    for side in ("left", "right"):
        for key in sorted(seed[side]):
            mutations.append(mutate(seed, f"delete_{side}:{key}", lambda r, side=side, key=key: r[side].pop(key), v0))

    mutation_observations = []
    for label, receipt in mutations:
        result = v1.compile_reorder_safe_strict(base, [receipt], mapping)
        passed = not result["proof_verification"]["verified_pairs"] and all_fixed(result)
        reason = result["proof_verification"]["receipt_audit"][0]["reason"]
        mutation_observations.append({"label": label, "passed": passed, "reason": reason})
    append_check(checks, "all_isolated_receipt_mutations_fail_closed", all(item["passed"] for item in mutation_observations), {"count": len(mutation_observations), "failures": [item for item in mutation_observations if not item["passed"]], "reason_counts": {reason: sum(item["reason"] == reason for item in mutation_observations) for reason in sorted({item["reason"] for item in mutation_observations})}})

    replacement = types.FunctionType(double.__code__, double.__globals__, name=add_one.__name__)
    replacement.__module__ = add_one.__module__
    replacement_mapping = dict(mapping)
    replacement_mapping["decode"] = replacement
    replacement_result = v1.compile_reorder_safe_strict(base, [receipts[1]], replacement_mapping)
    append_check(checks, "post_issue_callable_replacement_fails_sourceindex_replay", not replacement_result["proof_verification"]["verified_pairs"] and all_fixed(replacement_result), replacement_result["proof_verification"])

    subset_results: dict[int, dict[str, Any]] = {}
    for mask in range(1 << len(receipts)):
        selected = [receipt for index, receipt in enumerate(receipts) if mask & (1 << index)]
        compiled = v1.compile_reorder_safe_strict(base, selected, mapping)
        subset_results[mask] = {
            "receipt_count": len(selected),
            "verified_count": len(compiled["proof_verification"]["verified_pairs"]),
            "unfixed": sorted(unfixed_ids(compiled)),
            "full_region": any(region["admitted"] and len(region["operator_ids"]) == 3 for region in compiled["reorder_capability"]["regions"]),
        }
    monotone_failures = []
    for left_mask, right_mask in combinations(range(1 << len(receipts)), 2):
        if left_mask & right_mask == left_mask:
            left = set(subset_results[left_mask]["unfixed"])
            right = set(subset_results[right_mask]["unfixed"])
            if not left <= right:
                monotone_failures.append({"subset": left_mask, "superset": right_mask, "left": sorted(left), "right": sorted(right)})
    append_check(checks, "receipt_subset_evidence_is_monotone", not monotone_failures, {"comparisons": 19, "failures": monotone_failures})
    full_masks = [mask for mask, item in subset_results.items() if item["full_region"]]
    append_check(checks, "only_complete_pair_cover_opens_full_region", full_masks == [7], {"full_region_masks": full_masks, "subsets": subset_results})

    passed = sum(bool(item["passed"]) for item in checks)
    result = {
        "schema_version": "autocontract.p5j-reorder-v1-mutation-result.v0",
        "status": "pass" if passed == len(checks) else "fail",
        "passed": passed,
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "mutation_count": len(mutations),
        "checks": checks,
        "mutations": mutation_observations,
        "claim_boundary": protocol["claim_boundary"],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
