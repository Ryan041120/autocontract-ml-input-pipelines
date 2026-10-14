"""R3-P1 real-source Kornia calibration against a source-guided baseline.

The nine H7H units and their oracle are already known.  This runner is a
posthoc novelty gate: predictions are produced from label-stripped public unit
views before expected decisions/reasons are joined for scoring.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib
import inspect
import json
import statistics
import sys
import textwrap
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import numpy as np
import torch

import autocontract_final_baseline_horizon as baseline
import autocontract_h7h_effect_v7 as effect_v7
import autocontract_h7h_kornia as h7h


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "r3_p1_kornia_greybox_protocol.json"
H7H_PROTOCOL = OUT / "autocontract_h7h_protocol.json"
H7H_FREEZE = OUT / "autocontract_h7h_freeze.json"
SYMBOLS = OUT / "autocontract_h7h_symbol_manifest.json"
ADAPTER_MANIFEST = OUT / "autocontract_h7h_adapter_manifest.json"
DEFAULT_JSON = OUT / "autocontract_r3_p1_kornia_greybox.json"
DEFAULT_CSV = OUT / "autocontract_r3_p1_kornia_greybox.csv"
DEFAULT_REPORT = OUT / "autocontract_r3_p1_kornia_greybox.md"
BASE_SEED = 20260730


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PublicUnit:
    unit_id: str
    public_symbol: str
    configuration: str
    phase: str


@dataclass(frozen=True)
class Prediction:
    policy: str
    budget_ms: int
    unit_id: str
    admitted: bool
    outcome: str
    reasons: Tuple[str, ...]
    calls: int
    preparation_ms: float
    elapsed_ms: float
    budget_overrun: bool
    output_stable: Optional[bool]
    gradient_connected: Optional[bool]


def verify_h7h_freeze() -> Dict[str, Any]:
    freeze = json.loads(H7H_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "repository_commit": h7h.repository_revision(),
        "effect_v7_sha256": sha256(Path(effect_v7.__file__)),
        "adapter_sha256": sha256(Path(h7h.__file__)),
        "adapter_manifest_sha256": sha256(ADAPTER_MANIFEST),
        "protocol_sha256": sha256(H7H_PROTOCOL),
        "symbol_manifest_sha256": sha256(SYMBOLS),
    }
    for key, actual in checks.items():
        if str(freeze[key]).lower() != str(actual).lower():
            raise RuntimeError(f"H7H freeze mismatch: {key}")
    return freeze


def load_units() -> Tuple[List[PublicUnit], Dict[str, Dict[str, str]]]:
    protocol = json.loads(H7H_PROTOCOL.read_text(encoding="utf-8"))
    public: List[PublicUnit] = []
    oracle: Dict[str, Dict[str, str]] = {}
    for index, item in enumerate(protocol["sealed_units"]):
        unit_id = f"kornia-{index:02d}-{item['configuration'].rsplit('.', 1)[-1]}"
        public.append(
            PublicUnit(
                unit_id=unit_id,
                public_symbol=str(item["public_symbol"]),
                configuration=str(item["configuration"]),
                phase=str(item["phase"]),
            )
        )
        oracle[unit_id] = {
            "expected": str(item["expected"]),
            "coarse_reason": str(item["coarse_reason"]),
        }
    return public, oracle


def binding_map() -> Dict[str, Dict[str, object]]:
    manifest = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    return {str(item["public_symbol"]): item for item in manifest["bindings"]}


def effect_v7_predictions(
    units: List[PublicUnit],
) -> Tuple[List[Prediction], float]:
    bindings = binding_map()
    setup_started = time.perf_counter_ns()
    classes = h7h.package_classes()
    setup_ms = (time.perf_counter_ns() - setup_started) / 1e6
    rows: List[Prediction] = []
    for unit in units:
        started = time.perf_counter_ns()
        try:
            result = h7h.analyze(bindings[unit.public_symbol], classes, unit.configuration)
            reasons = effect_v7.validator_v7(result)
            outcome = "classified"
        except Exception as exc:  # Keep failures in the denominator.
            reasons = ("analysis_crash:" + type(exc).__name__,)
            outcome = "crash"
        elapsed_ms = (time.perf_counter_ns() - started) / 1e6
        rows.append(
            Prediction(
                policy="effect_v7_frozen",
                budget_ms=0,
                unit_id=unit.unit_id,
                admitted=outcome == "classified" and not reasons,
                outcome=outcome,
                reasons=tuple(reasons),
                calls=0,
                preparation_ms=0.0,
                elapsed_ms=elapsed_ms,
                budget_overrun=False,
                output_stable=None,
                gradient_connected=None,
            )
        )
    return rows, setup_ms


def resolve_symbol(symbol: str) -> Type[object]:
    module_name, name = symbol.rsplit(".", 1)
    module = importlib.import_module(module_name)
    value = getattr(module, name)
    if not isinstance(value, type):
        raise TypeError(f"symbol is not a class: {symbol}")
    return value


def build_operator(symbol: str) -> object:
    cls = resolve_symbol(symbol)
    name = cls.__name__
    if name == "RandomVerticalFlip":
        return cls(p=0.5)
    if name == "RandomPosterize":
        return cls(bits=(2.0, 6.0), p=0.5)
    if name == "RandomSolarize":
        return cls(thresholds=(0.1, 0.9), additions=(-0.1, 0.1), p=0.5)
    if name == "RandomMotionBlur":
        return cls(kernel_size=3, angle=(-30.0, 30.0), direction=(-0.5, 0.5), p=0.5)
    if name == "AugmentationSequential":
        child_cls = resolve_symbol(
            "kornia.augmentation._2d.geometric.vertical_flip.RandomVerticalFlip"
        )
        return cls(child_cls(p=0.5))
    raise ValueError(f"missing public runtime factory for {symbol}")


def prepare_runtime(unit: PublicUnit) -> Tuple[object, torch.Tensor, object, float]:
    started = time.perf_counter_ns()
    baseline.seed_all(BASE_SEED)
    operator = build_operator(unit.public_symbol)
    generator = torch.Generator(device="cpu").manual_seed(BASE_SEED)
    value = torch.rand((2, 3, 32, 32), generator=generator, dtype=torch.float32)
    value.requires_grad_(True)
    params: object = None
    if unit.configuration == "kornia.params_provided":
        params = operator.forward_parameters(value.shape)  # type: ignore[attr-defined]
    preparation_ms = (time.perf_counter_ns() - started) / 1e6
    return operator, value, params, preparation_ms


def invoke(operator: object, value: torch.Tensor, params: object) -> object:
    return operator(value, params=copy.deepcopy(params))  # type: ignore[operator]


def is_container_greybox(operator_type: Type[object]) -> bool:
    """Predeclared source/MRO heuristic for unresolved child delegation."""
    return any("Sequential" in item.__name__ for item in operator_type.mro())


def dynamic_prediction(
    unit: PublicUnit,
    budget_ms: int,
    *,
    source_guided: bool,
) -> Prediction:
    policy = "dynamic_source_guided" if source_guided else "dynamic_blackbox"
    preparation_started = time.perf_counter_ns()
    try:
        operator, value, params, preparation_ms = prepare_runtime(unit)
        operator_type = type(operator)
    except Exception as exc:
        return Prediction(
            policy,
            budget_ms,
            unit.unit_id,
            False,
            "crash",
            ("factory_crash:" + type(exc).__name__,),
            0,
            (time.perf_counter_ns() - preparation_started) / 1e6,
            0.0,
            False,
            None,
            None,
        )

    if source_guided and is_container_greybox(operator_type):
        return Prediction(
            policy,
            budget_ms,
            unit.unit_id,
            False,
            "classified",
            ("unresolved_child_delegation",),
            0,
            preparation_ms,
            0.0,
            False,
            None,
            None,
        )

    try:
        baseline.seed_all(BASE_SEED)
        warmup = invoke(operator, value, params)
        reference_digest = baseline.digest(warmup)
        gradient_connected: Optional[bool] = (
            bool(warmup.requires_grad) if isinstance(warmup, torch.Tensor) else None
        )
    except Exception as exc:
        return Prediction(
            policy,
            budget_ms,
            unit.unit_id,
            False,
            "crash",
            ("warmup_crash:" + type(exc).__name__,),
            0,
            preparation_ms,
            0.0,
            False,
            None,
            None,
        )

    reasons: List[str] = []
    outputs: List[str] = []
    calls = 0
    started = time.perf_counter_ns()
    deadline_ns = started + int(budget_ms * 1e6)
    try:
        while calls < 16 and (calls == 0 or time.perf_counter_ns() < deadline_ns):
            before_rng = baseline.rng_digest()
            before_state = baseline.object_state_digest(operator)  # post-warmup state
            output = invoke(operator, value, params)
            calls += 1
            after_rng = baseline.rng_digest()
            after_state = baseline.object_state_digest(operator)
            output_digest = baseline.digest(output)
            outputs.append(output_digest)
            if before_rng != after_rng:
                reasons.append("runtime_sampling_rng")
            if before_state != after_state:
                reasons.append("runtime_state_changed_post_warmup")
            if output_digest != reference_digest:
                reasons.append("same_context_output_changed")
            if reasons:
                break
    except Exception as exc:
        reasons.append("probe_crash:" + type(exc).__name__)
        outcome = "crash"
    else:
        outcome = "classified"
    elapsed_ms = (time.perf_counter_ns() - started) / 1e6
    reasons = list(dict.fromkeys(reasons))
    return Prediction(
        policy=policy,
        budget_ms=budget_ms,
        unit_id=unit.unit_id,
        admitted=outcome == "classified" and not reasons,
        outcome=outcome,
        reasons=tuple(reasons),
        calls=calls,
        preparation_ms=preparation_ms,
        elapsed_ms=elapsed_ms,
        budget_overrun=elapsed_ms > budget_ms,
        output_stable=(len(set(outputs + [reference_digest])) == 1) if outputs else None,
        gradient_connected=gradient_connected,
    )


def coarse_reason_match(expected: str, reasons: Tuple[str, ...]) -> bool:
    if expected == "none":
        return not reasons
    if expected == "sampling_rng":
        return any("rng" in item for item in reasons)
    if expected == "child":
        return any("child" in item for item in reasons)
    return any(expected in item for item in reasons)


def summarize(
    policy: str,
    budget_ms: int,
    predictions: List[Prediction],
    oracle: Dict[str, Dict[str, str]],
) -> Dict[str, object]:
    safe = {key: value["expected"] == "admit" for key, value in oracle.items()}
    tp = sum(item.admitted and safe[item.unit_id] for item in predictions)
    fp = sum(item.admitted and not safe[item.unit_id] for item in predictions)
    fn = sum(not item.admitted and safe[item.unit_id] for item in predictions)
    tn = sum(not item.admitted and not safe[item.unit_id] for item in predictions)
    reason_correct = sum(
        coarse_reason_match(oracle[item.unit_id]["coarse_reason"], item.reasons)
        for item in predictions
        if item.outcome == "classified"
    )
    classified = sum(item.outcome == "classified" for item in predictions)
    return {
        "policy": policy,
        "budget_ms": budget_ms,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "known_unsafe_false_accepts": fp,
        "classified": classified,
        "unknown": sum(item.outcome == "unknown" for item in predictions),
        "crash": sum(item.outcome == "crash" for item in predictions),
        "timeout": sum(item.outcome == "timeout" for item in predictions),
        "reason_accuracy": reason_correct / max(classified, 1),
        "median_preparation_ms": statistics.median(item.preparation_ms for item in predictions),
        "median_policy_ms": statistics.median(item.elapsed_ms for item in predictions),
        "total_calls": sum(item.calls for item in predictions),
        "budget_overruns": sum(item.budget_overrun for item in predictions),
    }


def nonblank_loc(callable_obj: Callable[..., object]) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in textwrap.dedent(inspect.getsource(callable_obj)).splitlines()
    )


def burden_accounting() -> Dict[str, object]:
    adapter = json.loads(ADAPTER_MANIFEST.read_text(encoding="utf-8"))
    return {
        "effect_v7_adapter_rules": len(adapter["rules"]),
        "effect_v7_adapter_loc_proxy": sum(
            nonblank_loc(item)
            for item in (h7h.empty_predecessor, h7h.is_child_container, h7h.analyze)
        ),
        "greybox_semantic_guidance_rules": 1,
        "greybox_guidance_loc": nonblank_loc(is_container_greybox),
        "runtime_factory_entries": 5,
        "runtime_factory_loc": nonblank_loc(build_operator),
        "manual_unit_hints": 9,
        "manual_hint_fields": 18,
        "note": "LOC is a mechanical proxy; historical development time is unavailable and is not reconstructed from memory.",
    }


def run() -> Dict[str, object]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    budgets = [int(item) for item in protocol["runtime_probe"]["wall_clock_budgets_ms"]]
    freeze = verify_h7h_freeze()
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import kornia  # noqa: F401 - binds runtime to the vendored real source.

    units, oracle = load_units()
    effect_rows, effect_setup_ms = effect_v7_predictions(units)
    blackbox: Dict[int, List[Prediction]] = {
        budget: [dynamic_prediction(unit, budget, source_guided=False) for unit in units]
        for budget in budgets
    }
    greybox: Dict[int, List[Prediction]] = {
        budget: [dynamic_prediction(unit, budget, source_guided=True) for unit in units]
        for budget in budgets
    }

    # Manual predictions are created only after oracle join and remain an upper bound.
    manual = [
        Prediction(
            "manual_full",
            0,
            unit.unit_id,
            oracle[unit.unit_id]["expected"] == "admit",
            "classified",
            ()
            if oracle[unit.unit_id]["coarse_reason"] == "none"
            else ("manual_" + oracle[unit.unit_id]["coarse_reason"],),
            0,
            0.0,
            0.0,
            False,
            None,
            None,
        )
        for unit in units
    ]
    summaries = [summarize("effect_v7_frozen", 0, effect_rows, oracle)]
    summaries.extend(
        summarize("dynamic_blackbox", budget, rows, oracle)
        for budget, rows in blackbox.items()
    )
    summaries.extend(
        summarize("dynamic_source_guided", budget, rows, oracle)
        for budget, rows in greybox.items()
    )
    summaries.append(summarize("manual_full", 0, manual, oracle))
    by_key = {(str(row["policy"]), int(row["budget_ms"])): row for row in summaries}
    checks = {
        "h7h_freeze_verified": bool(freeze),
        "nine_real_source_units": len(units) == 9,
        "effect_v7_reproduces_zero_false_accepts": int(
            by_key[("effect_v7_frozen", 0)]["known_unsafe_false_accepts"]
        )
        == 0,
        "effect_v7_reproduces_full_safe_recall": float(
            by_key[("effect_v7_frozen", 0)]["safe_recall"]
        )
        == 1.0,
        "blackbox_result_budget_stable": len(
            {
                (
                    int(by_key[("dynamic_blackbox", budget)]["tp"]),
                    int(by_key[("dynamic_blackbox", budget)]["fp"]),
                    int(by_key[("dynamic_blackbox", budget)]["fn"]),
                    int(by_key[("dynamic_blackbox", budget)]["tn"]),
                )
                for budget in budgets
            }
        )
        == 1,
        "greybox_result_budget_stable": len(
            {
                (
                    int(by_key[("dynamic_source_guided", budget)]["tp"]),
                    int(by_key[("dynamic_source_guided", budget)]["fp"]),
                    int(by_key[("dynamic_source_guided", budget)]["fn"]),
                    int(by_key[("dynamic_source_guided", budget)]["tn"]),
                )
                for budget in budgets
            }
        )
        == 1,
        "manual_upper_bound_reproduced": int(by_key[("manual_full", 0)]["tp"]) == 4
        and int(by_key[("manual_full", 0)]["tn"]) == 5,
        "all_units_accounted_for": all(
            int(row["classified"])
            + int(row["unknown"])
            + int(row["crash"])
            + int(row["timeout"])
            == 9
            for row in summaries
        ),
    }
    all_predictions = effect_rows + manual
    for rows in blackbox.values():
        all_predictions.extend(rows)
    for rows in greybox.values():
        all_predictions.extend(rows)
    return {
        "schema_version": "autocontract.r3-p1-kornia-greybox.v0",
        "artifact_role": "posthoc_real_source_method_calibration_not_blind_evidence",
        "protocol_sha256": sha256(PROTOCOL),
        "h7h_freeze_sha256": sha256(H7H_FREEZE),
        "repository_commit": freeze["repository_commit"],
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "numpy": np.__version__,
            "cuda_available": torch.cuda.is_available(),
            "kornia_source": str(REPO),
        },
        "effect_v7_shared_setup_ms": effect_setup_ms,
        "burden": burden_accounting(),
        "summaries": summaries,
        "predictions": [asdict(item) for item in all_predictions],
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
        "# AutoContract R3-P1 Kornia real-source greybox calibration",
        "",
        f"Status: **{payload['status']}** ({payload['passed']}/{payload['total']})",
        "",
        "> Posthoc method calibration on the already-known H7H source/oracle; not a new blind result.",
        "",
        "## Policy comparison",
        "",
        "| Policy | Budget | TP | FP | FN | TN | Safe recall | Reason accuracy | Classified/Crash | Median prep | Median policy | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["summaries"]:
        lines.append(
            f"| {row['policy']} | {row['budget_ms']} ms | {row['tp']} | {row['fp']} | "
            f"{row['fn']} | {row['tn']} | {float(row['safe_recall']):.1%} | "
            f"{float(row['reason_accuracy']):.1%} | {row['classified']}/{row['crash']} | "
            f"{float(row['median_preparation_ms']):.3f} ms | "
            f"{float(row['median_policy_ms']):.3f} ms | {row['total_calls']} |"
        )
    burden = payload["burden"]
    lines.extend(
        [
            "",
            "## Burden accounting",
            "",
            f"- EffectV7 Kornia adapter: {burden['effect_v7_adapter_rules']} rules, {burden['effect_v7_adapter_loc_proxy']} LOC proxy.",
            f"- Greybox semantic guidance: {burden['greybox_semantic_guidance_rules']} rule, {burden['greybox_guidance_loc']} LOC.",
            f"- Shared runtime factories: {burden['runtime_factory_entries']} entries, {burden['runtime_factory_loc']} LOC.",
            f"- Manual upper bound: {burden['manual_unit_hints']} unit hints / {burden['manual_hint_fields']} decision+reason fields.",
            "",
            "## Interpretation",
            "",
            "The decisive question is whether one public MRO/container heuristic lets source-guided dynamic close the black-box child-delegation false accept while preserving replay cases. If so, this nine-unit scope does not establish a detection-accuracy advantage for the full EffectV7 adapter; any retained contribution must come from broader effect coverage, stable contract reasons, and invalidation/audit artifacts.",
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
