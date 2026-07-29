"""H7A: adapter-assisted EffectV3 and fail-closed Unknown(reason) gate.

This is a mechanism calibration on the already-opened H6 blind corpus, not a
second blind evaluation.  The EffectV2 analyzer remains frozen and unchanged.
Adapters contain framework-level rules only: entrypoints, RNG aliases, record
schema, external base summaries, and sample-lineage/state conventions.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Literal, Protocol

import autocontract_h6_blind_eval as blind
import autocontract_h6_effect_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
Status = Literal["resolved", "unknown"]


@dataclass(frozen=True)
class EffectV3:
    construction_external_reads: frozenset[str]
    construction_external_writes: frozenset[str]
    construction_state_writes: bool
    construction_rng_sources: frozenset[str]
    execution_reads: frozenset[str]
    execution_writes: frozenset[str]
    execution_external_reads: frozenset[str]
    execution_external_writes: frozenset[str]
    rng_direct_sources: frozenset[str]
    rng_delegated: bool
    target_signature: v2.TargetSignature
    target_coupled: bool
    input_cardinality: v2.Cardinality
    output_cardinality: v2.Cardinality
    sample_identity: v2.SampleIdentity
    execution_state_writes: bool


@dataclass(frozen=True)
class AnalysisResult:
    status: Status
    effect: EffectV3 | None
    reasons: tuple[str, ...]
    adapter: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class FrameworkAdapter:
    name: str
    source_id: str
    rules: tuple[str, ...]


ADAPTERS = {
    "monai": FrameworkAdapter(
        "monai",
        "monai_*",
        (
            "Randomizable.self.R is NumPy RNG",
            "__call__ is the execution entrypoint",
            "transform containers carry parametric target/delegation effects",
            "container calls preserve one-sample lineage",
        ),
    ),
    "mmdetection": FrameworkAdapter(
        "mmdetection",
        "mmdet_*",
        (
            "transform is the execution entrypoint",
            "BaseTransform/MMCV transform bases have resolved call semantics",
            "results record keys map to canonical target groups",
            "random/np.random calls map to Python/NumPy RNG",
            "mix_results denotes many-to-one combined lineage",
            "results_cache mutations are execution-state writes",
        ),
    ),
}

BUILTIN_BASES = frozenset(("object", "Enum", "ABC", "Protocol"))
MMDET_EXTERNAL_BASES = frozenset(("BaseTransform", "MMCV_RandomFlip", "MMCV_Pad"))
MMDET_TARGET_TOKENS = {
    "image": ("img", "image", "img_shape"),
    "instances": ("gt_bboxes", "bbox", "bboxes", "gt_masks", "mask"),
    "semantic": ("gt_seg_map", "seg_map", "semantic", "seg"),
    "labels": ("gt_bboxes_labels", "labels", "label"),
}


def adapter_for(source_id: str) -> FrameworkAdapter | None:
    """Select by frozen framework namespace, never by operator name."""
    if source_id.startswith("monai_"):
        return ADAPTERS["monai"]
    if source_id.startswith("mmdet_"):
        return ADAPTERS["mmdetection"]
    return None


def to_v3(effect: v2.EffectV2, execution_state_writes: bool) -> EffectV3:
    return EffectV3(
        *(getattr(effect, field.name) for field in fields(v2.EffectV2)),
        execution_state_writes,
    )


def definitions(source: str) -> tuple[ast.Module, dict[str, ast.ClassDef], dict[str, ast.FunctionDef]]:
    tree = ast.parse(source)
    classes, functions = v2.top_definitions(tree)
    return tree, classes, functions


def execution_nodes(cls: ast.ClassDef, classes: dict[str, ast.ClassDef], entrypoint: str) -> list[ast.AST]:
    chain = v2.class_chain(cls, classes)
    methods: dict[str, ast.FunctionDef] = {}
    for item in chain:
        for name, method in v2.method_map(item).items():
            methods.setdefault(name, method)
    if entrypoint not in methods:
        return []
    result: list[ast.AST] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name not in methods:
            return
        seen.add(name)
        method = methods[name]
        result.append(method)
        for child in ast.walk(method):
            if not isinstance(child, ast.Call):
                continue
            called = v2.corpus_v1.simple_name(child.func)
            if called in methods:
                visit(called)

    visit(entrypoint)
    return result


def execution_state_writes(nodes: list[ast.AST]) -> tuple[bool, tuple[str, ...]]:
    attrs: set[str] = set()
    mutators = frozenset(("append", "extend", "insert", "pop", "remove", "clear", "update", "setdefault"))
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    chain = v2.corpus_v1.attribute_chain(target)
                    if chain.startswith("self."):
                        attrs.add(chain)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                chain = v2.corpus_v1.attribute_chain(child.func)
                parts = chain.split(".")
                if len(parts) >= 3 and parts[0] == "self" and parts[-1] in mutators:
                    attrs.add(".".join(parts[:-1]))
    return bool(attrs), tuple(sorted(attrs))


def external_bases(cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for item in v2.class_chain(cls, classes)
            for name in v2.base_names(item)
            if name not in classes and name not in BUILTIN_BASES
        )
    )


def generic_analyze(unit: v2.V2Unit, source: str) -> AnalysisResult:
    _, classes, functions = definitions(source)
    root = {**classes, **functions}[unit.name]
    prediction, evidence = v2.infer(unit, source)
    reasons: set[str] = set()

    if isinstance(root, ast.ClassDef):
        methods = {name for item in v2.class_chain(root, classes) for name in v2.method_map(item)}
        unknown_bases = external_bases(root, classes)
        if unknown_bases:
            reasons.add("unresolved_external_base:" + "+".join(unknown_bases))
        recognized = {"__call__", "forward", "get_params"} | {name for name in methods if name.startswith("apply_")}
        if not (methods & recognized):
            if "transform" in methods:
                reasons.add("unrecognized_execution_entrypoint:transform")
            else:
                reasons.add("missing_execution_entrypoint")
    else:
        reasons.add("unresolved_factory_execution_semantics")

    if "self.R" in source and unit.source_id.startswith("monai_"):
        reasons.add("unresolved_rng_alias:self.R")
    if unit.source_id.startswith("dali_"):
        reasons.add("unsupported_backend_graph:dali")

    if reasons:
        return AnalysisResult(
            "unknown", None, tuple(sorted(reasons)), "generic",
            (f"v2_execution_nodes={evidence['execution_nodes']}",),
        )

    # Generic analysis is only resolved when its own execution graph is known.
    tree_classes = classes
    nodes: list[ast.AST] = []
    if isinstance(root, ast.ClassDef):
        entry = next((name for name in ("__call__", "forward") if name in v2.method_map(root)), "")
        nodes = execution_nodes(root, tree_classes, entry) if entry else []
    stateful, attrs = execution_state_writes(nodes)
    return AnalysisResult(
        "resolved", to_v3(prediction, stateful), (), "generic",
        tuple(f"execution_state:{attr}" for attr in attrs),
    )


def monai_analyze(unit: v2.V2Unit, source: str) -> AnalysisResult:
    _, classes, _ = definitions(source)
    root = classes[unit.name]
    prediction, _ = v2.infer(unit, source)
    nodes = execution_nodes(root, classes, "__call__")
    if not nodes:
        return AnalysisResult("unknown", None, ("adapter_entrypoint_missing:__call__",), "monai", ())
    stateful, attrs = execution_state_writes(nodes)
    effect = EffectV3(
        prediction.construction_external_reads,
        prediction.construction_external_writes,
        prediction.construction_state_writes,
        prediction.construction_rng_sources,
        frozenset(("parametric",)),
        frozenset(("parametric",)),
        prediction.execution_external_reads,
        prediction.execution_external_writes,
        frozenset(("numpy",)),
        True,
        "parametric",
        True,
        "one",
        "one",
        "preserve",
        stateful,
    )
    return AnalysisResult(
        "resolved", effect, (), "monai",
        ("entrypoint:__call__", "rng_alias:self.R->numpy", "schema:parametric")
        + tuple(f"execution_state:{attr}" for attr in attrs),
    )


def mmdet_targets(nodes: list[ast.AST]) -> frozenset[str]:
    tokens = v2.corpus_v1.identifier_tokens(nodes)
    rendered = " ".join(ast.unparse(node) for node in nodes)
    targets = {
        canonical
        for canonical, aliases in MMDET_TARGET_TOKENS.items()
        if any(alias in tokens or f"'{alias}'" in rendered or f'"{alias}"' in rendered for alias in aliases)
    }
    return frozenset(targets or ("image",))


def mmdet_analyze(unit: v2.V2Unit, source: str) -> AnalysisResult:
    _, classes, _ = definitions(source)
    root = classes[unit.name]
    prediction, _ = v2.infer(unit, source)
    unknown_bases = tuple(name for name in external_bases(root, classes) if name not in MMDET_EXTERNAL_BASES)
    if unknown_bases:
        return AnalysisResult(
            "unknown", None,
            ("adapter_missing_external_base_summary:" + "+".join(unknown_bases),),
            "mmdetection", (),
        )
    external_base_set = set(external_bases(root, classes))
    nodes = execution_nodes(root, classes, "transform")
    inherited_entrypoint = False
    if not nodes and "MMCV_RandomFlip" in external_base_set:
        # The adapter's external-base summary says the inherited transform()
        # dispatches into the subclass hooks. Analyze those local hooks rather
        # than inventing an operator-specific admission rule.
        nodes = [
            method
            for name, method in v2.method_map(root).items()
            if name not in v2.CONSTRUCTION_METHODS and not name.startswith(v2.ADMIN_PREFIXES)
        ]
        inherited_entrypoint = bool(nodes)
    if not nodes:
        return AnalysisResult("unknown", None, ("adapter_entrypoint_missing:transform",), "mmdetection", ())
    targets = mmdet_targets(nodes)
    rendered = "\n".join(ast.unparse(node) for node in nodes)
    mix = "mix_results" in rendered or "results_cache" in rendered
    stateful, attrs = execution_state_writes(nodes)
    rng = v2.rng_sources(nodes)
    delegated = "MMCV_RandomFlip" in external_base_set
    effect = EffectV3(
        prediction.construction_external_reads,
        prediction.construction_external_writes,
        prediction.construction_state_writes,
        prediction.construction_rng_sources,
        targets,
        targets,
        frozenset(),
        frozenset(),
        rng,
        delegated,
        "fixed",
        len(targets) > 1 or mix,
        "many" if mix else "one",
        "one",
        "combine" if mix else "preserve",
        stateful,
    )
    return AnalysisResult(
        "resolved", effect, (), "mmdetection",
        (
            "entrypoint:external-base-transform" if inherited_entrypoint else "entrypoint:transform",
            "record_schema:results",
            f"lineage:{'combine' if mix else 'preserve'}",
        )
        + tuple(f"execution_state:{attr}" for attr in attrs),
    )


def analyze(unit: v2.V2Unit, source: str) -> AnalysisResult:
    generic = generic_analyze(unit, source)
    adapter = adapter_for(unit.source_id)
    if adapter is None:
        return generic
    if adapter.name == "monai":
        return monai_analyze(unit, source)
    if adapter.name == "mmdetection":
        return mmdet_analyze(unit, source)
    raise AssertionError(adapter.name)


def validator_reasons(result: AnalysisResult) -> tuple[str, ...]:
    if result.status == "unknown" or result.effect is None:
        return ("analysis_unknown",) + result.reasons
    effect = result.effect
    reasons: list[str] = []
    if effect.target_signature == "parametric":
        reasons.append("parametric_target_signature")
    if effect.input_cardinality != "one" or effect.output_cardinality != "one":
        reasons.append(f"unsupported_cardinality:{effect.input_cardinality}->{effect.output_cardinality}")
    if effect.sample_identity == "combine":
        reasons.append("combined_sample_identity")
    if effect.execution_state_writes:
        reasons.append("execution_state_write")
    if effect.execution_external_reads or effect.execution_external_writes:
        reasons.append("execution_external_effect")
    # Delegation is admissible only after a framework adapter has supplied its
    # semantics; generic unresolved delegation already produces Unknown.
    if effect.rng_delegated and result.adapter == "generic":
        reasons.append("unresolved_delegated_effect")
    return tuple(reasons)


def text_value(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, frozenset):
        return "+".join(sorted(value)) or "none"
    if isinstance(value, tuple):
        return ";".join(value) or "none"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    freeze = blind.verify_frozen_analyzer()
    units = blind.load_oracle()
    sources, _ = blind.fetch_sources()
    rows: list[dict[str, object]] = []
    generic_counterfactual_safe_accepts = 0
    for unit, unsafe in units:
        generic_result = generic_analyze(unit, sources[unit.source_id])
        if not unsafe and not validator_reasons(generic_result):
            generic_counterfactual_safe_accepts += 1
        result = analyze(unit, sources[unit.source_id])
        reject_reasons = validator_reasons(result)
        rejected = bool(reject_reasons)
        row: dict[str, object] = {
            "source_id": unit.source_id,
            "unit": unit.name,
            "unsafe_for_unary_optimizer": unsafe,
            "analysis_status": result.status,
            "adapter": result.adapter,
            "analysis_reasons": text_value(result.reasons),
            "validator_reject": rejected,
            "validator_reasons": text_value(reject_reasons),
            "decision_correct": rejected == unsafe,
            "evidence": text_value(result.evidence),
        }
        for field in fields(EffectV3):
            row[f"effect_{field.name}"] = text_value(
                getattr(result.effect, field.name) if result.effect else None
            )
        rows.append(row)

    unsafe_rows = [row for row in rows if row["unsafe_for_unary_optimizer"] is True]
    safe_supported = [
        row for row in rows
        if row["unsafe_for_unary_optimizer"] is False and row["adapter"] != "generic"
    ]
    unsupported = [row for row in rows if row["adapter"] == "generic"]
    false_accepts = [row for row in unsafe_rows if row["validator_reject"] is False]
    safe_accepts = [row for row in safe_supported if row["validator_reject"] is False]
    reasoned_unknowns = [
        row for row in unsupported
        if row["analysis_status"] == "unknown" and row["analysis_reasons"] != "none"
    ]
    decision_correct = sum(row["decision_correct"] is True for row in rows)
    adapter_rules = sum(len(adapter.rules) for adapter in ADAPTERS.values())
    supported_units = sum(row["adapter"] != "generic" for row in rows)
    effect_fields = len(fields(EffectV3))
    summary = {
        "protocol": "H7A post-blind mechanism calibration",
        "units": len(rows),
        "decisions_correct": decision_correct,
        "decision_accuracy": decision_correct / len(rows),
        "known_unsafe_false_accepts": len(false_accepts),
        "supported_safe_units": len(safe_supported),
        "supported_safe_accepts": len(safe_accepts),
        "supported_safe_recall": len(safe_accepts) / len(safe_supported),
        "generic_unknown_reject_safe_recall": generic_counterfactual_safe_accepts / len(safe_supported),
        "unsupported_units": len(unsupported),
        "unsupported_reasoned_unknowns": len(reasoned_unknowns),
        "unsupported_reason_coverage": len(reasoned_unknowns) / len(unsupported),
        "adapter_rules": adapter_rules,
        "supported_units_total": supported_units,
        "rules_per_supported_unit": adapter_rules / supported_units,
        "effect_v3_fields": effect_fields,
        "effect_cell_equivalent_reduction": 1 - adapter_rules / (supported_units * effect_fields),
        "h7a_safety_recall_mechanism_pass": (
            not false_accepts
            and len(safe_accepts) / len(safe_supported) >= 0.70
            and len(reasoned_unknowns) == len(unsupported)
        ),
        "h7_overall_pass": False,
        "frozen_effect_v2_sha256": freeze["analyzer_sha256"],
        "h7_analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    write_csv(OUT / "autocontract_h7_decisions.csv", rows)
    write_csv(OUT / "autocontract_h7_summary.csv", [summary])
    manifest = {
        "protocol": summary["protocol"],
        "adapters": [asdict(adapter) for adapter in ADAPTERS.values()],
        "cost_note": (
            "Rules are structural framework facts, not per-operator labels. "
            "Effect-cell-equivalent reduction is descriptive and not yet a valid annotation-time comparison."
        ),
    }
    (OUT / "autocontract_h7_adapter_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    report = "\n".join(
        [
            "# AutoContract H7A adapter mechanism calibration",
            "",
            "> This reuses the opened H6 blind set for postmortem calibration; it is not a new blind result.",
            "",
            f"Decisions correct: {decision_correct}/{len(rows)} ({decision_correct / len(rows):.1%}).",
            f"Known-unsafe false accepts: {len(false_accepts)}.",
            f"Supported safe recall: {len(safe_accepts)}/{len(safe_supported)} ({len(safe_accepts) / len(safe_supported):.1%}).",
            f"Generic unknown-reject safe recall counterfactual: {generic_counterfactual_safe_accepts}/{len(safe_supported)} "
            f"({generic_counterfactual_safe_accepts / len(safe_supported):.1%}).",
            f"Unsupported reason coverage: {len(reasoned_unknowns)}/{len(unsupported)} ({len(reasoned_unknowns) / len(unsupported):.1%}).",
            f"H7A safety/recall mechanism gate: **{'PASS' if summary['h7a_safety_recall_mechanism_pass'] else 'FAIL'}**.",
            "H7 overall gate: **INCOMPLETE** (adapters are not frozen and no unseen-project holdout has run).",
            "",
            "## Decisions",
            "",
            "| Unit | Adapter | Status | Decision | Correct | Reason |",
            "|---|---|---|---|---:|---|",
            *[
                f"| `{row['source_id']}::{row['unit']}` | {row['adapter']} | {row['analysis_status']} | "
                f"{'reject' if row['validator_reject'] else 'admit'} | {'yes' if row['decision_correct'] else 'no'} | "
                f"{row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "## Adapter cost (not yet a passed gate)",
            "",
            f"Two adapters contain {adapter_rules} structural rules for {supported_units} evaluated units "
            f"({adapter_rules / supported_units:.2f} rules/unit). Against {effect_fields} per-unit EffectV3 fields, "
            f"the descriptive cell-equivalent reduction is {summary['effect_cell_equivalent_reduction']:.1%}.",
            "This is not yet an annotation-time measurement and cannot establish the >=70% amortization claim.",
            "",
            "## Interpretation",
            "",
            "The assumption reversal worked on the calibration set: unsupported semantics became explicit Unknown outputs, "
            "while framework facts recovered the two safe MMDetection opportunities. The next valid test is to freeze "
            "these rules and evaluate unseen MONAI/MMDetection projects or versions without editing the adapters.",
            "",
        ]
    )
    (OUT / "autocontract_h7_adapters.md").write_text(report, encoding="utf-8")
    print(report)
    if not summary["h7a_safety_recall_mechanism_pass"]:
        raise RuntimeError("H7A safety/recall mechanism gate failed")


if __name__ == "__main__":
    main()
