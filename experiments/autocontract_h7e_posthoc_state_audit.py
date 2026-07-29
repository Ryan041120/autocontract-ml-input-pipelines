"""Non-gating posthoc audit of H7E state paths.

This script was created only after the frozen H7E run.  Its output must never
be used to rewrite the formal H7E result.
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7e_audiomentations as h7e


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
MUTATORS = frozenset(("append", "clear", "extend", "insert", "pop", "remove", "setdefault", "update"))


def state_base(node: ast.AST) -> str:
    current = node
    while isinstance(current, ast.Subscript):
        current = current.value
    chain = v2.corpus_v1.attribute_chain(current)
    return chain if chain.startswith("self.") else ""


def state_paths(nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    writes: set[str] = set()
    reads: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if path := state_base(target):
                        writes.add(path)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                chain = v2.corpus_v1.attribute_chain(child.func)
                parts = chain.split(".")
                if len(parts) >= 3 and parts[0] == "self" and parts[-1] in MUTATORS:
                    writes.add(".".join(parts[:-1]))
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
                chain = v2.corpus_v1.attribute_chain(child)
                if chain.startswith("self."):
                    reads.add(chain)
            if isinstance(child, ast.Subscript) and isinstance(child.ctx, ast.Load):
                if path := state_base(child):
                    reads.add(path)
    return writes, reads


def classify(writes: set[str], reads: set[str]) -> tuple[str, str]:
    has_parameters = "self.parameters" in writes
    has_frozen_guard = "self.are_parameters_frozen" in reads
    other = writes - {"self.parameters"}
    if has_parameters and has_frozen_guard and other:
        return "replayable_parameters+other_state", "requires_parameters_unfrozen+audit_other_state"
    if has_parameters and has_frozen_guard:
        return "replayable_parameters", "requires_parameters_unfrozen"
    if has_parameters:
        return "parameter_buffer", "unknown_parameter_lifetime"
    if other:
        return "other_cross_call_state", "reject_or_prove_overwrite"
    return "none", "none"


def diagnostic_execution_nodes(
    root: ast.ClassDef, classes: dict[str, ast.ClassDef]
) -> list[ast.AST]:
    """Include every hook implementation in the inheritance chain.

    The frozen H7E adapter follows ordinary self-calls but not every super()
    target.  This broader traversal is intentionally posthoc and diagnostic.
    """
    result = list(h7e.execution_nodes(root, classes))
    seen = {id(node) for node in result}
    for cls in v2.class_chain(root, classes):
        for name, method in v2.method_map(cls).items():
            if name in h7e.HOOKS and id(method) not in seen:
                result.append(method)
                seen.add(id(method))
    return result


def main() -> None:
    bindings = h7e.symbol_bindings()
    classes, ambiguous = h7e.package_classes()
    rows: list[dict[str, object]] = []
    for unit in h7e.protocol_units():
        root = h7e.target_class(unit, bindings[unit.public_symbol])
        if root is None or any(base in ambiguous for base in v2.base_names(root)):
            raise RuntimeError(f"posthoc audit cannot resolve {unit.public_symbol}")
        execution = diagnostic_execution_nodes(root, classes)
        writes, reads = state_paths(execution)
        role, obligation = classify(writes, reads)
        rows.append(
            {
                "public_symbol": unit.public_symbol,
                "state_write_paths": ";".join(sorted(writes)) or "none",
                "state_read_paths": ";".join(sorted(reads)) or "none",
                "posthoc_state_role": role,
                "proposed_obligation": obligation,
                "formal_gate_impact": "none",
            }
        )

    csv_path = OUT / "autocontract_h7e_posthoc_state_audit.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    replayable = sum("replayable_parameters" in str(row["posthoc_state_role"]) for row in rows)
    report = "\n".join(
        [
            "# H7E posthoc state audit (non-gating)",
            "",
            "This audit was designed after the formal one-shot H7E run and does not change H7E=PASS.",
            "",
            f"Replayable-parameter state detected: {replayable}/{len(rows)} units.",
            "",
            "| Symbol | State writes | Role | Proposed obligation |",
            "|---|---|---|---|",
            *[
                f"| `{row['public_symbol']}` | {row['state_write_paths']} | "
                f"{row['posthoc_state_role']} | {row['proposed_obligation']} |"
                for row in rows
            ],
            "",
        ]
    )
    (OUT / "autocontract_h7e_posthoc_state_audit.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
