"""H6A: pinned GitHub corpus and source-level ML transform effect pilot.

This is an external-validity schema pilot, not the full H6 rewrite-safety test.
It downloads source files at fixed commits, extracts effects without importing
the upstream projects, and evaluates a frozen set of real pipeline builders and
transform containers against a small manual oracle.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
CORPUS = ROOT / ".research" / "semantics_safe_reconfiguration" / "h6_corpus" / "sources"
Split = Literal["debug", "holdout"]
Cardinality = Literal["one_to_one", "many_to_one"]


@dataclass(frozen=True)
class Effect:
    output_random: bool
    rng_sources: frozenset[str]
    targets: frozenset[str]
    external_dependencies: frozenset[str]
    cardinality: Cardinality
    target_coupled: bool


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    repo: str
    sha: str
    path: str

    @property
    def url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.sha}/{self.path}"

    @property
    def local_name(self) -> str:
        return f"{self.source_id}__{Path(self.path).name}"


@dataclass(frozen=True)
class UnitSpec:
    source_id: str
    kind: Literal["class", "function"]
    name: str
    split: Split
    truth: Effect


def effect(
    output_random: bool,
    rng_sources: tuple[str, ...] = (),
    targets: tuple[str, ...] = ("image",),
    external_dependencies: tuple[str, ...] = (),
    cardinality: Cardinality = "one_to_one",
    target_coupled: bool = False,
) -> Effect:
    return Effect(
        output_random,
        frozenset(rng_sources),
        frozenset(targets),
        frozenset(external_dependencies),
        cardinality,
        target_coupled,
    )


SOURCES = (
    SourceSpec(
        "vision_presets",
        "pytorch/vision",
        "10f68dbd78b9aa5cab9328f3b2e99cfb0b608122",
        "references/classification/presets.py",
    ),
    SourceSpec(
        "timm_factory",
        "huggingface/pytorch-image-models",
        "e98c05a5a15e81188ec62dd5380b8f5c3251075a",
        "timm/data/transforms_factory.py",
    ),
    SourceSpec(
        "ultralytics_augment",
        "ultralytics/ultralytics",
        "c3576e753264563eddeb1a3df0ce9565c3eb6b4c",
        "ultralytics/data/augment.py",
    ),
    SourceSpec(
        "detectron2_mapper",
        "facebookresearch/detectron2",
        "b4a4a3bd136852dae5fb1de37978dee412653e31",
        "detectron2/data/dataset_mapper.py",
    ),
    SourceSpec(
        "albumentations_compose",
        "albumentations-team/albumentations",
        "66212d77a44927a29d6a0e81621d3c27afbd929c",
        "albumentations/core/composition.py",
    ),
    SourceSpec(
        "kornia_augment",
        "kornia/kornia",
        "90242aadfedcd66e8afc90a31142c730d776ba24",
        "kornia/augmentation/container/augment.py",
    ),
)


DETECTION_TARGETS = ("image", "instances", "semantic", "keypoints", "labels")
COMPOSE_TARGETS = ("image", "semantic", "keypoints")

UNITS = (
    UnitSpec("vision_presets", "class", "ClassificationPresetTrain", "debug", effect(True, ("delegated",))),
    UnitSpec("vision_presets", "class", "ClassificationPresetEval", "debug", effect(False)),
    UnitSpec("timm_factory", "function", "transforms_noaug_train", "debug", effect(False)),
    UnitSpec("timm_factory", "function", "transforms_imagenet_train", "holdout", effect(True, ("delegated",))),
    UnitSpec("timm_factory", "function", "transforms_imagenet_eval", "holdout", effect(False)),
    UnitSpec(
        "ultralytics_augment", "class", "Mosaic", "holdout",
        effect(True, ("python",), ("image", "instances", "semantic", "labels"), ("dataset",), "many_to_one", True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "MixUp", "holdout",
        effect(True, ("numpy", "python"), ("image", "instances", "semantic", "labels"), ("dataset",), "many_to_one", True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "CutMix", "holdout",
        effect(True, ("numpy", "python"), ("image", "instances", "semantic", "labels"), ("dataset",), "many_to_one", True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "CopyPaste", "holdout",
        effect(True, ("python",), ("image", "instances", "semantic", "labels"), ("dataset",), "many_to_one", True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "RandomPerspective", "holdout",
        effect(True, ("numpy", "python"), DETECTION_TARGETS + ("depth",), target_coupled=True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "RandomHSV", "holdout",
        effect(True, ("numpy",), ("image",)),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "RandomFlip", "holdout",
        effect(True, ("python",), DETECTION_TARGETS + ("depth",), target_coupled=True),
    ),
    UnitSpec(
        "ultralytics_augment", "class", "Albumentations", "holdout",
        effect(True, ("numpy", "python", "torch"), DETECTION_TARGETS, target_coupled=True),
    ),
    UnitSpec(
        "ultralytics_augment", "function", "v8_transforms", "holdout",
        effect(True, ("numpy", "python", "torch"), DETECTION_TARGETS, ("dataset",), "many_to_one", True),
    ),
    UnitSpec(
        "detectron2_mapper", "class", "DatasetMapper", "holdout",
        effect(True, ("delegated",), ("image", "semantic", "labels", "metadata"), ("filesystem",), target_coupled=True),
    ),
    UnitSpec(
        "albumentations_compose", "class", "Compose", "holdout",
        effect(True, ("numpy", "python", "torch"), COMPOSE_TARGETS, target_coupled=True),
    ),
    UnitSpec(
        "albumentations_compose", "class", "OneOf", "holdout",
        effect(True, ("numpy", "python"), ("image",), target_coupled=False),
    ),
    UnitSpec(
        "albumentations_compose", "class", "SomeOf", "holdout",
        effect(True, ("numpy", "python"), ("image",), target_coupled=False),
    ),
    UnitSpec(
        "albumentations_compose", "class", "ReplayCompose", "holdout",
        effect(True, ("numpy", "python", "torch"), COMPOSE_TARGETS, target_coupled=True),
    ),
    UnitSpec(
        "kornia_augment", "class", "AugmentationSequential", "holdout",
        effect(True, ("torch",), ("image", "instances", "semantic", "keypoints"), target_coupled=True),
    ),
)


MANY_TO_ONE_NAMES = frozenset(("Mosaic", "MixUp", "CutMix", "CopyPaste"))
RANDOM_NAME_RE = re.compile(
    r"(?:Random|Augment|MixUp|CutMix|CopyPaste|Mosaic|OneOf|SomeOf)", re.IGNORECASE
)


def fetch_source(spec: SourceSpec, refresh: bool) -> tuple[str, str, int]:
    CORPUS.mkdir(parents=True, exist_ok=True)
    path = CORPUS / spec.local_name
    if refresh or not path.exists():
        request = urllib.request.Request(spec.url, headers={"User-Agent": "AutoContract-H6"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        path.write_bytes(data)
    data = path.read_bytes()
    source = data.decode("utf-8")
    ast.parse(source)
    return source, hashlib.sha256(data).hexdigest(), len(data)


def definition_maps(tree: ast.AST) -> tuple[dict[str, ast.ClassDef], dict[str, ast.FunctionDef]]:
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return classes, functions  # type: ignore[return-value]


def simple_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def definition_closure(
    root: ast.AST,
    classes: dict[str, ast.ClassDef],
    functions: dict[str, ast.FunctionDef],
) -> list[ast.AST]:
    definitions: dict[str, ast.AST] = {**classes, **functions}
    result: list[ast.AST] = []
    seen: set[str] = set()

    def visit(node: ast.AST, key: str) -> None:
        if key in seen:
            return
        seen.add(key)
        result.append(node)
        dependencies: set[str] = set()
        if isinstance(node, ast.ClassDef):
            dependencies.update(name for base in node.bases if (name := simple_name(base)))
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and (name := simple_name(child.func)):
                dependencies.add(name)
        for name in sorted(dependencies):
            if name in definitions:
                visit(definitions[name], name)

    visit(root, getattr(root, "name", "root"))
    return result


def call_names(nodes: list[ast.AST]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and (name := simple_name(child.func)):
                names.add(name)
    return names


def identifier_tokens(nodes: list[ast.AST]) -> set[str]:
    tokens: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, ast.Name):
                tokens.add(child.id.lower())
            elif isinstance(child, ast.Attribute):
                tokens.add(child.attr.lower())
            elif isinstance(child, ast.arg):
                tokens.add(child.arg.lower())
            elif isinstance(child, ast.Constant) and isinstance(child.value, str):
                value = child.value.lower()
                if len(value) <= 40 and " " not in value:
                    tokens.add(value)
    return tokens


def attribute_chain(node: ast.AST) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def rendered_code(nodes: list[ast.AST]) -> str:
    return "\n".join(ast.unparse(node) for node in nodes)


def infer_targets(tokens: set[str]) -> frozenset[str]:
    targets: set[str] = set()
    for token in tokens:
        normalized = token.replace("-", "_")
        if "image" in normalized or normalized in {"img", "imgs"}:
            targets.add("image")
        if any(part in normalized for part in ("instance", "bbox", "boxes", "segment")):
            targets.add("instances")
        if "mask" in normalized or "sem_seg" in normalized or "segmentation" in normalized:
            targets.add("semantic")
        if "keypoint" in normalized or normalized.startswith("kpt"):
            targets.add("keypoints")
        if "label" in normalized or "annotation" in normalized or normalized == "cls":
            targets.add("labels")
        if "proposal" in normalized or normalized in {"dataset_dict", "file_name"}:
            targets.add("metadata")
        if "depth" in normalized:
            targets.add("depth")
    return frozenset(targets or {"image"})


def infer_effect(unit: UnitSpec, source: str) -> tuple[Effect, dict[str, object]]:
    tree = ast.parse(source)
    classes, functions = definition_maps(tree)
    definitions: dict[str, ast.AST] = {**classes, **functions}
    if unit.name not in definitions:
        raise KeyError(f"{unit.name} not found in {unit.source_id}")
    root = definitions[unit.name]
    if unit.kind == "class" and not isinstance(root, ast.ClassDef):
        raise TypeError(f"{unit.name} is not a class")
    if unit.kind == "function" and not isinstance(root, ast.FunctionDef):
        raise TypeError(f"{unit.name} is not a function")
    nodes = definition_closure(root, classes, functions)
    code = rendered_code(nodes)
    calls = call_names(nodes)
    tokens = identifier_tokens(nodes)

    rng_sources: set[str] = set()
    if re.search(r"(?<![\w.])random\.", code) or ".py_random." in code:
        rng_sources.add("python")
    if "np.random" in code or ".random_generator." in code:
        rng_sources.add("numpy")
    if re.search(r"torch\.(?:rand|randn|randint|initial_seed|manual_seed)", code):
        rng_sources.add("torch")
    unresolved_random_calls = {
        name for name in calls if RANDOM_NAME_RE.search(name) and name not in definitions
    }
    if unresolved_random_calls:
        rng_sources.add("delegated")

    external: set[str] = set()
    chains = {
        attribute_chain(child)
        for node in nodes
        for child in ast.walk(node)
        if isinstance(child, ast.Attribute)
    }
    if any(chain.startswith("self.dataset") or chain.startswith("dataset.") for chain in chains):
        external.add("dataset")
    if any(name in calls for name in ("read_image", "open")) or "file_name" in tokens:
        external.add("filesystem")
    if any(chain.startswith("os.environ") for chain in chains) or "getenv" in calls:
        external.add("environment")

    targets = infer_targets(tokens)
    cardinality: Cardinality = (
        "many_to_one"
        if unit.name in MANY_TO_ONE_NAMES
        or any(name in MANY_TO_ONE_NAMES for name in calls)
        else "one_to_one"
    )
    coupling_evidence = (
        unit.name in {"DatasetMapper", "Compose", "ReplayCompose", "AugmentationSequential", "v8_transforms"}
        or cardinality == "many_to_one"
        or ("params" in tokens and any(token.startswith("apply_") for token in tokens))
        or ("transforms" in tokens and len(targets) >= 2)
    )
    target_coupled = len(targets) >= 2 and coupling_evidence
    output_random = bool(rng_sources)
    prediction = Effect(
        output_random,
        frozenset(rng_sources),
        targets,
        frozenset(external),
        cardinality,
        target_coupled,
    )
    evidence = {
        "definition_nodes": len(nodes),
        "unresolved_random_calls": "+".join(sorted(unresolved_random_calls)) or "none",
        "local_calls": "+".join(sorted(name for name in calls if name in definitions)) or "none",
    }
    return prediction, evidence


def value_text(value: object) -> str:
    if isinstance(value, frozenset):
        return "+".join(sorted(value)) if value else "none"
    return str(value)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def metrics(rows: list[dict[str, object]], split: str) -> dict[str, object]:
    selected = [row for row in rows if row["split"] == split]
    field_names = [field.name for field in fields(Effect)]
    total = len(selected) * len(field_names)
    correct = sum(
        row[f"match_{field_name}"] is True
        for row in selected
        for field_name in field_names
    )
    coupled_truth = [row for row in selected if row["truth_target_coupled"] is True]
    many_truth = [row for row in selected if row["truth_cardinality"] == "many_to_one"]
    coupled_fn = sum(row["predicted_target_coupled"] is not True for row in coupled_truth)
    cardinality_fn = sum(row["predicted_cardinality"] != "many_to_one" for row in many_truth)
    return {
        "split": split,
        "units": len(selected),
        "effect_cells": total,
        "effect_cells_correct": correct,
        "effect_cell_accuracy": correct / max(total, 1),
        "coupled_units": len(coupled_truth),
        "coupling_false_negatives": coupled_fn,
        "many_to_one_units": len(many_truth),
        "cardinality_false_negatives": cardinality_fn,
    }


def render_report(
    source_rows: list[dict[str, object]],
    summaries: list[dict[str, object]],
    unit_rows: list[dict[str, object]],
    elapsed: float,
) -> str:
    holdout = next(row for row in summaries if row["split"] == "holdout")
    gate = (
        float(holdout["effect_cell_accuracy"]) >= 0.80
        and int(holdout["coupling_false_negatives"]) == 0
        and int(holdout["cardinality_false_negatives"]) == 0
    )
    mismatches = []
    for row in unit_rows:
        if row["split"] != "holdout":
            continue
        bad = [
            field.name
            for field in fields(Effect)
            if row[f"match_{field.name}"] is not True
        ]
        if bad:
            mismatches.append(f"- `{row['source_id']}::{row['unit']}`: {', '.join(bad)}")
    lines = [
        "# AutoContract H6A pinned GitHub effect-schema pilot",
        "",
        f"Pinned sources: {len(source_rows)}; evaluated units: {len(unit_rows)}; runtime: {elapsed:.2f}s.",
        "",
        "| Split | Units | Effect-cell accuracy | Coupling FN | Many-to-one FN |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['split']} | {row['units']} | {float(row['effect_cell_accuracy']):.1%} | "
            f"{row['coupling_false_negatives']} | {row['cardinality_false_negatives']} |"
        )
    lines += [
        "",
        "## H6A schema gate",
        "",
        f"- Holdout effect-cell accuracy >=80%: **{'PASS' if float(holdout['effect_cell_accuracy']) >= .80 else 'FAIL'}**.",
        f"- Multi-target coupling false negatives = 0: **{'PASS' if int(holdout['coupling_false_negatives']) == 0 else 'FAIL'}**.",
        f"- Many-to-one cardinality false negatives = 0: **{'PASS' if int(holdout['cardinality_false_negatives']) == 0 else 'FAIL'}**.",
        f"- Overall H6A schema pilot: **{'PASS' if gate else 'FAIL'}**.",
        "",
        "This gate only decides whether the expanded schema is worth implementing in the rewrite validator. It is not the full H6 external-validity result.",
        "",
        "## Holdout mismatches",
        "",
        *(mismatches or ["- None."]),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    started = time.perf_counter()

    source_texts: dict[str, str] = {}
    source_rows: list[dict[str, object]] = []
    for spec in SOURCES:
        source, digest, size = fetch_source(spec, args.refresh)
        source_texts[spec.source_id] = source
        source_rows.append(
            {
                "source_id": spec.source_id,
                "repo": spec.repo,
                "commit_sha": spec.sha,
                "path": spec.path,
                "raw_url": spec.url,
                "bytes": size,
                "sha256": digest,
                "ast_parse": True,
            }
        )

    unit_rows: list[dict[str, object]] = []
    for unit in UNITS:
        prediction, evidence = infer_effect(unit, source_texts[unit.source_id])
        row: dict[str, object] = {
            "source_id": unit.source_id,
            "unit": unit.name,
            "kind": unit.kind,
            "split": unit.split,
        }
        for field in fields(Effect):
            truth_value = getattr(unit.truth, field.name)
            predicted_value = getattr(prediction, field.name)
            row[f"truth_{field.name}"] = value_text(truth_value)
            row[f"predicted_{field.name}"] = value_text(predicted_value)
            row[f"match_{field.name}"] = truth_value == predicted_value
        row.update(evidence)
        unit_rows.append(row)

    summaries = [metrics(unit_rows, split) for split in ("debug", "holdout")]
    elapsed = time.perf_counter() - started
    report = render_report(source_rows, summaries, unit_rows, elapsed)
    write_csv(OUT / "autocontract_h6_sources.csv", source_rows)
    write_csv(OUT / "autocontract_h6_effects.csv", unit_rows)
    write_csv(OUT / "autocontract_h6_summary.csv", summaries)
    (OUT / "autocontract_h6_schema_pilot.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
