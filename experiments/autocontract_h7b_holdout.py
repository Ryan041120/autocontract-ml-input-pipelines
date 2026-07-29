"""One-shot H7B release-version holdout for frozen AutoContract adapters.

The evaluator verifies all pre-source hashes before downloading the sealed
files. It never mutates the H7 analyzer or adapter manifest.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import sys
import urllib.request
from dataclasses import dataclass, fields
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
SOURCE_DIR = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7b_corpus" / "sealed_sources"
FREEZE_PATH = OUT / "autocontract_h7b_freeze.json"
ORACLE_PATH = OUT / "autocontract_h7b_oracle.json"


@dataclass(frozen=True)
class OracleUnit:
    source_id: str
    kind: str
    name: str
    unsafe: bool
    expected_decision: str
    expected_reason_category: str


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    checks = {
        "analyzer_sha256": sha256(Path(h7.__file__)),
        "adapter_manifest_sha256": sha256(OUT / "autocontract_h7_adapter_manifest.json"),
        "oracle_sha256": sha256(ORACLE_PATH),
    }
    for name, actual in checks.items():
        if actual != freeze[name]:
            raise RuntimeError(f"H7B freeze violation for {name}: {actual}")
    return freeze


def load_oracle() -> list[OracleUnit]:
    payload = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    if payload.get("created_before_source_fetch") is not True:
        raise RuntimeError("oracle was not marked pre-source")
    return [
        OracleUnit(
            item["source_id"], item["kind"], item["name"],
            bool(item["unsafe_for_unary_optimizer"]),
            item["expected_decision"], item["expected_reason_category"],
        )
        for item in payload["units"]
    ]


def fetch_sources(freeze: dict[str, object]) -> tuple[dict[str, str], list[dict[str, object]]]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    texts: dict[str, str] = {}
    rows: list[dict[str, object]] = []
    for spec in freeze["sealed_sources"]:
        url = f"https://raw.githubusercontent.com/{spec['repo']}/{spec['commit_sha']}/{spec['path']}"
        local = SOURCE_DIR / f"{spec['source_id']}__{Path(spec['path']).name}"
        if not local.exists():
            request = urllib.request.Request(url, headers={"User-Agent": "AutoContract-H7B-holdout"})
            with urllib.request.urlopen(request, timeout=60) as response:
                local.write_bytes(response.read())
        data = local.read_bytes()
        source = data.decode("utf-8")
        ast.parse(source)
        texts[spec["source_id"]] = source
        rows.append(
            {
                "source_id": spec["source_id"],
                "repo": spec["repo"],
                "release": spec["release"],
                "commit_sha": spec["commit_sha"],
                "path": spec["path"],
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return texts, rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def text(value: object) -> str:
    if isinstance(value, frozenset):
        return "+".join(sorted(value)) or "none"
    if isinstance(value, tuple):
        return ";".join(value) or "none"
    if value is None:
        return "unknown"
    return str(value)


def evaluate(unit: OracleUnit, source: str) -> h7.AnalysisResult:
    tree = ast.parse(source)
    classes, functions = v2.top_definitions(tree)
    definitions = {**classes, **functions}
    if unit.name not in definitions:
        adapter = h7.adapter_for(unit.source_id)
        return h7.AnalysisResult(
            "unknown", None, ("sealed_source_unit_missing:" + unit.name,),
            adapter.name if adapter else "generic", (),
        )
    probe = v2.V2Unit(unit.source_id, unit.kind, unit.name, v2.fx())
    return h7.analyze(probe, source)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    freeze = verify_freeze()
    oracle = load_oracle()
    sources, source_rows = fetch_sources(freeze)
    rows: list[dict[str, object]] = []
    for unit in oracle:
        result = evaluate(unit, sources[unit.source_id])
        rejection_reasons = h7.validator_reasons(result)
        decision = "reject" if rejection_reasons else "admit"
        reason_match = (
            not rejection_reasons if unit.expected_reason_category == "none"
            else any(unit.expected_reason_category in reason for reason in rejection_reasons)
        )
        row: dict[str, object] = {
            "source_id": unit.source_id,
            "unit": unit.name,
            "unsafe_for_unary_optimizer": unit.unsafe,
            "expected_decision": unit.expected_decision,
            "actual_decision": decision,
            "decision_correct": decision == unit.expected_decision,
            "expected_reason_category": unit.expected_reason_category,
            "reason_category_match": reason_match,
            "analysis_status": result.status,
            "adapter": result.adapter,
            "analysis_reasons": text(result.reasons),
            "validator_reasons": text(rejection_reasons),
            "evidence": text(result.evidence),
        }
        for field in fields(h7.EffectV3):
            row[f"effect_{field.name}"] = text(
                getattr(result.effect, field.name) if result.effect else None
            )
        rows.append(row)

    supported = [row for row in rows if row["adapter"] != "generic"]
    safe_supported = [row for row in supported if row["unsafe_for_unary_optimizer"] is False]
    unsafe = [row for row in rows if row["unsafe_for_unary_optimizer"] is True]
    unsupported = [row for row in rows if row["adapter"] == "generic"]
    false_accepts = [row for row in unsafe if row["actual_decision"] == "admit"]
    safe_accepts = [row for row in safe_supported if row["actual_decision"] == "admit"]
    reasoned_unknowns = [
        row for row in unsupported
        if row["analysis_status"] == "unknown" and row["analysis_reasons"] != "none"
    ]
    reason_matches = sum(row["reason_category_match"] is True for row in rows)
    decision_matches = sum(row["decision_correct"] is True for row in rows)
    thresholds = freeze["thresholds"]
    safe_recall = len(safe_accepts) / len(safe_supported)
    unsupported_coverage = len(reasoned_unknowns) / len(unsupported)
    reason_accuracy = reason_matches / len(rows)
    passed = (
        len(false_accepts) <= thresholds["known_unsafe_false_accepts"]
        and safe_recall >= thresholds["supported_safe_recall"]
        and unsupported_coverage >= thresholds["unsupported_reason_coverage"]
        and reason_accuracy >= thresholds["reason_category_accuracy"]
    )
    summary = {
        "protocol": freeze["protocol"],
        "sources": len(source_rows),
        "units": len(rows),
        "decision_matches": decision_matches,
        "decision_accuracy": decision_matches / len(rows),
        "known_unsafe_false_accepts": len(false_accepts),
        "supported_safe_units": len(safe_supported),
        "supported_safe_accepts": len(safe_accepts),
        "supported_safe_recall": safe_recall,
        "unsupported_units": len(unsupported),
        "unsupported_reasoned_unknowns": len(reasoned_unknowns),
        "unsupported_reason_coverage": unsupported_coverage,
        "reason_category_matches": reason_matches,
        "reason_category_accuracy": reason_accuracy,
        "h7b_blind_gate_pass": passed,
        "h7_overall_pass": False,
        "analyzer_sha256": freeze["analyzer_sha256"],
        "adapter_manifest_sha256": freeze["adapter_manifest_sha256"],
        "oracle_sha256": freeze["oracle_sha256"],
    }
    write_csv(OUT / "autocontract_h7b_sources.csv", source_rows)
    write_csv(OUT / "autocontract_h7b_decisions.csv", rows)
    write_csv(OUT / "autocontract_h7b_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7B sealed release-version holdout",
            "",
            "Analyzer, adapter manifest, oracle, releases, units, and thresholds were hashed before source fetch.",
            "",
            f"Decision accuracy: {decision_matches}/{len(rows)} ({decision_matches / len(rows):.1%}).",
            f"Known-unsafe false accepts: {len(false_accepts)}.",
            f"Supported safe recall: {len(safe_accepts)}/{len(safe_supported)} ({safe_recall:.1%}).",
            f"Unsupported reason coverage: {len(reasoned_unknowns)}/{len(unsupported)} ({unsupported_coverage:.1%}).",
            f"Reason-category accuracy: {reason_matches}/{len(rows)} ({reason_accuracy:.1%}).",
            f"H7B blind gate: **{'PASS' if passed else 'FAIL'}**.",
            "H7 overall gate: **INCOMPLETE** until adapter annotation-time amortization is measured.",
            "",
            "## Decisions",
            "",
            "| Unit | Status | Adapter | Expected | Actual | Reason match | Validator reason |",
            "|---|---|---|---|---|---:|---|",
            *[
                f"| `{row['source_id']}::{row['unit']}` | {row['analysis_status']} | {row['adapter']} | "
                f"{row['expected_decision']} | {row['actual_decision']} | "
                f"{'yes' if row['reason_category_match'] else 'no'} | {row['validator_reasons']} |"
                for row in rows
            ],
            "",
            "## Protocol boundary",
            "",
            "This is a release-version holdout, not a new-framework holdout. Two operators (RandomShift and "
            "CachedMixUp) were absent from H7A's evaluated units, but their older source file had already been opened "
            "during the H6 postmortem. The result therefore tests frozen-rule version/operator transfer, not fully "
            "independent project transfer.",
            "",
        ]
    )
    (OUT / "autocontract_h7b_holdout.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
