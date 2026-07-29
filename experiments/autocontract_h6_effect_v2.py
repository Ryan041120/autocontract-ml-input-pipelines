"""EffectV2 calibration on the already-opened H6 GitHub corpus.

The sealed MONAI/MMDetection/DALI repositories are intentionally absent from
this file.  This script separates construction from execution, direct from
delegated randomness, and fixed from parametric target signatures.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal

import autocontract_h6_github_corpus as corpus_v1


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
TargetSignature = Literal["fixed", "parametric"]
Cardinality = Literal["one", "many"]
SampleIdentity = Literal["preserve", "combine"]


@dataclass(frozen=True)
class EffectV2:
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
    target_signature: TargetSignature
    target_coupled: bool
    input_cardinality: Cardinality
    output_cardinality: Cardinality
    sample_identity: SampleIdentity


@dataclass(frozen=True)
class V2Unit:
    source_id: str
    kind: Literal["class", "function"]
    name: str
    truth: EffectV2


def fx(
    *,
    construction_external_reads: tuple[str, ...] = (),
    construction_external_writes: tuple[str, ...] = (),
    construction_state_writes: bool = False,
    construction_rng_sources: tuple[str, ...] = (),
    execution_reads: tuple[str, ...] = ("image",),
    execution_writes: tuple[str, ...] = ("image",),
    execution_external_reads: tuple[str, ...] = (),
    execution_external_writes: tuple[str, ...] = (),
    rng_direct_sources: tuple[str, ...] = (),
    rng_delegated: bool = False,
    target_signature: TargetSignature = "fixed",
    target_coupled: bool = False,
    input_cardinality: Cardinality = "one",
    output_cardinality: Cardinality = "one",
    sample_identity: SampleIdentity = "preserve",
) -> EffectV2:
    return EffectV2(
        frozenset(construction_external_reads),
        frozenset(construction_external_writes),
        construction_state_writes,
        frozenset(construction_rng_sources),
        frozenset(execution_reads),
        frozenset(execution_writes),
        frozenset(execution_external_reads),
        frozenset(execution_external_writes),
        frozenset(rng_direct_sources),
        rng_delegated,
        target_signature,
        target_coupled,
        input_cardinality,
        output_cardinality,
        sample_identity,
    )


PARAMETRIC = ("parametric",)
DETECTION = ("image", "instances", "semantic", "keypoints", "labels", "depth")
MIX_TARGETS = ("image", "instances", "semantic", "labels")

UNITS = (
    V2Unit("vision_presets", "class", "ClassificationPresetTrain", fx(construction_state_writes=True, rng_delegated=True)),
    V2Unit("vision_presets", "class", "ClassificationPresetEval", fx(construction_state_writes=True)),
    V2Unit("timm_factory", "function", "transforms_noaug_train", fx()),
    V2Unit("timm_factory", "function", "transforms_imagenet_train", fx(rng_delegated=True)),
    V2Unit("timm_factory", "function", "transforms_imagenet_eval", fx()),
    V2Unit(
        "ultralytics_augment", "class", "Mosaic",
        fx(
            construction_external_reads=("dataset",), construction_state_writes=True,
            execution_reads=MIX_TARGETS, execution_writes=MIX_TARGETS,
            execution_external_reads=("dataset",), rng_direct_sources=("python",), rng_delegated=True,
            target_coupled=True, input_cardinality="many", sample_identity="combine",
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "MixUp",
        fx(
            construction_state_writes=True, execution_reads=MIX_TARGETS, execution_writes=MIX_TARGETS,
            execution_external_reads=("dataset",), rng_direct_sources=("numpy", "python"), rng_delegated=True,
            target_coupled=True, input_cardinality="many", sample_identity="combine",
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "CutMix",
        fx(
            construction_state_writes=True, execution_reads=MIX_TARGETS, execution_writes=MIX_TARGETS,
            execution_external_reads=("dataset",), rng_direct_sources=("numpy", "python"), rng_delegated=True,
            target_coupled=True, input_cardinality="many", sample_identity="combine",
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "CopyPaste",
        fx(
            construction_state_writes=True, execution_reads=MIX_TARGETS, execution_writes=MIX_TARGETS,
            execution_external_reads=("dataset",), rng_direct_sources=("python",), rng_delegated=True,
            target_coupled=True, input_cardinality="many", sample_identity="combine",
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "RandomPerspective",
        fx(
            construction_state_writes=True, execution_reads=DETECTION, execution_writes=DETECTION,
            rng_direct_sources=("python",), target_coupled=True,
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "RandomHSV",
        fx(construction_state_writes=True, rng_direct_sources=("numpy",)),
    ),
    V2Unit(
        "ultralytics_augment", "class", "RandomFlip",
        fx(
            construction_state_writes=True, execution_reads=DETECTION, execution_writes=DETECTION,
            rng_direct_sources=("python",), target_coupled=True,
        ),
    ),
    V2Unit(
        "ultralytics_augment", "class", "Albumentations",
        fx(
            construction_external_writes=("environment",), construction_state_writes=True,
            construction_rng_sources=("torch",),
            execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_direct_sources=("python",), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "ultralytics_augment", "function", "v8_transforms",
        fx(
            construction_external_reads=("dataset",), execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_delegated=True, target_signature="parametric", target_coupled=True,
            input_cardinality="many", sample_identity="combine",
        ),
    ),
    V2Unit(
        "detectron2_mapper", "class", "DatasetMapper",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            execution_external_reads=("filesystem",), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "albumentations_compose", "class", "Compose",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_direct_sources=("python", "torch"), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "albumentations_compose", "class", "OneOf",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_direct_sources=("numpy", "python"), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "albumentations_compose", "class", "SomeOf",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_direct_sources=("numpy", "python"), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "albumentations_compose", "class", "ReplayCompose",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_direct_sources=("python", "torch"), rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
    V2Unit(
        "kornia_augment", "class", "AugmentationSequential",
        fx(
            construction_state_writes=True, execution_reads=PARAMETRIC, execution_writes=PARAMETRIC,
            rng_delegated=True,
            target_signature="parametric", target_coupled=True,
        ),
    ),
)


MIX_NAMES = frozenset(("Mosaic", "MixUp", "CutMix", "CopyPaste"))
CONSTRUCTION_METHODS = frozenset(("__init__", "from_config", "__setstate__"))
ADMIN_PREFIXES = ("__repr__", "to_dict", "_get_init", "get_dict", "is_serializable")
DELEGATE_ATTRS = frozenset(("transforms", "augmentations", "pre_transform", "ops", "transform"))
DELEGATE_NAMES = frozenset(("t", "transform"))
RANDOM_CONSTRUCTOR = re.compile(
    r"^(?:Random[A-Z].*|AutoAugment|RandAugment|AugMix|Mosaic|MixUp|CutMix|CopyPaste|OneOf|SomeOf|.*_augment_transform)$"
)


def top_definitions(tree: ast.Module) -> tuple[dict[str, ast.ClassDef], dict[str, ast.FunctionDef]]:
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    return classes, functions


def method_map(cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}


def base_names(cls: ast.ClassDef) -> list[str]:
    names = []
    for base in cls.bases:
        name = corpus_v1.simple_name(base)
        if name:
            names.append(name)
    return names


def class_chain(cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[ast.ClassDef]:
    result: list[ast.ClassDef] = []
    seen: set[str] = set()

    def visit(current: ast.ClassDef) -> None:
        if current.name in seen:
            return
        seen.add(current.name)
        result.append(current)
        for name in base_names(current):
            if name in classes:
                visit(classes[name])

    visit(cls)
    return result


def phase_nodes(
    unit: V2Unit, root: ast.AST, classes: dict[str, ast.ClassDef]
) -> tuple[list[ast.AST], list[ast.AST]]:
    if isinstance(root, ast.FunctionDef):
        return [root], []
    chain = class_chain(root, classes)
    construction: list[ast.AST] = []
    methods_by_name: dict[str, ast.FunctionDef] = {}
    parent_methods: dict[str, list[ast.FunctionDef]] = {}
    for cls in chain:
        for name, method in method_map(cls).items():
            if name in CONSTRUCTION_METHODS:
                construction.append(method)
            elif not name.startswith(ADMIN_PREFIXES):
                parent_methods.setdefault(name, []).append(method)
                methods_by_name.setdefault(name, method)
    entry_names = [name for name in ("__call__", "forward") if name in methods_by_name]
    if not entry_names:
        entry_names = [
            name for name in methods_by_name if name == "get_params" or name.startswith("apply_")
        ]
    execution: list[ast.AST] = []
    seen_methods: set[int] = set()

    def visit_method(method: ast.FunctionDef) -> None:
        if id(method) in seen_methods:
            return
        seen_methods.add(id(method))
        execution.append(method)
        for child in ast.walk(method):
            if not isinstance(child, ast.Call):
                continue
            name = corpus_v1.simple_name(child.func)
            if name in methods_by_name:
                visit_method(methods_by_name[name])
            rendered = ast.unparse(child.func)
            if rendered.startswith("super().") and name in parent_methods:
                for parent_method in parent_methods[name][1:]:
                    visit_method(parent_method)

    for name in entry_names:
        visit_method(methods_by_name[name])
    return construction, execution


def code(nodes: list[ast.AST]) -> str:
    return "\n".join(ast.unparse(node) for node in nodes)


def call_info(nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    chains: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if name := corpus_v1.simple_name(child.func):
                    names.add(name)
                rendered = corpus_v1.attribute_chain(child.func)
                if rendered:
                    chains.add(rendered)
    return names, chains


def self_state_write(nodes: list[ast.AST]) -> bool:
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    for item in ast.walk(target):
                        if isinstance(item, ast.Attribute) and corpus_v1.attribute_chain(item).startswith("self."):
                            return True
    return False


def external_effects(nodes: list[ast.AST]) -> tuple[frozenset[str], frozenset[str]]:
    reads: set[str] = set()
    writes: set[str] = set()
    names, _ = call_info(nodes)
    if "read_image" in names or "open" in names:
        reads.add("filesystem")
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
                chain = corpus_v1.attribute_chain(child)
                if chain.startswith("self.dataset") or chain.startswith("dataset."):
                    reads.add("dataset")
            if isinstance(child, ast.Subscript):
                chain = corpus_v1.attribute_chain(child.value)
                if chain == "os.environ":
                    if isinstance(child.ctx, ast.Store):
                        writes.add("environment")
                    else:
                        reads.add("environment")
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                chain = corpus_v1.attribute_chain(child.func)
                if chain in {"os.getenv", "os.environ.get"}:
                    reads.add("environment")
    return frozenset(reads), frozenset(writes)


def rng_sources(nodes: list[ast.AST]) -> frozenset[str]:
    result: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            chain = corpus_v1.attribute_chain(child.func)
            if chain.startswith("random.") and chain != "random.Random":
                result.add("python")
            if chain.startswith("self.py_random."):
                result.add("python")
            if chain.startswith("np.random.") and chain != "np.random.default_rng":
                result.add("numpy")
            if chain.startswith("self.random_generator."):
                result.add("numpy")
            if re.match(r"torch\.(?:rand|randn|randint|initial_seed|manual_seed)", chain):
                result.add("torch")
    return frozenset(result)


def is_noop_method(method: ast.FunctionDef) -> bool:
    body = list(method.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Name)


def fixed_targets(cls: ast.ClassDef, execution: list[ast.AST]) -> frozenset[str]:
    mapping = {
        "apply_image": "image",
        "apply_instances": "instances",
        "apply_semantic": "semantic",
        "apply_keypoints": "keypoints",
        "apply_depth": "depth",
    }
    targets: set[str] = set()
    for name, method in method_map(cls).items():
        if name in mapping and not is_noop_method(method):
            targets.add(mapping[name])
        if name in {"apply_instances", "_transform_annotations"} and not is_noop_method(method):
            targets.add("labels")
    tokens = corpus_v1.identifier_tokens(execution)
    if any("keypoint" in token or token.startswith("kpt") for token in tokens):
        targets.add("keypoints")
    return frozenset(targets or {"image"})


def parametric_signature(
    unit: V2Unit, root: ast.AST, classes: dict[str, ast.ClassDef]
) -> bool:
    nodes = class_chain(root, classes) if isinstance(root, ast.ClassDef) else [root]
    tokens = corpus_v1.identifier_tokens(nodes)
    structural = {
        "additional_targets", "data_keys", "use_keypoint", "use_instance_mask",
        "augmentations", "keypoint_hflip_indices",
    }
    if tokens & structural:
        return True
    if isinstance(root, ast.ClassDef):
        init = method_map(root).get("__init__")
        if init and any(arg.arg in {"transforms", "transform", "data_keys"} for arg in init.args.args + init.args.kwonlyargs):
            return True
    return False


def delegated_effect(
    unit: V2Unit,
    construction: list[ast.AST],
    execution: list[ast.AST],
    definitions: dict[str, ast.AST],
) -> bool:
    construction_names, _ = call_info(construction)
    execution_names, execution_chains = call_info(execution)
    if any(RANDOM_CONSTRUCTOR.match(name) for name in construction_names):
        return True
    root = definitions[unit.name]
    if isinstance(root, ast.ClassDef) and parametric_signature(unit, root, {k: v for k, v in definitions.items() if isinstance(v, ast.ClassDef)}):
        return True
    if isinstance(root, ast.ClassDef) and any(name == "BaseMixTransform" for name in base_names(root)):
        return True
    if any(name in MIX_NAMES for name in construction_names):
        return True
    if unit.kind == "function" and any(name in definitions for name in construction_names):
        return True
    return False


def infer(unit: V2Unit, source: str) -> tuple[EffectV2, dict[str, object]]:
    tree = ast.parse(source)
    classes, functions = top_definitions(tree)
    definitions: dict[str, ast.AST] = {**classes, **functions}
    root = definitions[unit.name]
    construction, execution = phase_nodes(unit, root, classes)
    construction_reads, construction_writes = external_effects(construction)
    execution_external_reads, execution_external_writes = external_effects(execution)
    signature: TargetSignature = "parametric" if parametric_signature(unit, root, classes) else "fixed"

    if isinstance(root, ast.FunctionDef):
        if signature == "parametric":
            reads = writes = frozenset(("parametric",))
        else:
            reads = writes = frozenset(("image",))
    elif signature == "parametric":
        reads = writes = frozenset(("parametric",))
    else:
        reads = writes = fixed_targets(root, execution)

    construction_names, _ = call_info(construction)
    many = unit.name in MIX_NAMES or bool(construction_names & MIX_NAMES)
    coupled = signature == "parametric" or len(writes) >= 2 or many
    prediction = EffectV2(
        construction_reads,
        construction_writes,
        self_state_write(construction),
        rng_sources(construction),
        reads,
        writes,
        execution_external_reads,
        execution_external_writes,
        rng_sources(execution),
        delegated_effect(unit, construction, execution, definitions),
        signature,
        coupled,
        "many" if many else "one",
        "one",
        "combine" if many else "preserve",
    )
    evidence = {
        "construction_nodes": len(construction),
        "execution_nodes": len(execution),
        "construction_calls": "+".join(sorted(construction_names)) or "none",
    }
    return prediction, evidence


def text_value(value: object) -> str:
    if isinstance(value, frozenset):
        return "+".join(sorted(value)) if value else "none"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    sources = {}
    for spec in corpus_v1.SOURCES:
        source, _, _ = corpus_v1.fetch_source(spec, args.refresh)
        sources[spec.source_id] = source

    rows: list[dict[str, object]] = []
    field_names = [field.name for field in fields(EffectV2)]
    for unit in UNITS:
        predicted, evidence = infer(unit, sources[unit.source_id])
        row: dict[str, object] = {
            "source_id": unit.source_id,
            "unit": unit.name,
            "kind": unit.kind,
        }
        for name in field_names:
            truth = getattr(unit.truth, name)
            value = getattr(predicted, name)
            row[f"truth_{name}"] = text_value(truth)
            row[f"predicted_{name}"] = text_value(value)
            row[f"match_{name}"] = truth == value
        row.update(evidence)
        rows.append(row)

    correct = sum(row[f"match_{name}"] is True for row in rows for name in field_names)
    total = len(rows) * len(field_names)
    mismatches = [
        {
            "unit": f"{row['source_id']}::{row['unit']}",
            "fields": [name for name in field_names if row[f"match_{name}"] is not True],
        }
        for row in rows
        if any(row[f"match_{name}"] is not True for name in field_names)
    ]
    calibration_accuracy = correct / total
    critical_fields = ("target_coupled", "input_cardinality", "sample_identity")
    critical_false_negatives = sum(
        row[f"truth_{name}"] != row[f"predicted_{name}"]
        for row in rows
        for name in critical_fields
        if row[f"truth_{name}"] not in ("False", "one", "preserve")
    )
    freeze_ready = calibration_accuracy >= 0.95 and critical_false_negatives == 0
    analyzer_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary = {
        "units": len(rows),
        "effect_fields": len(field_names),
        "effect_cells": total,
        "effect_cells_correct": correct,
        "calibration_accuracy": calibration_accuracy,
        "critical_false_negatives": critical_false_negatives,
        "freeze_ready": freeze_ready,
        "analyzer_sha256": analyzer_hash,
    }
    write_csv(OUT / "autocontract_h6_v2_effects.csv", rows)
    write_csv(OUT / "autocontract_h6_v2_summary.csv", [summary])
    (OUT / "autocontract_h6_v2_mismatches.json").write_text(
        json.dumps(mismatches, indent=2), encoding="utf-8"
    )
    report = "\n".join(
        [
            "# AutoContract EffectV2 calibration",
            "",
            f"Units: {len(rows)}; fields: {len(field_names)}; cells: {total}.",
            f"Calibration accuracy: {calibration_accuracy:.1%}.",
            f"Critical false negatives: {critical_false_negatives}.",
            f"Freeze ready (>=95% and zero critical FN): **{'YES' if freeze_ready else 'NO'}**.",
            "",
            "## Mismatches",
            "",
            *(
                [f"- `{item['unit']}`: {', '.join(item['fields'])}" for item in mismatches]
                or ["- None."]
            ),
            "",
            "The sealed MONAI/MMDetection/DALI sources were not accessed by this calibration.",
            "",
        ]
    )
    (OUT / "autocontract_h6_v2_calibration.md").write_text(report, encoding="utf-8")
    if args.freeze:
        if not freeze_ready:
            raise RuntimeError("EffectV2 is not freeze-ready")
        sealed_path = OUT / "autocontract_h6_blind_holdout.csv"
        with sealed_path.open(encoding="utf-8") as handle:
            sealed = list(csv.DictReader(handle))
        oracle_payload = [
            {
                "source_id": unit.source_id,
                "kind": unit.kind,
                "name": unit.name,
                "truth": {
                    name: text_value(getattr(unit.truth, name)) for name in field_names
                },
            }
            for unit in UNITS
        ]
        freeze = {
            "protocol": "AutoContract H6 EffectV2 calibration freeze",
            "date": "2026-07-28",
            "effect_fields": field_names,
            "calibration_units": len(UNITS),
            "calibration_accuracy": calibration_accuracy,
            "critical_false_negatives": critical_false_negatives,
            "blind_thresholds": {
                "effect_cell_accuracy": 0.95,
                "critical_false_negatives": 0,
                "known_unsafe_false_accepts": 0,
            },
            "analyzer_sha256": analyzer_hash,
            "calibration_oracle_sha256": hashlib.sha256(
                json.dumps(oracle_payload, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "sealed_repositories": [
                {"repo": row["repo"], "commit_sha": row["commit_sha"]}
                for row in sealed
            ],
            "sealed_sources_opened": False,
        }
        (OUT / "autocontract_h6_v2_freeze.json").write_text(
            json.dumps(freeze, indent=2), encoding="utf-8"
        )
    print(report)


if __name__ == "__main__":
    main()
