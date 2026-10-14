"""P4A reproducible accounting of framework-specific adapter burden."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "p4a_adapter_burden_protocol.json"
EXPECTED_PROTOCOL_SHA = "e0827d7598bc416c9930f0630e4de93607d141ae6c870f53ee0ad51b772585b1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def top_level_nodes(path: Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node
    return result


def span(node: ast.AST) -> tuple[int, int]:
    return int(node.lineno), int(getattr(node, "end_lineno", node.lineno))


def logical_sloc(lines: list[str], covered: set[int]) -> int:
    return sum(
        bool(lines[number - 1].strip()) and not lines[number - 1].lstrip().startswith("#")
        for number in covered
    )


def decision_points(node: ast.AST) -> int:
    total = 0
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp, ast.For, ast.AsyncFor, ast.While)):
            total += 1
        elif isinstance(child, ast.Try):
            total += len(child.handlers)
        elif hasattr(ast, "Match") and isinstance(child, ast.Match):
            total += len(child.cases)
        elif isinstance(child, ast.BoolOp):
            total += max(0, len(child.values) - 1)
    return total


def measure_items(entries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    category_lines: dict[str, dict[str, set[int]]] = {}
    item_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        relative = entry["file"]
        category = entry["category"]
        path = ROOT / relative
        nodes = top_level_nodes(path)
        source_lines = path.read_text(encoding="utf-8").splitlines()
        file_lines = category_lines.setdefault(category, {}).setdefault(relative, set())
        for name in entry["names"]:
            node = nodes.get(name)
            if node is None:
                errors.append(f"missing:{relative}:{name}")
                continue
            start, end = span(node)
            covered = set(range(start, end + 1))
            file_lines.update(covered)
            item_rows.append(
                {
                    "file": relative,
                    "category": category,
                    "name": name,
                    "start": start,
                    "end": end,
                    "logical_sloc": logical_sloc(source_lines, covered),
                    "decision_points": decision_points(node),
                }
            )
    overlap: set[tuple[str, int]] = set()
    if "semantic" in category_lines and "binding" in category_lines:
        for relative in set(category_lines["semantic"]) & set(category_lines["binding"]):
            for number in category_lines["semantic"][relative] & category_lines["binding"][relative]:
                overlap.add((relative, number))
    if overlap:
        errors.append("cross_category_overlap:" + ";".join(f"{path}:{line}" for path, line in sorted(overlap)))
    summary: dict[str, Any] = {}
    for category, files in category_lines.items():
        total_sloc = 0
        for relative, covered in files.items():
            lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
            total_sloc += logical_sloc(lines, covered)
        registered = [row for row in item_rows if row["category"] == category]
        summary[category] = {
            "logical_sloc": total_sloc,
            "decision_points": sum(row["decision_points"] for row in registered),
            "registered_items": len(registered),
            "files": len(files),
        }
    return summary, item_rows, errors


def manifest_rules(framework: str, path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if "adapters" in value:
        target = normalize(framework)
        for adapter in value["adapters"]:
            if normalize(adapter["name"]) == target:
                return list(adapter["rules"])
        raise KeyError(f"adapter {framework} absent from {path}")
    return list(value["rules"])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    protocol_sha = sha256(PROTOCOL)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    frozen_checks = {
        relative: sha256(ROOT / relative) == expected
        for relative, expected in protocol["frozen_file_sha256"].items()
    }
    frozen_checks["benchmark/final_v1/contamination_registry.json"] = (
        sha256(ROOT / "benchmark" / "final_v1" / "contamination_registry.json")
        == protocol["frozen_registry_sha256"]
    )
    registry = json.loads(
        (ROOT / "benchmark" / "final_v1" / "contamination_registry.json").read_text(encoding="utf-8")
    )
    contaminated_frameworks = {
        normalize(item["name"]): item["name"]
        for item in registry["development_sources"]
        if item.get("kind") == "framework"
    }

    details: list[dict[str, Any]] = []
    csv_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for registered in protocol["frameworks"]:
        name = registered["name"]
        status = registered["status"]
        detail: dict[str, Any] = {
            "framework": name,
            "status": status,
            "formal_units": int(registered.get("formal_units", 0)),
            "calibration_units": int(registered.get("calibration_units", 0)),
            "operation_decisions": int(registered.get("operation_decisions", registered.get("formal_units", 0))),
            "prospective_onboarding_time": "unavailable",
            "runtime_policy": registered.get("runtime_policy"),
            "reason": registered.get("reason"),
        }
        if status.startswith("adapter"):
            summary, items, item_errors = measure_items(registered["code_items"])
            errors.extend(f"{name}:{error}" for error in item_errors)
            rules = manifest_rules(name, ROOT / registered["manifest"])
            semantic = summary.get("semantic", {"logical_sloc": 0, "decision_points": 0, "registered_items": 0, "files": 0})
            binding = summary.get("binding", {"logical_sloc": 0, "decision_points": 0, "registered_items": 0, "files": 0})
            formal_units = detail["formal_units"]
            rules_per_unit = len(rules) / formal_units
            sloc_per_unit = semantic["logical_sloc"] / formal_units
            thresholds = protocol["diagnostic_thresholds"]
            lightweight = (
                semantic["logical_sloc"] <= thresholds["lightweight_semantic_adapter_sloc_max"]
                and rules_per_unit <= thresholds["lightweight_rules_per_formal_unit_max"]
            )
            detail.update(
                {
                    "declared_rules": rules,
                    "declared_rule_count": len(rules),
                    "rules_per_formal_unit": rules_per_unit,
                    "semantic": semantic,
                    "binding": binding,
                    "semantic_sloc_per_formal_unit": sloc_per_unit,
                    "lightweight_diagnostic": lightweight,
                    "items": items,
                }
            )
        else:
            detail.update(
                {
                    "declared_rules": [],
                    "declared_rule_count": 0,
                    "rules_per_formal_unit": None,
                    "semantic": {"logical_sloc": 0, "decision_points": 0, "registered_items": 0, "files": 0},
                    "binding": {"logical_sloc": 0, "decision_points": 0, "registered_items": 0, "files": 0},
                    "semantic_sloc_per_formal_unit": None,
                    "lightweight_diagnostic": None,
                    "items": [],
                }
            )
        details.append(detail)
        runtime = detail.get("runtime_policy") or {}
        csv_rows.append(
            {
                "framework": name,
                "status": status,
                "formal_units": detail["formal_units"],
                "calibration_units": detail["calibration_units"],
                "operation_decisions": detail["operation_decisions"],
                "declared_rules": detail["declared_rule_count"],
                "rules_per_formal_unit": detail["rules_per_formal_unit"],
                "semantic_sloc": detail["semantic"]["logical_sloc"],
                "semantic_decision_points": detail["semantic"]["decision_points"],
                "binding_sloc": detail["binding"]["logical_sloc"],
                "semantic_sloc_per_formal_unit": detail["semantic_sloc_per_formal_unit"],
                "runtime_components": runtime.get("components", 0),
                "runtime_slots": runtime.get("registered_slots", 0),
                "capability_requirements": runtime.get("capability_requirements", 0),
                "lightweight_diagnostic": detail["lightweight_diagnostic"],
                "prospective_time": detail["prospective_onboarding_time"],
            }
        )

    shared_entries = [
        {"file": item["file"], "category": "shared", "names": item["names"]}
        for item in protocol["shared_infrastructure"]
    ]
    shared_summary, shared_items, shared_errors = measure_items(shared_entries)
    errors.extend(f"shared:{error}" for error in shared_errors)

    registered_names = {normalize(item["framework"]) for item in details}
    adapters = [item for item in details if item["status"].startswith("adapter")]
    lightweight_count = sum(item["lightweight_diagnostic"] is True for item in adapters)
    prospective_count = sum(item["prospective_onboarding_time"] != "unavailable" for item in adapters)
    thresholds = protocol["diagnostic_thresholds"]
    gates = {
        "all_10_contaminated_frameworks_accounted": len(contaminated_frameworks) == 10 and registered_names == set(contaminated_frameworks),
        "all_registered_items_exist_without_category_overlap": not errors,
        "all_8_adapters_have_rules_and_denominator": len(adapters) == 8 and all(item["declared_rule_count"] > 0 and item["formal_units"] > 0 for item in adapters),
        "at_least_75_percent_meet_lightweight_diagnostic": lightweight_count / len(adapters) >= thresholds["minimum_lightweight_framework_fraction"],
        "human_time_claim_correctly_unsupported": prospective_count < thresholds["human_time_claim_requires_prospective_frameworks"],
        "frozen_inputs_unchanged": protocol_sha == EXPECTED_PROTOCOL_SHA and all(frozen_checks.values()),
    }
    result = {
        "schema_version": "autocontract.p4a-adapter-burden-result.v0",
        "artifact_role": "retrospective_code_rule_accounting_not_person_time",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "status": "pass" if all(gates.values()) else "fail",
        "frozen_checks": frozen_checks,
        "registry_frameworks": contaminated_frameworks,
        "summary": {
            "contaminated_frameworks": len(contaminated_frameworks),
            "adapters": len(adapters),
            "unsupported_or_example_only": len(details) - len(adapters),
            "semantic_adapter_sloc": sum(item["semantic"]["logical_sloc"] for item in adapters),
            "binding_glue_sloc": sum(item["binding"]["logical_sloc"] for item in adapters),
            "declared_rules": sum(item["declared_rule_count"] for item in adapters),
            "formal_units": sum(item["formal_units"] for item in adapters),
            "lightweight_frameworks": lightweight_count,
            "prospective_time_frameworks": prospective_count,
            "human_time_displacement_claim": "unsupported_no_prospective_measurement",
            "shared_infrastructure": shared_summary.get("shared", {}),
        },
        "gates": gates,
        "errors": errors,
        "frameworks": details,
        "shared_items": shared_items,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    result_path = OUT / "autocontract_p4a_adapter_burden.json"
    csv_path = OUT / "autocontract_p4a_adapter_burden.csv"
    items_path = OUT / "autocontract_p4a_adapter_items.csv"
    report_path = OUT / "autocontract_p4a_adapter_burden.md"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(csv_path, csv_rows)
    all_item_rows = []
    for detail in details:
        for row in detail["items"]:
            all_item_rows.append({"framework": detail["framework"], **row})
    for row in shared_items:
        all_item_rows.append({"framework": "SHARED", **row})
    write_csv(items_path, all_item_rows)

    summary = result["summary"]
    lines = [
        "# AutoContract P4A adapter burden accounting",
        "",
        f"Preregistered status: **{result['status']}** ({sum(gates.values())}/{len(gates)} gates).",
        "",
        f"- Accounted contaminated frameworks: {summary['contaminated_frameworks']}; adapters: {summary['adapters']}; unsupported/example-only: {summary['unsupported_or_example_only']}.",
        f"- Framework-specific semantic adapter SLOC: {summary['semantic_adapter_sloc']}; binding glue SLOC: {summary['binding_glue_sloc']}; shared infrastructure SLOC: {summary['shared_infrastructure'].get('logical_sloc', 0)}.",
        f"- Declared rules: {summary['declared_rules']} over {summary['formal_units']} formal symbols.",
        f"- Lightweight diagnostic: {summary['lightweight_frameworks']}/{summary['adapters']} frameworks.",
        f"- Prospective onboarding time: {summary['prospective_time_frameworks']}/{summary['adapters']}; human-time displacement claim: **unsupported**.",
        "",
        "| Framework | Status | Formal | Rules | Semantic SLOC | Binding SLOC | Runtime slots | Lightweight |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in csv_rows:
        lines.append(
            f"| {row['framework']} | {row['status']} | {row['formal_units']} | {row['declared_rules']} | {row['semantic_sloc']} | {row['binding_sloc']} | {row['runtime_slots']} | {row['lightweight_diagnostic']} |"
        )
    lines.extend(["", "## Gates", ""])
    for name, passed in gates.items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This audit quantifies retained code and declarations, not the effort required to discover them. Retrospective SLOC/rule ratios cannot support a claim that AutoContract reduces human annotation time. A prospective unseen-framework onboarding log remains required.",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": result["status"],
                "gates_passed": sum(gates.values()),
                "gates_total": len(gates),
                "semantic_sloc": summary["semantic_adapter_sloc"],
                "binding_sloc": summary["binding_glue_sloc"],
                "rules": summary["declared_rules"],
                "lightweight": f"{summary['lightweight_frameworks']}/{summary['adapters']}",
                "human_time_claim": summary["human_time_displacement_claim"],
            }
        )
    )


if __name__ == "__main__":
    main()
