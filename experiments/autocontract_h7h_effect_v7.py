"""EffectV7: mode- and phase-conditioned reachable effects.

V7 is calibrated only on completed H7C/H7E/H7F/H7G corpora.  It leaves every
frozen result untouched and makes path reachability, rather than class-wide
effect presence, authoritative for validation.
"""

from __future__ import annotations

import ast
import csv
import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import autocontract_h6_effect_v2 as v2
import autocontract_h7d_effect_v4 as v4
import autocontract_h7e_audiomentations as h7e
import autocontract_h7f_effect_v5 as v5
import autocontract_h7f_imgaug as h7f
import autocontract_h7g_albumentations as h7g
import autocontract_h7g_effect_v6 as v6


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
Phase = Literal["construction", "sample_apply", "replay_apply"]


@dataclass(frozen=True)
class ReachabilityContext:
    configuration: str
    phase: Phase
    values: tuple[tuple[str, str], ...]

    def environment(self) -> dict[str, str]:
        return dict(self.values)


@dataclass(frozen=True)
class ReachableSlice:
    context: ReachabilityContext
    methods: tuple[str, ...]
    guards: tuple[str, ...]
    state_accesses: tuple[v6.StateAccessV6, ...]
    callable_bindings: tuple[v6.CallableBinding, ...]
    rng_paths: tuple[str, ...]
    sampling_rng: bool
    delegation: v4.DelegationKind
    unresolved_dispatch: tuple[str, ...]


@dataclass(frozen=True)
class EffectV7:
    predecessor: v6.EffectV6
    reachable: ReachableSlice


@dataclass(frozen=True)
class AnalysisV7:
    status: Literal["resolved", "unknown"]
    effect: EffectV7
    inherited_reasons: tuple[str, ...]
    evidence: tuple[str, ...]
    adapter: str


V7_RULES = (
    "effects are attached to (configuration, phase, reachable path), not to a class globally",
    "self and super helper calls are closed transitively from the framework entrypoint",
    "known mode predicates and params-is-None predicates prune unreachable branches",
    "sampling/RNG, callable, state, and delegation effects are collected only from reachable nodes",
    "provided compatible parameter records discharge sampling but not unresolved child effects",
    "unknown conditions and dynamic dispatch are over-approximated and fail closed when safety-relevant",
    "the oracle labels operations as (public symbol, configuration, phase)",
)


def attribute_chain(node: ast.AST) -> str:
    return v2.corpus_v1.attribute_chain(node)


def condition_value(node: ast.AST, env: dict[str, str]) -> bool | None:
    """Evaluate only predicates explicitly fixed by the active context."""
    if isinstance(node, ast.Attribute):
        value = env.get(attribute_chain(node))
        if value in ("true", "false"):
            return value == "true"
    if isinstance(node, ast.Name):
        value = env.get(node.id)
        if value in ("true", "false"):
            return value == "true"
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = condition_value(node.operand, env)
        return None if value is None else not value
    if isinstance(node, ast.BoolOp):
        values = [condition_value(item, env) for item in node.values]
        if isinstance(node.op, ast.And):
            if False in values:
                return False
            return True if all(value is True for value in values) else None
        if isinstance(node.op, ast.Or):
            if True in values:
                return True
            return False if all(value is False for value in values) else None
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
        left, right = node.left, node.comparators[0]
        name: str | None = None
        if isinstance(left, ast.Name) and isinstance(right, ast.Constant) and right.value is None:
            name = left.id
        elif isinstance(right, ast.Name) and isinstance(left, ast.Constant) and left.value is None:
            name = right.id
        if name is not None and env.get(name) in ("none", "provided"):
            is_none = env[name] == "none"
            if isinstance(node.ops[0], (ast.Is, ast.Eq)):
                return is_none
            if isinstance(node.ops[0], (ast.IsNot, ast.NotEq)):
                return not is_none
    return None


@dataclass
class BlockScan:
    nodes: list[ast.AST]
    guards: list[str]
    terminated: bool


def scan_block(statements: list[ast.stmt], env: dict[str, str]) -> BlockScan:
    """Flatten only reachable statement fragments and stop after definite returns."""
    nodes: list[ast.AST] = []
    guards: list[str] = []
    for statement in statements:
        if isinstance(statement, ast.If):
            nodes.append(statement.test)
            value = condition_value(statement.test, env)
            rendered = ast.unparse(statement.test)
            guards.append(f"{rendered}={value if value is not None else 'unknown'}")
            branches = (
                [statement.body]
                if value is True
                else [statement.orelse]
                if value is False
                else [statement.body, statement.orelse]
            )
            scans = [scan_block(branch, env) for branch in branches]
            for scan in scans:
                nodes.extend(scan.nodes)
                guards.extend(scan.guards)
            if branches and all(scan.terminated for scan in scans):
                return BlockScan(nodes, guards, True)
            continue
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            nodes.extend((statement.target, statement.iter))
            body = scan_block(statement.body, env)
            otherwise = scan_block(statement.orelse, env)
            nodes.extend(body.nodes + otherwise.nodes)
            guards.extend(body.guards + otherwise.guards)
            continue
        if isinstance(statement, ast.While):
            nodes.append(statement.test)
            body = scan_block(statement.body, env)
            otherwise = scan_block(statement.orelse, env)
            nodes.extend(body.nodes + otherwise.nodes)
            guards.extend(body.guards + otherwise.guards)
            continue
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            nodes.extend(item.context_expr for item in statement.items)
            nested = scan_block(statement.body, env)
            nodes.extend(nested.nodes)
            guards.extend(nested.guards)
            if nested.terminated:
                return BlockScan(nodes, guards, True)
            continue
        if isinstance(statement, ast.Try):
            groups = [statement.body, statement.orelse, statement.finalbody]
            groups.extend(handler.body for handler in statement.handlers)
            scans = [scan_block(group, env) for group in groups if group]
            for scan in scans:
                nodes.extend(scan.nodes)
                guards.extend(scan.guards)
            continue
        nodes.append(statement)
        if isinstance(statement, (ast.Return, ast.Raise)):
            return BlockScan(nodes, guards, True)
    return BlockScan(nodes, guards, False)


def method_chain(root: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    return v2.class_chain(root, {**classes, root.name: root})


def resolve_method(
    chain: list[ast.ClassDef], name: str, start: int = 0
) -> tuple[int, ast.FunctionDef] | None:
    for index in range(start, len(chain)):
        method = v2.method_map(chain[index]).get(name)
        if method is not None:
            return index, method
    return None


def reachable_nodes(
    root: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    entrypoint: str,
    context: ReachabilityContext,
    dispatch: dict[str, tuple[str, ...]] | None = None,
) -> tuple[list[ast.AST], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Close self/super helper calls using a conservative source-level MRO."""
    chain = method_chain(root, classes)
    entry = resolve_method(chain, entrypoint)
    if entry is None:
        return [], (), (), (f"missing_entrypoint:{entrypoint}",)
    queue: deque[tuple[int, str, ast.FunctionDef]] = deque(((entry[0], entrypoint, entry[1]),))
    seen: set[tuple[int, str]] = set()
    nodes: list[ast.AST] = []
    methods: list[str] = []
    guards: list[str] = []
    unresolved: set[str] = set()
    env = context.environment()
    while queue:
        class_index, name, method = queue.popleft()
        key = (class_index, name)
        if key in seen:
            continue
        seen.add(key)
        methods.append(f"{chain[class_index].name}.{name}")
        scan = scan_block(method.body, env)
        nodes.extend(scan.nodes)
        guards.extend(scan.guards)
        for fragment in scan.nodes:
            for child in ast.walk(fragment):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Attribute):
                    receiver = child.func.value
                    if isinstance(receiver, ast.Name) and receiver.id == "self":
                        target = resolve_method(chain, child.func.attr)
                        if target is not None:
                            queue.append((target[0], child.func.attr, target[1]))
                    elif (
                        isinstance(receiver, ast.Call)
                        and isinstance(receiver.func, ast.Name)
                        and receiver.func.id == "super"
                    ):
                        target = resolve_method(chain, child.func.attr, class_index + 1)
                        if target is None:
                            unresolved.add("super." + child.func.attr)
                        else:
                            queue.append((target[0], child.func.attr, target[1]))
        for source, targets in (dispatch or {}).items():
            if any(item.endswith("." + source) for item in methods):
                for target_name in targets:
                    target = resolve_method(chain, target_name)
                    if target is not None:
                        queue.append((target[0], target_name, target[1]))
                    else:
                        unresolved.add("dispatch." + target_name)
    return nodes, tuple(methods), tuple(dict.fromkeys(guards)), tuple(sorted(unresolved))


def invoked_self_attrs(nodes: list[ast.AST]) -> set[str]:
    result: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = attribute_chain(child.func)
            if chain.startswith("self."):
                result.add(chain.split(".", 2)[1])
    return result


def albumentations_callable_bindings(
    root: ast.ClassDef,
    classes: dict[str, ast.ClassDef],
    functions: set[str],
    nodes: list[ast.AST],
) -> tuple[v6.CallableBinding, ...]:
    origins = h7g.provenance.constructor_origins(
        root, {**classes, root.name: root}, functions
    )
    invoked = invoked_self_attrs(nodes)
    origin_map: dict[str, v6.CallableOrigin] = {
        "module_symbol": "module_bound",
        "user_input": "public_input",
        "user_derived": "public_input_derived",
        "internal": "module_bound",
        "unknown": "unknown",
    }
    result: dict[str, v6.CallableOrigin] = {}
    for attr in invoked & set(origins):
        if any(token in attr.lower() for token in ("func", "fn", "callable")):
            result[attr] = origin_map[origins[attr]]
    for attr in h7g.container_callable_attrs(root):
        if attr.split(".", 1)[1].split("[", 1)[0] in invoked:
            result[attr] = "public_input"
    return tuple(v6.CallableBinding(name, result[name]) for name in sorted(result))


def state_accesses(nodes: list[ast.AST], rng_paths: set[str]) -> tuple[v6.StateAccessV6, ...]:
    accesses = v5.state_accesses(nodes)
    result = [
        v6.StateAccessV6(
            item.path,
            "delegated_mutation" if item.path in rng_paths else item.kind,
        )
        for item in accesses
    ]
    for path in sorted(rng_paths):
        if not any(item.path == path for item in result):
            result.append(v6.StateAccessV6(path, "delegated_mutation"))
    return tuple(sorted(result, key=lambda item: (item.path, item.kind)))


def albumentations_v7(
    binding: dict[str, object],
    classes: dict[str, ast.ClassDef],
    functions: set[str],
    configuration: str,
) -> AnalysisV7:
    root = h7g.target_class(binding)
    prior = h7g.analyze(binding, classes, functions)
    if root is None:
        empty = ReachableSlice(
            ReachabilityContext(configuration, "replay_apply", ()),
            (), (), (), (v6.CallableBinding("<missing>", "unknown"),), (), False,
            "none", ("missing_root",),
        )
        return AnalysisV7("unknown", EffectV7(prior.effect, empty), prior.reasons, (), "albumentations-v7")
    replay = configuration == "albumentations.replay"
    context = ReachabilityContext(
        configuration,
        "replay_apply" if replay else "sample_apply",
        (
            ("self.replay_mode", "true" if replay else "false"),
            ("self.applied_in_replay", "true" if replay else "false"),
        ),
    )
    nodes, methods, guards, unresolved = reachable_nodes(
        root,
        classes,
        "__call__",
        context,
        dispatch={"apply_with_params": ("apply",)},
    )
    rng_paths = h7g.rng_accesses(nodes)
    callables = albumentations_callable_bindings(root, classes, functions, nodes)
    child = h7g.is_compose(root, classes) and h7g.has_child_delegation(
        h7g.inherited_execution_nodes(root, classes)
    )
    inherited = list(
        v6.validator_v6(
            prior,
            frozenset(("albumentations.replay",)) if replay else frozenset(),
            frozenset(("framework_specific",)) if replay else frozenset(),
        )
    )
    inherited = [
        reason
        for reason in inherited
        if "callable" not in reason
        and not reason.startswith("unsatisfied_named_mode:")
        and reason != "missing_named_mode_obligation"
        and reason != "unresolved_child_effect"
    ]
    reachable = ReachableSlice(
        context,
        methods,
        guards,
        state_accesses(nodes, rng_paths),
        callables,
        tuple(sorted(rng_paths)),
        bool(rng_paths),
        "child_operator" if child else "none",
        unresolved,
    )
    effect = EffectV7(prior.effect, reachable)
    reasons = validator_v7(AnalysisV7("resolved", effect, tuple(inherited), (), "albumentations-v7"))
    evidence = (
        "reachable_methods:" + ",".join(methods),
        "guards:" + (",".join(guards) or "none"),
        "reachable_callables:" + (",".join(f"{x.attribute}={x.origin}" for x in callables) or "none"),
    )
    return AnalysisV7("unknown" if reasons else "resolved", effect, tuple(inherited), evidence, "albumentations-v7")


def validator_v7(result: AnalysisV7) -> tuple[str, ...]:
    reasons = list(result.inherited_reasons)
    reachable = result.effect.reachable
    if reachable.delegation == "child_operator":
        reasons.append("unresolved_child_effect")
    if reachable.sampling_rng:
        reasons.append("reachable_sampling_rng")
    for binding in reachable.callable_bindings:
        if binding.origin in ("public_input", "public_input_derived", "external_dynamic", "unknown"):
            reasons.append("unresolved_callable_origin:" + binding.origin)
    if reachable.unresolved_dispatch:
        reasons.append("unresolved_reachable_dispatch")
    return tuple(dict.fromkeys(reasons))


def coarse_match(expected: str, reasons: tuple[str, ...]) -> bool:
    if expected == "none":
        return not reasons
    mapping = {
        "user_callable": "callable",
        "sampling_rng": "sampling_rng",
        "child": "child",
    }
    return any(mapping.get(expected, expected) in reason for reason in reasons)


def legacy_v6_rows() -> list[dict[str, object]]:
    """Re-run all 34 predecessor calibration units through a V7 compatibility view."""
    rows: list[dict[str, object]] = []
    protocol = v4.h7c.load_protocol()
    common = protocol["adapter_calibration"]["common_files"]
    for unit in v4.expected_units():
        result = v6.wrap_v5(v5.wrap_v4(v4.infer_v4(unit["name"], unit["path"], common)), "torchio")
        reasons = v6.validator_v6(result)
        rows.append({"corpus": "TorchIO", "unit": unit["name"], "configuration": "legacy", "phase": "sample_apply", "expected": unit["expected"], "actual": "reject" if reasons else "admit", "reason_match": v6.reason_match(unit["reason"], reasons)})
    bindings = h7e.symbol_bindings()
    classes, ambiguous = h7e.package_classes()
    for unit in h7e.protocol_units():
        prior = v5.infer_audiomentations_v5(unit, bindings[unit.public_symbol], classes, ambiguous)
        result = v6.wrap_v5(prior, "audiomentations")
        reasons = v6.validator_v6(result, frozenset(("audiomentations.parameters_unfrozen",)), frozenset(("parameters_unfrozen",)))
        rows.append({"corpus": "audiomentations", "unit": unit.public_symbol, "configuration": "legacy", "phase": "sample_apply", "expected": unit.expected, "actual": "reject" if reasons else "admit", "reason_match": v6.reason_match(unit.coarse_reason, reasons)})
    img_classes = h7f.package_classes()
    units = [h7f.Unit(*item) for item in h7f.CALIBRATION_UNITS] + h7f.protocol_units()
    formal = {item["public_symbol"]: item for item in json.loads(h7f.SYMBOLS.read_text(encoding="utf-8"))["bindings"]}
    for unit in units:
        binding = formal.get(unit.public_symbol) or h7f.public_binding(unit.public_symbol)
        result = v6.infer_imgaug_v6(binding, img_classes)
        reasons = v6.validator_v6(result, frozenset(("imgaug.deterministic",)), frozenset(("framework_specific",)))
        rows.append({"corpus": "imgaug", "unit": unit.public_symbol, "configuration": "legacy", "phase": "replay_apply", "expected": unit.expected, "actual": "reject" if reasons else "admit", "reason_match": v6.reason_match(unit.coarse_reason, reasons)})
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rows = legacy_v6_rows()
    classes, functions = h7g.package_index()
    manifest = json.loads(h7g.SYMBOLS.read_text(encoding="utf-8"))
    bindings = {item["public_symbol"]: item for item in manifest["bindings"]}
    histogram = "albumentations.augmentations.mixing.domain_adaptation.HistogramMatching"
    for configuration, expected, reason in (
        ("albumentations.replay", "admit", "none"),
        ("albumentations.record", "reject", "user_callable"),
    ):
        result = albumentations_v7(bindings[histogram], classes, functions, configuration)
        reasons = validator_v7(result)
        rows.append({"corpus": "Albumentations-H7G-posthoc", "unit": histogram, "configuration": configuration, "phase": result.effect.reachable.context.phase, "expected": expected, "actual": "reject" if reasons else "admit", "reason_match": coarse_match(reason, reasons)})
    for row in rows:
        row["decision_correct"] = row["actual"] == row["expected"]
    path = OUT / "autocontract_h7h_v7_calibration.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    correct = sum(row["decision_correct"] is True for row in rows)
    reason_correct = sum(row["reason_match"] is True for row in rows)
    contrasts = rows[-2:]
    ready = correct == len(rows) and reason_correct == len(rows) and contrasts[0]["actual"] != contrasts[1]["actual"]
    summary = {"units": len(rows), "decisions_correct": correct, "reason_categories_correct": reason_correct, "phase_contrast_correct": contrasts[0]["actual"] == "admit" and contrasts[1]["actual"] == "reject", "effect_v7_freeze_ready": ready}
    with (OUT / "autocontract_h7h_v7_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary))
        writer.writeheader(); writer.writerow(summary)
    (OUT / "autocontract_h7h_v7_manifest.json").write_text(json.dumps({"schema": {"key": ["configuration", "phase", "reachable_path"], "phases": ["construction", "sample_apply", "replay_apply"]}, "rules": V7_RULES, "calibration_corpora": ["TorchIO", "audiomentations", "imgaug", "completed H7G posthoc contrast"]}, indent=2), encoding="utf-8")
    report = "\n".join(["# AutoContract EffectV7 calibration", "", f"Decisions: {correct}/{len(rows)}; reason categories: {reason_correct}/{len(rows)}.", f"H7G phase contrast: replay={contrasts[0]['actual']}, record={contrasts[1]['actual']}.", f"Freeze ready: **{'YES' if ready else 'NO'}**.", "", "| Corpus | Unit | Configuration | Phase | Expected | Actual |", "|---|---|---|---|---|---|", *[f"| {row['corpus']} | `{row['unit']}` | {row['configuration']} | {row['phase']} | {row['expected']} | {row['actual']} |" for row in rows], ""])
    (OUT / "autocontract_h7h_v7_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if not ready:
        raise RuntimeError("EffectV7 is not freeze-ready")


if __name__ == "__main__":
    main()
