"""H8C-R2 novelty falsification: contract analysis vs dynamic probe budgets.

The public protocol and parameterized threat fixtures are separate, hashable
artifacts.  Both policies run before oracle labels are joined for scoring.  The
contract policy reuses EffectV7's conservative reachable-path traversal but
uses a small generic threat adapter; this is an internal pilot, not a new
EffectV7 cross-framework result.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import math
import statistics
import sys
import tempfile
import textwrap
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Type

import numpy as np
import torch

import autocontract_final_baseline_horizon as baseline
import autocontract_h7h_effect_v7 as effect_v7
import autocontract_h8c_r2_threat_fixtures as fixtures


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "h8c_r2_novelty_falsification_protocol.json"
FIXTURES = Path(fixtures.__file__)
DEFAULT_JSON = OUT / "autocontract_h8c_r2_novelty_falsification.json"
DEFAULT_CSV = OUT / "autocontract_h8c_r2_novelty_falsification.csv"
DEFAULT_REPORT = OUT / "autocontract_h8c_r2_novelty_falsification.md"
BASE_SEED = 20260730


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_sha256(operator_type: Type[object]) -> str:
    source = textwrap.dedent(inspect.getsource(operator_type))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    operator_type: Type[object]
    factory: Callable[[], object]
    expected_source_sha256: str
    external_path: Optional[Path] = None
    bound_external_sha256: Optional[str] = None
    gradient_applicable: bool = False


@dataclass(frozen=True)
class Prediction:
    policy: str
    budget: int
    case_id: str
    family: str
    admitted: bool
    reasons: Tuple[str, ...]
    calls: int
    elapsed_ms: float


def make_cases() -> List[Case]:
    root = Path(tempfile.gettempdir()) / "autocontract_h8c_r2"
    root.mkdir(parents=True, exist_ok=True)
    bound_path = root / "bound_gain.txt"
    unbound_path = root / "unbound_gain.txt"
    bound_path.write_text("2\n", encoding="utf-8")
    unbound_path.write_text("2\n", encoding="utf-8")

    def current(cls: Type[object]) -> str:
        return source_sha256(cls)

    cases: List[Case] = [
        Case("safe_pure", "safe_control", fixtures.SafePure, fixtures.SafePure, current(fixtures.SafePure)),
        Case(
            "safe_mode_pure",
            "safe_control",
            fixtures.SafeModePure,
            fixtures.SafeModePure,
            current(fixtures.SafeModePure),
        ),
        Case(
            "safe_keyed_deterministic",
            "safe_control",
            fixtures.SafeKeyedDeterministic,
            fixtures.SafeKeyedDeterministic,
            current(fixtures.SafeKeyedDeterministic),
        ),
        Case(
            "safe_content_bound_file",
            "safe_control",
            fixtures.ExternalFile,
            lambda: fixtures.ExternalFile(bound_path),
            current(fixtures.ExternalFile),
            external_path=bound_path,
            bound_external_sha256=file_sha256(bound_path),
        ),
    ]
    for threshold in (224, 240, 248, 252):
        cases.append(
            Case(
                f"rare_rng_t{threshold}",
                "rare_input_rng",
                fixtures.RareInputRng,
                lambda threshold=threshold: fixtures.RareInputRng(threshold),
                current(fixtures.RareInputRng),
            )
        )
    for period in (4, 8, 16, 32):
        cases.append(
            Case(
                f"periodic_global_p{period}",
                "periodic_global_state",
                fixtures.PeriodicGlobalState,
                lambda period=period: fixtures.PeriodicGlobalState(
                    f"period-{period}", period
                ),
                current(fixtures.PeriodicGlobalState),
            )
        )
    cases.append(
        Case(
            "unbound_external_file",
            "unbound_external_file",
            fixtures.ExternalFile,
            lambda: fixtures.ExternalFile(unbound_path),
            current(fixtures.ExternalFile),
            external_path=unbound_path,
        )
    )
    for worker in (1, 4, 8):
        cases.append(
            Case(
                f"worker_mode_rng_w{worker}",
                "worker_mode_rng",
                fixtures.WorkerModeRng,
                lambda worker=worker: fixtures.WorkerModeRng(worker),
                current(fixtures.WorkerModeRng),
            )
        )
    cases.extend(
        [
            Case(
                "gradient_detach",
                "gradient_detach",
                fixtures.GradientDetach,
                fixtures.GradientDetach,
                current(fixtures.GradientDetach),
                gradient_applicable=True,
            ),
            Case(
                "source_drift",
                "source_drift",
                fixtures.SafePure,
                fixtures.SafePure,
                "0" * 64,
            ),
        ]
    )
    return cases


def call_name(node: ast.AST) -> str:
    return effect_v7.attribute_chain(node)


def assignment_targets(node: ast.AST) -> List[ast.AST]:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        if isinstance(node, ast.Assign):
            return list(node.targets)
        return [node.target]
    if isinstance(node, ast.AugAssign):
        return [node.target]
    return []


def target_root_name(target: ast.AST) -> str:
    current = target
    while isinstance(current, (ast.Attribute, ast.Subscript)):
        current = current.value
    return current.id if isinstance(current, ast.Name) else ""


def contract_predict(case: Case) -> Prediction:
    started = time.perf_counter_ns()
    source = textwrap.dedent(inspect.getsource(case.operator_type))
    tree = ast.parse(source)
    root = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    context = effect_v7.ReachabilityContext(
        configuration="h8c-r2.public",
        phase="sample_apply",
        values=(),
    )
    nodes, _methods, _guards, unresolved = effect_v7.reachable_nodes(
        root, {root.name: root}, "__call__", context
    )
    reasons: List[str] = []
    if unresolved:
        reasons.append("unresolved_reachable_dispatch")
    for fragment in nodes:
        for child in ast.walk(fragment):
            if isinstance(child, ast.Call):
                name = call_name(child.func)
                if name in {
                    "random.random",
                    "random.randrange",
                    "np.random.random",
                    "np.random.rand",
                    "torch.rand",
                    "torch.randn",
                }:
                    reasons.append("reachable_sampling_rng")
                if (
                    name in {"open", "time.time", "os.getenv", "os.environ.get"}
                    or name.endswith(".read_text")
                    or name.endswith(".read_bytes")
                ):
                    reasons.append("reachable_external_read")
                if name.endswith(".detach"):
                    reasons.append("reachable_gradient_detach")
            for target in assignment_targets(child):
                root_name = target_root_name(target)
                if root_name == "self":
                    reasons.append("reachable_instance_state_write")
                elif root_name and root_name.isupper():
                    reasons.append("reachable_global_state_write")

    actual_source = source_sha256(case.operator_type)
    if actual_source != case.expected_source_sha256:
        reasons.append("source_binding_mismatch")
    if "reachable_external_read" in reasons and case.bound_external_sha256 is not None:
        current = file_sha256(case.external_path) if case.external_path is not None else None
        if current == case.bound_external_sha256:
            reasons = [item for item in reasons if item != "reachable_external_read"]
        else:
            reasons.append("external_binding_mismatch")
    reasons = list(dict.fromkeys(reasons))
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    return Prediction(
        policy="effect_v7_style_contract",
        budget=0,
        case_id=case.case_id,
        family=case.family,
        admitted=not reasons,
        reasons=tuple(reasons),
        calls=0,
        elapsed_ms=elapsed_ms,
    )


def van_der_corput_8bit(index: int) -> int:
    value = 0.0
    denominator = 1.0
    current = index
    while current:
        current, remainder = divmod(current, 2)
        denominator *= 2.0
        value += remainder / denominator
    return int(value * 256)


def dynamic_predict(case: Case, budget: int) -> Prediction:
    fixtures.reset_global_counts()
    baseline.seed_all(BASE_SEED)
    started = time.perf_counter_ns()
    reasons: List[str] = []
    actual_source = source_sha256(case.operator_type)
    if actual_source != case.expected_source_sha256:
        reasons.append("source_binding_mismatch")
    if case.bound_external_sha256 is not None:
        current = file_sha256(case.external_path) if case.external_path is not None else None
        if current != case.bound_external_sha256:
            reasons.append("external_binding_mismatch")

    instance = case.factory()
    worker_schedule = (0, 1, 2, 4, 8)
    calls = 0
    for offset in range(budget):
        integer_value = van_der_corput_8bit(offset + 1)
        context = {
            "training": True,
            "worker_id": worker_schedule[offset % len(worker_schedule)],
        }
        before_rng = baseline.rng_digest()
        before_state = baseline.object_state_digest(instance)
        if case.gradient_applicable:
            value = torch.tensor(float(integer_value), requires_grad=True)
            output = instance(value, context)
            if not isinstance(output, torch.Tensor) or not output.requires_grad:
                reasons.append("gradient_connectivity_changed")
        else:
            output = instance(integer_value, context)
        calls += 1
        after_rng = baseline.rng_digest()
        after_state = baseline.object_state_digest(instance)
        baseline.digest(output)
        if before_rng != after_rng:
            reasons.append("rng_state_changed")
        if before_state != after_state:
            reasons.append("instance_state_changed")
    reasons = list(dict.fromkeys(reasons))
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    return Prediction(
        policy="dynamic_stateful_bound",
        budget=budget,
        case_id=case.case_id,
        family=case.family,
        admitted=not reasons,
        reasons=tuple(reasons),
        calls=calls,
        elapsed_ms=elapsed_ms,
    )


def summarize(
    policy: str,
    budget: int,
    predictions: List[Prediction],
    oracle_safe: Dict[str, bool],
) -> Dict[str, object]:
    tp = sum(item.admitted and oracle_safe[item.case_id] for item in predictions)
    fp = sum(item.admitted and not oracle_safe[item.case_id] for item in predictions)
    fn = sum(not item.admitted and oracle_safe[item.case_id] for item in predictions)
    tn = sum(not item.admitted and not oracle_safe[item.case_id] for item in predictions)
    return {
        "policy": policy,
        "budget": budget,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "unsafe_detection_rate": tn / max(fp + tn, 1),
        "median_elapsed_ms_per_case": statistics.median(
            item.elapsed_ms for item in predictions
        ),
        "total_operator_calls": sum(item.calls for item in predictions),
    }


def family_detection(
    predictions: List[Prediction], oracle_safe: Dict[str, bool]
) -> Dict[str, float]:
    families: Dict[str, List[bool]] = {}
    for item in predictions:
        if oracle_safe[item.case_id]:
            continue
        families.setdefault(item.family, []).append(not item.admitted)
    return {
        family: sum(values) / len(values) for family, values in sorted(families.items())
    }


def run() -> Dict[str, object]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    budgets = [int(item) for item in protocol["dynamic_policy"]["budgets"]]
    cases = make_cases()

    # Both prediction sets are produced before oracle labels are joined below.
    contract = [contract_predict(case) for case in cases]
    dynamic_by_budget = {
        budget: [dynamic_predict(case, budget) for case in cases] for budget in budgets
    }

    oracle_safe = {
        "safe_pure": True,
        "safe_mode_pure": True,
        "safe_keyed_deterministic": True,
        "safe_content_bound_file": True,
        **{f"rare_rng_t{x}": False for x in (224, 240, 248, 252)},
        **{f"periodic_global_p{x}": False for x in (4, 8, 16, 32)},
        "unbound_external_file": False,
        **{f"worker_mode_rng_w{x}": False for x in (1, 4, 8)},
        "gradient_detach": False,
        "source_drift": False,
    }
    summaries = [summarize("effect_v7_style_contract", 0, contract, oracle_safe)]
    summaries.extend(
        summarize("dynamic_stateful_bound", budget, rows, oracle_safe)
        for budget, rows in dynamic_by_budget.items()
    )
    family_rows = {
        str(budget): family_detection(rows, oracle_safe)
        for budget, rows in dynamic_by_budget.items()
    }
    by_budget = {int(row["budget"]): row for row in summaries if row["budget"] != 0}
    contract_summary = summaries[0]
    checks = {
        "protocol_budgets_preserved": budgets == [1, 3, 7, 15, 31, 63],
        "four_safe_fourteen_unsafe_cases": sum(oracle_safe.values()) == 4
        and sum(not item for item in oracle_safe.values()) == 14,
        "predictions_cover_oracle_ids_exactly": {item.case_id for item in contract}
        == set(oracle_safe)
        and all({item.case_id for item in rows} == set(oracle_safe) for rows in dynamic_by_budget.values()),
        "contract_zero_false_accepts": int(contract_summary["fp"]) == 0,
        "contract_preserves_all_safe_controls": int(contract_summary["tp"]) == 4,
        "dynamic_detection_monotonic": all(
            float(by_budget[left]["unsafe_detection_rate"])
            <= float(by_budget[right]["unsafe_detection_rate"])
            for left, right in zip(budgets, budgets[1:])
        ),
        "budget_seven_does_not_match_contract": int(by_budget[7]["fp"])
        > int(contract_summary["fp"]),
        "budget_sixty_three_exposes_unbound_external_limit": int(by_budget[63]["fp"])
        == 1,
        "all_policies_preserve_safe_controls": all(int(row["tp"]) == 4 for row in summaries),
    }
    predictions = contract + [item for budget in budgets for item in dynamic_by_budget[budget]]
    return {
        "schema_version": "autocontract.h8c-r2-novelty-falsification.v0",
        "artifact_role": "synthetic_internal_novelty_falsification_not_blind_evidence",
        "protocol_sha256": file_sha256(PROTOCOL),
        "fixtures_sha256": file_sha256(FIXTURES),
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "numpy": np.__version__,
            "cuda_available": torch.cuda.is_available(),
        },
        "cases": [
            {
                "case_id": case.case_id,
                "family": case.family,
                "source_sha256": source_sha256(case.operator_type),
                "expected_source_sha256": case.expected_source_sha256,
                "external_binding_declared": case.bound_external_sha256 is not None,
                "gradient_applicable": case.gradient_applicable,
            }
            for case in cases
        ],
        "summaries": summaries,
        "family_detection_by_budget": family_rows,
        "predictions": [asdict(item) for item in predictions],
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "status": "pass" if all(checks.values()) else "fail",
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def render_report(payload: Dict[str, object]) -> str:
    lines = [
        "# AutoContract H8C-R2 novelty falsification",
        "",
        f"Status: **{payload['status']}** ({payload['passed']}/{payload['total']})",
        "",
        "> Synthetic parameterized threats with known source/oracle; not final benchmark evidence.",
        "",
        "## Detection-budget frontier",
        "",
        "| Policy | Budget | TP | FP | FN | TN | Safe recall | Unsafe detection | Median ms/case | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["summaries"]:
        lines.append(
            f"| {row['policy']} | {row['budget']} | {row['tp']} | {row['fp']} | "
            f"{row['fn']} | {row['tn']} | {float(row['safe_recall']):.1%} | "
            f"{float(row['unsafe_detection_rate']):.1%} | "
            f"{float(row['median_elapsed_ms_per_case']):.3f} | {row['total_operator_calls']} |"
        )
    lines.extend(
        [
            "",
            "## Family detection by dynamic budget",
            "",
            "| Budget | Rare input RNG | Periodic global | Worker/mode RNG | External | Gradient | Source drift |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for budget, row in payload["family_detection_by_budget"].items():
        lines.append(
            f"| {budget} | {row['rare_input_rng']:.1%} | "
            f"{row['periodic_global_state']:.1%} | {row['worker_mode_rng']:.1%} | "
            f"{row['unbound_external_file']:.1%} | {row['gradient_detach']:.1%} | "
            f"{row['source_drift']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The contract pilot detects all preregistered unsafe families while preserving four safe controls. Dynamic detection improves monotonically with budget, but finite budgets trade calls for coverage and do not discover an unbound external-file dependency. This supports a narrower hypothesis: source contracts may add value through path/dependency discovery and auditability, not because stateful dynamic testing is intrinsically weak.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    payload = run()
    args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_csv(args.csv, payload["summaries"])
    args.report.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "passed": payload["passed"], "total": payload["total"]}))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
