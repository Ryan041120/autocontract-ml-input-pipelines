#!/usr/bin/env python3
"""Commit-bound source/API conformance audit for the P5A cedar mapping.

This reads three official cedar blobs from GitHub, verifies their bytes, and
uses Python AST checks.  It neither imports cedar nor executes its optimizer.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p5b_cedar_api_conformance_protocol_v1.json"
P5A_RESULT = ROOT / "outputs" / "autocontract_p5a_constraint_compiler_selftest.json"
UPSTREAM_REPO = "stanford-mast/cedar"
UPSTREAM_COMMIT = "f062305fcdab196e871c5d09b4c82ab788b4da79"
UPSTREAM = {
    "cedar/pipes/map.py": {
        "git_blob_sha": "3ea6d339a031f5ea4073239e9c548fcce5089066",
        "size": 12771,
        "sha256": "dc99e3646996ab306071da3cab7f3fb8063486645f884c986a366277d8c572b2",
    },
    "cedar/pipes/pipe.py": {
        "git_blob_sha": "33720d9be0bca33a22225a02b48f1aa9be0b3447",
        "size": 27811,
        "sha256": "4ecac2a92e5100f6419a7a9f5247f9a2a058fbad5f76f5cb1df5ebac26b2710c",
    },
    "evaluation/pipelines/simclrv2/cedar_dataset.py": {
        "git_blob_sha": "45bc1dac2ba5cce9372e5d52d311c4aac8737fb6",
        "size": 3137,
        "sha256": "4ad0b875d5801475c9f5e856fb0b3e7d6755924965d29059a2ca63ceee1e7ef2",
    },
}
LOCAL_FROZEN = {
    "experiments/autocontract_p5a_constraint_compiler.py": "c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab",
    "outputs/autocontract_p5a_constraint_compiler_selftest.json": "59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a",
    "benchmark/final_v1/optimizer_constraint_bundle_v0.schema.json": "640ead1cef3085daf1000d70fdb9240ea2c63a2bb1890d235a754d3696ad910b",
}


class AuditError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_blob(blob_sha: str) -> bytes:
    url = f"https://api.github.com/repos/{UPSTREAM_REPO}/git/blobs/{blob_sha}"
    request = urllib.request.Request(url, headers={"User-Agent": "AutoContract-cedar-api-audit", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if value.get("sha") != blob_sha or value.get("encoding") != "base64":
        raise AuditError(f"bad GitHub blob response for {blob_sha}")
    return base64.b64decode(value["content"])


def class_node(tree: ast.AST, name: str) -> ast.ClassDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AuditError(f"class not found: {name}")


def method_node(owner: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in owner.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AuditError(f"method not found: {owner.name}.{name}")


def assigns_attribute(method: ast.FunctionDef, attribute: str, value_name: str | None = None, constant: Any | None = None) -> bool:
    for node in ast.walk(method):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self" and target.attr == attribute:
                if value_name is not None:
                    return isinstance(value, ast.Name) and value.id == value_name
                if constant is not None:
                    return isinstance(value, ast.Constant) and value.value == constant
                return True
    return False


def returns_self(method: ast.FunctionDef) -> bool:
    return any(isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id == "self" for node in ast.walk(method))


def method_returns_attribute(method: ast.FunctionDef, attribute: str) -> bool:
    return any(
        isinstance(node, ast.Return)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and node.value.attr == attribute
        for node in ast.walk(method)
    )


def super_init_keywords(method: ast.FunctionDef) -> set[str]:
    for node in ast.walk(method):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "__init__":
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "super":
            return {keyword.arg for keyword in node.keywords if keyword.arg is not None}
    return set()


def official_example_usage(tree: ast.AST) -> dict[str, int]:
    counts = {"mapper_tag_keywords": 0, "fix_calls": 0, "depends_on_calls": 0}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "MapperPipe":
            if any(keyword.arg == "tag" for keyword in node.keywords):
                counts["mapper_tag_keywords"] += 1
        if isinstance(node.func, ast.Attribute) and node.func.attr == "fix":
            counts["fix_calls"] += 1
        if isinstance(node.func, ast.Attribute) and node.func.attr == "depends_on":
            counts["depends_on_calls"] += 1
    return counts


def build_recipe(p5a_bundle: dict[str, Any]) -> dict[str, Any]:
    operators = p5a_bundle["backends"]["cedar"]["operators"]
    recipe_operators = []
    for operator in operators:
        public_calls = []
        if operator["fix"]:
            public_calls.append({"method": "fix", "args": []})
        if operator["depends_on"]:
            public_calls.append({"method": "depends_on", "args": [operator["depends_on"]]})
        recipe_operators.append({
            "operator_id": operator["operator_id"],
            "pipe_class": "MapperPipe",
            "constructor_kwargs": {"tag": operator["tag"], "is_random": operator["random"]},
            "public_post_construction_calls": public_calls,
            "autocontract_sidecar": {"contract_sha256": operator["contract_sha256"], "source_index_sha256": operator["source_index_sha256"]},
        })
    return {
        "schema_version": "autocontract.cedar-public-api-recipe.v0",
        "upstream_repository": f"https://github.com/{UPSTREAM_REPO}",
        "upstream_commit_sha": UPSTREAM_COMMIT,
        "operators": recipe_operators,
        "claim_boundary": "Source-level public API recipe only; cedar was not imported or executed.",
    }


def recursive_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys |= recursive_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= recursive_keys(child)
    return keys


def run(output: Path | None) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    sources: dict[str, bytes] = {}
    blob_ok = True
    for path, expected in UPSTREAM.items():
        content = fetch_blob(expected["git_blob_sha"])
        item = {"size": len(content), "sha256": sha256_bytes(content), "size_ok": len(content) == expected["size"], "sha256_ok": sha256_bytes(content) == expected["sha256"]}
        observed[path] = item
        sources[path] = content
        blob_ok = blob_ok and item["size_ok"] and item["sha256_ok"]

    map_tree = ast.parse(sources["cedar/pipes/map.py"].decode("utf-8"))
    pipe_tree = ast.parse(sources["cedar/pipes/pipe.py"].decode("utf-8"))
    example_tree = ast.parse(sources["evaluation/pipelines/simclrv2/cedar_dataset.py"].decode("utf-8"))
    mapper_init = method_node(class_node(map_tree, "MapperPipe"), "__init__")
    mapper_args = [arg.arg for arg in mapper_init.args.args]
    forwarded = super_init_keywords(mapper_init)
    pipe = class_node(pipe_tree, "Pipe")
    fix = method_node(pipe, "fix")
    depends = method_node(pipe, "depends_on")
    is_random = method_node(pipe, "is_random")
    usage = official_example_usage(example_tree)

    p5a_result = json.loads(P5A_RESULT.read_text(encoding="utf-8"))
    exercised_bundle = json.loads(json.dumps(p5a_result["example_bundle"]))
    exercised_operators = exercised_bundle["backends"]["cedar"]["operators"]
    exercised_operators[0]["fix"] = True
    exercised_operators[1]["depends_on"] = [exercised_operators[0]["tag"]]
    recipe = build_recipe(exercised_bundle)
    recipe_keys = recursive_keys(recipe)
    constructor_ok = all(set(item["constructor_kwargs"]) == {"tag", "is_random"} for item in recipe["operators"])
    public_methods = {call["method"] for item in recipe["operators"] for call in item["public_post_construction_calls"]}
    calls_ok = public_methods == {"fix", "depends_on"}
    sidecar_ok = all(set(item["autocontract_sidecar"]) == {"contract_sha256", "source_index_sha256"} for item in recipe["operators"])
    private_absent = not any(key.startswith("_") for key in recipe_keys) and "_is_random" not in json.dumps(recipe)
    local = {path: (ROOT / path).is_file() and file_sha256(ROOT / path) == expected for path, expected in LOCAL_FROZEN.items()}

    checks = [
        {"name": "all_upstream_blobs_match_commit_bound_sha256", "passed": blob_ok, "observed": observed},
        {"name": "MapperPipe_constructor_accepts_tag_and_is_random", "passed": {"tag", "is_random"} <= set(mapper_args), "observed": mapper_args},
        {"name": "MapperPipe_forwards_tag_and_is_random_to_Pipe", "passed": {"tag", "is_random"} <= forwarded, "observed": sorted(forwarded)},
        {"name": "Pipe_fix_is_public_fluent_and_sets_fix_order", "passed": assigns_attribute(fix, "_fix_order", constant=True) and returns_self(fix)},
        {"name": "Pipe_depends_on_is_public_fluent_and_sets_tags", "passed": assigns_attribute(depends, "_depends_on_tags", value_name="tags") and returns_self(depends)},
        {"name": "Pipe_is_random_reads_constructor_state", "passed": method_returns_attribute(is_random, "_is_random")},
        {"name": "official_example_uses_constructor_tags_fix_and_depends_on", "passed": all(value > 0 for value in usage.values()), "observed": usage},
        {"name": "recipe_uses_constructor_for_random_and_tag", "passed": constructor_ok},
        {"name": "recipe_uses_only_public_fix_and_depends_on_methods", "passed": calls_ok, "observed": sorted(public_methods)},
        {"name": "recipe_keeps_contract_and_source_digests_in_sidecar", "passed": sidecar_ok},
        {"name": "unsafe_private_field_mutation_is_absent", "passed": private_absent},
        {"name": "frozen_local_inputs_unchanged", "passed": all(local.values()), "observed": local},
    ]
    result = {
        "schema_version": "autocontract.p5b-cedar-api-conformance-result.v0",
        "status": "pass" if all(check["passed"] for check in checks) else "fail",
        "passed": sum(bool(check["passed"]) for check in checks),
        "total": len(checks),
        "protocol_sha256": file_sha256(PROTOCOL),
        "runner_sha256": file_sha256(Path(__file__).resolve()),
        "upstream_commit_sha": UPSTREAM_COMMIT,
        "checks": checks,
        "recipe": recipe,
        "note": "Commit-bound source/API conformance only; no cedar import, optimizer execution, or performance claim.",
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
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
