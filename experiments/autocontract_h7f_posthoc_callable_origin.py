"""Posthoc callable-provenance audit for the completed H7F run.

This script is non-gating and must not be used to rewrite the frozen H7F
result.  It distinguishes a public constructor parameter from a module-owned
function that is forwarded through a superclass constructor.
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import Literal

import autocontract_h6_effect_v2 as v2
import autocontract_h7f_imgaug as h7f


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
Origin = Literal["user_input", "user_derived", "module_symbol", "internal", "unknown"]
USER_ORIGINS = frozenset(("user_input", "user_derived"))
SYMBOLS = (
    "imgaug.augmenters.contrast.LinearContrast",
    "imgaug.augmenters.meta.Lambda",
    "imgaug.augmenters.meta.AssertLambda",
)


def join_origins(origins: list[Origin]) -> Origin:
    if any(item in USER_ORIGINS for item in origins):
        return "user_derived"
    if "unknown" in origins:
        return "unknown"
    if "module_symbol" in origins:
        return "module_symbol"
    return "internal"


def expression_origin(
    node: ast.AST, env: dict[str, Origin], module_functions: set[str]
) -> Origin:
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in module_functions:
            return "module_symbol"
        return "internal"
    children = [
        expression_origin(child, env, module_functions)
        for child in ast.iter_child_nodes(node)
        if not isinstance(child, (ast.Load, ast.Store))
    ]
    return join_origins(children) if children else "internal"


def first_base(cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> ast.ClassDef | None:
    for name in v2.base_names(cls):
        if name in classes:
            return classes[name]
    return None


def super_init_call(method: ast.FunctionDef) -> ast.Call | None:
    for statement in method.body:
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            if (
                node.func.attr == "__init__"
                and isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "super"
            ):
                return node
    return None


def constructor_origins(
    root: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    module_functions: set[str],
) -> dict[str, Origin]:
    current = root
    env: dict[str, Origin] | None = None
    attrs: dict[str, Origin] = {}
    seen: set[str] = set()
    while current.name not in seen:
        seen.add(current.name)
        method = v2.method_map(current).get("__init__")
        parent = first_base(current, classes)
        if method is None:
            if parent is None:
                break
            current = parent
            continue
        parameters = [
            arg.arg
            for arg in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)
            if arg.arg != "self"
        ]
        if env is None:
            env = {name: "user_input" for name in parameters}
        else:
            env = {name: env.get(name, "unknown") for name in parameters}

        for statement in method.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            origin = expression_origin(statement.value, env, module_functions)
            for target in targets:
                if isinstance(target, ast.Name):
                    env[target.id] = origin
                chain = v2.corpus_v1.attribute_chain(target)
                if chain.startswith("self.") and chain.count(".") == 1:
                    attrs[chain.split(".", 1)[1]] = origin

        call = super_init_call(method)
        if parent is None or call is None:
            if parent is None:
                break
            current = parent
            env = None
            continue
        parent_init = v2.method_map(parent).get("__init__")
        if parent_init is None:
            current = parent
            env = None
            continue
        parent_params = [
            arg.arg
            for arg in (*parent_init.args.posonlyargs, *parent_init.args.args)
            if arg.arg != "self"
        ]
        forwarded: dict[str, Origin] = {}
        for name, argument in zip(parent_params, call.args):
            forwarded[name] = expression_origin(argument, env, module_functions)
        for keyword in call.keywords:
            if keyword.arg is not None:
                forwarded[keyword.arg] = expression_origin(keyword.value, env, module_functions)
        env = forwarded
        current = parent
    return attrs


def module_functions() -> set[str]:
    found: set[str] = set()
    for path in (h7f.REPO / "imgaug").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _, functions = v2.top_definitions(tree)
        found.update(functions)
    return found


def main() -> None:
    classes = h7f.package_classes()
    functions = module_functions()
    rows: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        binding = h7f.public_binding(symbol)
        root = h7f.target_class(binding)
        if root is None:
            raise RuntimeError(f"missing target: {symbol}")
        attrs = constructor_origins(root, {**classes, root.name: root}, functions)
        invoked = h7f.invoked_self_attrs(h7f.execution_nodes(root, classes))
        callable_attrs = sorted(
            attr
            for attr in invoked & set(attrs)
            if any(token in attr.lower() for token in h7f.CALLABLE_PARAM_TOKENS)
        )
        origins = sorted({attrs[attr] for attr in callable_attrs})
        actual_user_callable = any(origin in USER_ORIGINS for origin in origins)
        rows.append(
            {
                "public_symbol": symbol,
                "invoked_callable_attrs": ";".join(callable_attrs) or "none",
                "origins": ";".join(origins) or "none",
                "user_callable_after_provenance": actual_user_callable,
                "counterfactual_decision": "reject" if actual_user_callable else "admit",
            }
        )

    path = OUT / "autocontract_h7f_posthoc_callable_origin.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = "\n".join(
        [
            "# H7F posthoc callable-origin audit (non-gating)",
            "",
            "This audit was designed after the frozen one-shot H7F run and does not alter H7F=PASS.",
            "",
            "| Symbol | Invoked callable | Origin | User callable? | Counterfactual |",
            "|---|---|---|---|---|",
            *[
                f"| `{row['public_symbol']}` | {row['invoked_callable_attrs']} | "
                f"{row['origins']} | {row['user_callable_after_provenance']} | "
                f"{row['counterfactual_decision']} |"
                for row in rows
            ],
            "",
            "`LinearContrast.func` is a module-owned function forwarded through `super().__init__`; "
            "the Lambda-family callbacks derive from public constructor inputs.",
            "",
        ]
    )
    (OUT / "autocontract_h7f_posthoc_callable_origin.md").write_text(
        report, encoding="utf-8"
    )
    print(report)


if __name__ == "__main__":
    main()
