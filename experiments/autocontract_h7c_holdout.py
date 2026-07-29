"""Frozen one-shot TorchIO operator holdout for H7C."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import autocontract_h6_effect_v2 as v2
import autocontract_h7_adapters as h7
import autocontract_h7c_torchio as h7c


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
FREEZE = OUT / "autocontract_h7c_freeze.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    checks = {
        "analyzer_sha256": digest(Path(h7c.__file__)),
        "adapter_manifest_sha256": digest(OUT / "autocontract_h7c_adapter_manifest.json"),
        "protocol_sha256": digest(OUT / "autocontract_h7c_protocol.json"),
    }
    for name, actual in checks.items():
        if actual != freeze[name]:
            raise RuntimeError(f"H7C freeze violation for {name}: {actual}")
    return freeze


def isolated_generic(name: str, path: str) -> h7.AnalysisResult:
    source = h7c.read_source(path)
    probe = v2.V2Unit("torchio_holdout", "class", name, v2.fx())
    return h7.generic_analyze(probe, source)


def decision(result: h7.AnalysisResult) -> tuple[str, tuple[str, ...]]:
    reasons = h7.validator_reasons(result)
    return ("reject" if reasons else "admit"), reasons


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    freeze = verify_freeze()
    protocol = h7c.load_protocol()
    common = protocol["adapter_calibration"]["common_files"]
    rows: list[dict[str, object]] = []
    for item in protocol["sealed_operator_holdout"]:
        generic = isolated_generic(item["name"], item["path"])
        generic_decision, generic_reasons = decision(generic)
        adapted = h7c.infer_torchio(item["name"], item["path"], common)
        actual, reasons = decision(adapted)
        reason_match = (
            not reasons if item["reason"] == "none"
            else any(item["reason"] in reason for reason in reasons)
        )
        rows.append(
            {
                "unit": item["name"],
                "expected_decision": item["expected"],
                "generic_status": generic.status,
                "generic_decision": generic_decision,
                "generic_reasons": ";".join(generic_reasons),
                "adapter_status": adapted.status,
                "adapter_decision": actual,
                "adapter_reasons": ";".join(reasons) or "none",
                "decision_correct": actual == item["expected"],
                "expected_reason": item["reason"],
                "reason_match": reason_match,
                "evidence": ";".join(adapted.evidence) or "none",
            }
        )

    unsafe = [row for row in rows if row["expected_decision"] == "reject"]
    safe = [row for row in rows if row["expected_decision"] == "admit"]
    false_accepts = [row for row in unsafe if row["adapter_decision"] == "admit"]
    safe_accepts = [row for row in safe if row["adapter_decision"] == "admit"]
    reason_matches = sum(row["reason_match"] is True for row in rows)
    generic_unknowns = sum(row["generic_status"] == "unknown" for row in rows)
    thresholds = protocol["adapter_holdout_thresholds"]
    safe_recall = len(safe_accepts) / len(safe)
    reason_accuracy = reason_matches / len(rows)
    passed = (
        len(false_accepts) <= thresholds["known_unsafe_false_accepts"]
        and safe_recall >= thresholds["safe_recall"]
        and reason_accuracy >= thresholds["reason_category_accuracy"]
    )
    summary = {
        "protocol": freeze["protocol"],
        "units": len(rows),
        "generic_unknowns": generic_unknowns,
        "generic_reason_coverage": generic_unknowns / len(rows),
        "generic_safe_recall": sum(row["generic_decision"] == "admit" for row in safe) / len(safe),
        "known_unsafe_false_accepts": len(false_accepts),
        "supported_safe_units": len(safe),
        "supported_safe_accepts": len(safe_accepts),
        "supported_safe_recall": safe_recall,
        "decision_accuracy": sum(row["decision_correct"] is True for row in rows) / len(rows),
        "reason_category_matches": reason_matches,
        "reason_category_accuracy": reason_accuracy,
        "h7c_transfer_gate_pass": passed,
        "analyzer_sha256": freeze["analyzer_sha256"],
        "adapter_manifest_sha256": freeze["adapter_manifest_sha256"],
        "protocol_sha256": freeze["protocol_sha256"],
    }
    write_csv(OUT / "autocontract_h7c_holdout.csv", rows)
    write_csv(OUT / "autocontract_h7c_holdout_summary.csv", [summary])
    report = "\n".join(
        [
            "# AutoContract H7C frozen TorchIO operator holdout",
            "",
            f"Generic Unknown coverage: {generic_unknowns}/{len(rows)} ({generic_unknowns / len(rows):.1%}).",
            f"Generic safe recall: {summary['generic_safe_recall']:.1%}.",
            f"Adapter unsafe false accepts: {len(false_accepts)}.",
            f"Adapter safe recall: {len(safe_accepts)}/{len(safe)} ({safe_recall:.1%}).",
            f"Decision accuracy: {sum(row['decision_correct'] is True for row in rows)}/{len(rows)}.",
            f"Reason-category accuracy: {reason_matches}/{len(rows)} ({reason_accuracy:.1%}).",
            f"H7C transfer gate: **{'PASS' if passed else 'FAIL'}**.",
            "",
            "| Unit | Generic | Adapter | Correct | Reason match | Adapter reason |",
            "|---|---|---|---:|---:|---|",
            *[
                f"| `{row['unit']}` | {row['generic_decision']} | {row['adapter_decision']} | "
                f"{'yes' if row['decision_correct'] else 'no'} | {'yes' if row['reason_match'] else 'no'} | "
                f"{row['adapter_reasons']} |"
                for row in rows
            ],
            "",
            "A failed reason-category gate is retained as a holdout failure; the frozen adapter is not repaired here.",
            "",
        ]
    )
    (OUT / "autocontract_h7c_holdout.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
