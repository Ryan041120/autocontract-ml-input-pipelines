"""Non-gating mode-conditioned reachability audit after H7G.

The audit contrasts Albumentations BasicTransform replay execution with its
record/default path.  It does not alter the frozen H7G result.
"""

from __future__ import annotations

import ast
import csv
from collections import deque
from pathlib import Path
from typing import Literal

import autocontract_h6_effect_v2 as v2
import autocontract_h7g_albumentations as h7g


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
Mode = Literal["replay", "record"]
TARGET = "albumentations.augmentations.mixing.domain_adaptation.HistogramMatching"


def attribute_name(node: ast.AST) -> str:
    return v2.corpus_v1.attribute_chain(node)


def condition_value(node: ast.AST, mode: Mode) -> bool | None:
    if isinstance(node, ast.Attribute):
        chain = attribute_name(node)
        if chain == "self.replay_mode":
            return mode == "replay"
        if chain == "self.applied_in_replay":
            return mode == "replay"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = condition_value(node.operand, mode)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [condition_value(item, mode) for item in node.values]
        if isinstance(node.op, ast.And):
            if False in values:
                return False
            return True if all(value is True for value in values) else None
        if isinstance(node.op, ast.Or):
            if True in values:
                return True
            return False if all(value is False for value in values) else None
    return None


def self_calls(node: ast.AST) -> tuple[set[str], set[str]]:
    methods: set[str] = set()
    attrs: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        chain = attribute_name(child.func)
        if chain.startswith("self."):
            parts = chain.split(".")
            attrs.add(parts[1])
            if len(parts) == 2:
                methods.add(parts[1])
    return methods, attrs


def block_calls(statements: list[ast.stmt], mode: Mode) -> tuple[set[str], set[str], bool]:
    methods: set[str] = set()
    attrs: set[str] = set()
    for statement in statements:
        if isinstance(statement, ast.If):
            test_methods, test_attrs = self_calls(statement.test)
            methods.update(test_methods)
            attrs.update(test_attrs)
            value = condition_value(statement.test, mode)
            branches = [statement.body] if value is True else [statement.orelse] if value is False else [statement.body, statement.orelse]
            branch_terminated = []
            for branch in branches:
                branch_methods, branch_attrs, terminated = block_calls(branch, mode)
                methods.update(branch_methods)
                attrs.update(branch_attrs)
                branch_terminated.append(terminated)
            if branches and all(branch_terminated):
                return methods, attrs, True
            continue
        statement_methods, statement_attrs = self_calls(statement)
        methods.update(statement_methods)
        attrs.update(statement_attrs)
        if isinstance(statement, (ast.Return, ast.Raise)):
            return methods, attrs, True
    return methods, attrs, False


def root_method_map(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> dict[str, ast.FunctionDef]:
    methods: dict[str, ast.FunctionDef] = {}
    for cls in h7g.class_chain(root, classes):
        for name, method in v2.method_map(cls).items():
            methods.setdefault(name, method)
    return methods


def reachable(root: ast.ClassDef, classes: dict[str, ast.ClassDef], mode: Mode) -> tuple[set[str], set[str]]:
    methods = root_method_map(root, classes)
    queue: deque[str] = deque(("__call__",))
    reached: set[str] = set()
    attrs: set[str] = set()
    while queue:
        name = queue.popleft()
        if name in reached or name not in methods:
            continue
        reached.add(name)
        called_methods, called_attrs, _ = block_calls(methods[name].body, mode)
        attrs.update(called_attrs)
        for called in called_methods:
            if called in methods and called not in reached:
                queue.append(called)
        # _key2func dispatches a record target to the root apply method.
        if name == "apply_with_params" and "apply" in methods:
            queue.append("apply")
    return reached, attrs


def main() -> None:
    binding = h7g.public_binding(TARGET)
    classes, _ = h7g.package_index()
    root = h7g.target_class(binding)
    if root is None:
        raise RuntimeError("HistogramMatching binding missing")
    constructor_attrs = h7g.provenance.constructor_origins(
        root,
        {**classes, root.name: root},
        h7g.package_index()[1],
    )
    rows: list[dict[str, object]] = []
    for mode in ("replay", "record"):
        reached, attrs = reachable(root, classes, mode)
        read_fn_origin = constructor_attrs.get("read_fn", "unknown")
        read_fn_reachable = "read_fn" in attrs
        rows.append(
            {
                "mode": mode,
                "reachable_methods": ";".join(sorted(reached)),
                "read_fn_origin": read_fn_origin,
                "read_fn_reachable": read_fn_reachable,
                "counterfactual_decision": "reject" if read_fn_reachable else "admit",
            }
        )

    path = OUT / "autocontract_h7g_posthoc_mode_reachability.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = "\n".join(
        [
            "# H7G posthoc mode-conditioned reachability (non-gating)",
            "",
            "This audit was designed after the frozen H7G run and does not change H7G=FAIL.",
            "",
            "| Mode | read_fn origin | Reachable? | Counterfactual | Reachable methods |",
            "|---|---|---|---|---|",
            *[
                f"| {row['mode']} | {row['read_fn_origin']} | {row['read_fn_reachable']} | "
                f"{row['counterfactual_decision']} | {row['reachable_methods']} |"
                for row in rows
            ],
            "",
            "In replay mode, BasicTransform.__call__ returns through stored params before sampling helpers. "
            "In record mode, get_params_dependent_on_data reaches _get_reference_image and the public-input read_fn.",
            "",
        ]
    )
    (OUT / "autocontract_h7g_posthoc_mode_reachability.md").write_text(
        report, encoding="utf-8"
    )
    print(report)


if __name__ == "__main__":
    main()
