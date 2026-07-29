"""One-shot blind evaluation of the frozen AutoContract EffectV2 analyzer."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys
import urllib.request
from dataclasses import fields
from pathlib import Path

import autocontract_h6_effect_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
SOURCE_DIR = ROOT / ".research" / "semantics_safe_reconfiguration" / "h6_corpus" / "blind_sources"
ORACLE = OUT / "autocontract_h6_blind_oracle.json"
ORACLE_HASH = "f0f4799978de14c03b53fddc1fed971f012c7f735fccfe2e62c7a2f808beb1dc"

SOURCES = {
    "monai_compose": (
        "Project-MONAI/MONAI",
        "3ee058bdd16dd4a566d23d3f84687c3c35268a36",
        "monai/transforms/compose.py",
    ),
    "mmdet_transforms": (
        "open-mmlab/mmdetection",
        "cfd5d3a985b0249de009b67d04f37263e11cdf3d",
        "mmdet/datasets/transforms/transforms.py",
    ),
    "dali_pipeline": (
        "NVIDIA/DALI",
        "1a8328edbc8db6786d764e309d519a3926171d19",
        "dali/python/nvidia/dali/pipeline.py",
    ),
}


def parse_value(name: str, value: str) -> object:
    field = next(field for field in fields(v2.EffectV2) if field.name == name)
    if name in {
        "construction_state_writes",
        "rng_delegated",
        "target_coupled",
    }:
        return value == "True"
    if name in {
        "target_signature",
        "input_cardinality",
        "output_cardinality",
        "sample_identity",
    }:
        return value
    return frozenset() if value == "none" else frozenset(value.split("+"))


def load_oracle() -> list[tuple[v2.V2Unit, bool]]:
    digest = hashlib.sha256(ORACLE.read_bytes()).hexdigest()
    if digest != ORACLE_HASH:
        raise RuntimeError(f"blind oracle hash changed: {digest}")
    payload = json.loads(ORACLE.read_text(encoding="utf-8"))
    result = []
    names = [field.name for field in fields(v2.EffectV2)]
    for item in payload["units"]:
        truth = v2.EffectV2(*(parse_value(name, item["truth"][name]) for name in names))
        result.append(
            (
                v2.V2Unit(item["source_id"], item["kind"], item["name"], truth),
                bool(item["unsafe_for_unary_optimizer"]),
            )
        )
    return result


def verify_frozen_analyzer() -> dict[str, object]:
    freeze = json.loads((OUT / "autocontract_h6_v2_freeze.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(Path(v2.__file__).read_bytes()).hexdigest()
    if digest != freeze["analyzer_sha256"]:
        raise RuntimeError(f"frozen analyzer changed: {digest}")
    return freeze


def fetch_sources() -> tuple[dict[str, str], list[dict[str, object]]]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    texts = {}
    rows = []
    for source_id, (repo, sha, path) in SOURCES.items():
        url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
        local = SOURCE_DIR / f"{source_id}__{Path(path).name}"
        if not local.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "AutoContract-H6-blind"})
            with urllib.request.urlopen(request, timeout=60) as response:
                local.write_bytes(response.read())
        data = local.read_bytes()
        source = data.decode("utf-8")
        ast.parse(source)
        texts[source_id] = source
        rows.append(
            {
                "source_id": source_id,
                "repo": repo,
                "commit_sha": sha,
                "path": path,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return texts, rows


def conservative_reject(effect: v2.EffectV2) -> bool:
    return (
        effect.target_signature == "parametric"
        or effect.input_cardinality == "many"
        or effect.output_cardinality == "many"
        or effect.sample_identity == "combine"
        or bool(effect.execution_external_reads)
        or bool(effect.execution_external_writes)
        or effect.rng_delegated
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    freeze = verify_frozen_analyzer()
    units = load_oracle()
    sources, source_rows = fetch_sources()
    names = [field.name for field in fields(v2.EffectV2)]
    rows = []
    for unit, unsafe in units:
        predicted, evidence = v2.infer(unit, sources[unit.source_id])
        row: dict[str, object] = {
            "source_id": unit.source_id,
            "unit": unit.name,
            "kind": unit.kind,
            "unsafe_for_unary_optimizer": unsafe,
            "validator_reject": conservative_reject(predicted),
        }
        for name in names:
            truth = getattr(unit.truth, name)
            prediction = getattr(predicted, name)
            row[f"truth_{name}"] = v2.text_value(truth)
            row[f"predicted_{name}"] = v2.text_value(prediction)
            row[f"match_{name}"] = truth == prediction
        row.update(evidence)
        rows.append(row)

    total = len(rows) * len(names)
    correct = sum(row[f"match_{name}"] is True for row in rows for name in names)
    critical_fields = ("target_coupled", "input_cardinality", "output_cardinality", "sample_identity")
    critical_false_negatives = sum(
        row[f"truth_{name}"] != row[f"predicted_{name}"]
        for row in rows
        for name in critical_fields
        if row[f"truth_{name}"] not in ("False", "one", "preserve")
    )
    false_accepts = [
        f"{row['source_id']}::{row['unit']}"
        for row in rows
        if row["unsafe_for_unary_optimizer"] is True and row["validator_reject"] is not True
    ]
    accuracy = correct / total
    passed = accuracy >= 0.95 and critical_false_negatives == 0 and not false_accepts
    mismatches = [
        (
            f"{row['source_id']}::{row['unit']}",
            [name for name in names if row[f"match_{name}"] is not True],
        )
        for row in rows
        if any(row[f"match_{name}"] is not True for name in names)
    ]
    summary = {
        "units": len(rows),
        "effect_fields": len(names),
        "effect_cells": total,
        "effect_cells_correct": correct,
        "effect_cell_accuracy": accuracy,
        "critical_false_negatives": critical_false_negatives,
        "known_unsafe_false_accepts": len(false_accepts),
        "blind_gate_pass": passed,
        "frozen_analyzer_sha256": freeze["analyzer_sha256"],
        "blind_oracle_sha256": ORACLE_HASH,
    }
    write_csv(OUT / "autocontract_h6_blind_sources.csv", source_rows)
    write_csv(OUT / "autocontract_h6_blind_effects.csv", rows)
    write_csv(OUT / "autocontract_h6_blind_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract EffectV2 one-shot blind evaluation",
            "",
            f"Repositories: {len(source_rows)}; units: {len(rows)}; effect cells: {total}.",
            f"Effect-cell accuracy: {accuracy:.1%}.",
            f"Critical false negatives: {critical_false_negatives}.",
            f"Known-unsafe false accepts: {len(false_accepts)}.",
            f"Blind H6 effect gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "## Mismatches",
            "",
            *([f"- `{unit}`: {', '.join(bad)}" for unit, bad in mismatches] or ["- None."]),
            "",
            "## False accepts",
            "",
            *([f"- `{unit}`" for unit in false_accepts] or ["- None."]),
            "",
            "The frozen analyzer and pre-run oracle hashes were verified before evaluation.",
            "",
        ]
    )
    (OUT / "autocontract_h6_blind_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
