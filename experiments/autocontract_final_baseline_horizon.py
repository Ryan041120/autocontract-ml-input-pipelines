"""Internal calibration for final-v1 dynamic baselines and workload horizons.

This module is deliberately separate from the frozen H8A-H8C scripts.  It
contains only synthetic fixtures and public workload metadata; it must not read
the final private oracle or unit-specific threat labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Protocol

import numpy as np

try:
    import torch
except ModuleNotFoundError:  # The protocol self-test must run without framework extras.
    torch = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
DEFAULT_JSON = OUT / "autocontract_final_baseline_horizon_selftest.json"
DEFAULT_REPORT = OUT / "autocontract_final_baseline_horizon_selftest.md"
BASE_SEED = 20260730

CostUnit = Literal["sample", "batch", "epoch", "run"]
ReuseScope = Literal["call", "epoch", "run", "cross_run"]


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, set):
        return sorted(canonical(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return {
            "type": "numpy",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "sha256": hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest(),
        }
    if torch is not None and isinstance(value, torch.Tensor):
        tensor = value.detach().contiguous().cpu()
        return {
            "type": "torch",
            "shape": list(tensor.shape),
            "dtype": str(tensor.dtype),
            "sha256": hashlib.sha256(tensor.numpy().tobytes()).hexdigest(),
        }
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"type": type(value).__qualname__, "repr": repr(value)}


def digest(value: Any) -> str:
    payload = json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RangeInt:
    low: int
    planned: int
    high: int

    def validate(self, name: str, *, minimum: int = 1) -> None:
        if not (minimum <= self.low <= self.planned <= self.high):
            raise ValueError(
                f"{name} must satisfy {minimum} <= low <= planned <= high"
            )


@dataclass(frozen=True)
class WorkloadManifest:
    workload_id: str
    dataset_cardinality: int
    epochs: RangeInt
    planned_runs: RangeInt
    global_batch_size: int
    drop_last: bool
    worker_count: int
    replica_count: int
    candidate_invocations_per_sample: int
    reuse_scope: ReuseScope
    max_valid_epochs: Optional[int] = None
    max_valid_runs: Optional[int] = None

    def validate(self) -> None:
        if not self.workload_id:
            raise ValueError("workload_id must not be empty")
        for name in (
            "dataset_cardinality",
            "global_batch_size",
            "worker_count",
            "replica_count",
            "candidate_invocations_per_sample",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        self.epochs.validate("epochs")
        self.planned_runs.validate("planned_runs")
        if self.max_valid_epochs is not None and self.max_valid_epochs < 1:
            raise ValueError("max_valid_epochs must be >= 1")
        if self.max_valid_runs is not None and self.max_valid_runs < 1:
            raise ValueError("max_valid_runs must be >= 1")


@dataclass(frozen=True)
class CostProfile:
    profile_id: str
    cost_unit: CostUnit
    measured_saving_per_unit_ms: float
    registration_or_build_cost_ms: float
    validation_cost_ms: float = 0.0
    storage_cost_ms: float = 0.0

    def validate(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id must not be empty")
        for name in (
            "measured_saving_per_unit_ms",
            "registration_or_build_cost_ms",
            "validation_cost_ms",
            "storage_cost_ms",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and >= 0")


@dataclass(frozen=True)
class HorizonDecision:
    horizon_source: str
    cost_unit: CostUnit
    horizon_low: int
    horizon_planned: int
    horizon_high: int
    net_benefit_low_ms: float
    net_benefit_planned_ms: float
    net_benefit_high_ms: float
    select_low: bool
    select_planned: bool
    select_high: bool
    decision_stability: Literal["stable_select", "stable_reject", "horizon_unstable"]
    workload_manifest_sha256: str
    cost_profile_sha256: str


def _global_samples_per_epoch(manifest: WorkloadManifest) -> int:
    if not manifest.drop_last:
        return manifest.dataset_cardinality
    return (manifest.dataset_cardinality // manifest.global_batch_size) * manifest.global_batch_size


def _global_batches_per_epoch(manifest: WorkloadManifest) -> int:
    if manifest.drop_last:
        return manifest.dataset_cardinality // manifest.global_batch_size
    return math.ceil(manifest.dataset_cardinality / manifest.global_batch_size)


def _horizon_for(
    manifest: WorkloadManifest, cost_unit: CostUnit, epochs: int, runs: int
) -> int:
    """Derive a global-workload horizon without multiplying by workers/replicas.

    Worker and replica counts affect the measured profile and environment hash,
    not the logical number of global dataset elements.  This avoids silently
    double-counting a sharded dataset.
    """

    if manifest.reuse_scope == "call":
        return 1

    effective_epochs = epochs
    effective_runs = runs
    if manifest.reuse_scope == "epoch":
        effective_epochs, effective_runs = 1, 1
    elif manifest.reuse_scope == "run":
        effective_runs = 1
    if manifest.max_valid_epochs is not None:
        effective_epochs = min(effective_epochs, manifest.max_valid_epochs)
    if manifest.max_valid_runs is not None:
        effective_runs = min(effective_runs, manifest.max_valid_runs)

    if cost_unit == "sample":
        per_epoch = _global_samples_per_epoch(manifest)
        per_epoch *= manifest.candidate_invocations_per_sample
        return per_epoch * effective_epochs * effective_runs
    if cost_unit == "batch":
        return _global_batches_per_epoch(manifest) * effective_epochs * effective_runs
    if cost_unit == "epoch":
        return effective_epochs * effective_runs
    if cost_unit == "run":
        return effective_runs
    raise ValueError(f"unsupported cost unit: {cost_unit}")


def derive_horizon_decision(
    manifest: WorkloadManifest, profile: CostProfile
) -> HorizonDecision:
    manifest.validate()
    profile.validate()
    horizon = tuple(
        _horizon_for(manifest, profile.cost_unit, epochs, runs)
        for epochs, runs in (
            (manifest.epochs.low, manifest.planned_runs.low),
            (manifest.epochs.planned, manifest.planned_runs.planned),
            (manifest.epochs.high, manifest.planned_runs.high),
        )
    )
    if not (1 <= horizon[0] <= horizon[1] <= horizon[2]):
        raise ValueError("derived horizon must be positive and monotonic")
    fixed_cost = (
        profile.registration_or_build_cost_ms
        + profile.validation_cost_ms
        + profile.storage_cost_ms
    )
    net = tuple(value * profile.measured_saving_per_unit_ms - fixed_cost for value in horizon)
    selected = tuple(value > 0 for value in net)
    if all(selected):
        stability: Literal["stable_select", "stable_reject", "horizon_unstable"] = (
            "stable_select"
        )
    elif not any(selected):
        stability = "stable_reject"
    else:
        stability = "horizon_unstable"
    return HorizonDecision(
        horizon_source="workload_manifest",
        cost_unit=profile.cost_unit,
        horizon_low=horizon[0],
        horizon_planned=horizon[1],
        horizon_high=horizon[2],
        net_benefit_low_ms=net[0],
        net_benefit_planned_ms=net[1],
        net_benefit_high_ms=net[2],
        select_low=selected[0],
        select_planned=selected[1],
        select_high=selected[2],
        decision_stability=stability,
        workload_manifest_sha256=digest(asdict(manifest)),
        cost_profile_sha256=digest(asdict(profile)),
    )


class ProbeOperator(Protocol):
    def __call__(self, value: int, *, epoch: int) -> int: ...


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str = "autocontract.dynamic-stateful.v0"
    seed: int = BASE_SEED
    same_context_repeats: int = 2
    cross_context_epochs: tuple[int, int] = (0, 1)
    environment_key: str = "AUTOCONTRACT_FINAL_PROBE_GAIN"
    environment_values: tuple[str, str] = ("1", "2")
    max_operator_calls: int = 7


@dataclass(frozen=True)
class DynamicProbeResult:
    unit_id: str
    output_only_conflict: bool
    stateful_conflict: bool
    observed_effects: tuple[str, ...]
    same_context_output_changed: bool
    fresh_instance_repro_mismatch: bool
    cross_context_output_changed: bool
    rng_state_changed: bool
    object_state_changed: bool
    environment_output_changed: bool
    operator_calls: int
    probe_spec_sha256: str


def seed_all(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    if torch is not None:
        torch.manual_seed(seed)


def rng_digest() -> str:
    torch_state = None if torch is None else bytes(torch.random.get_rng_state().tolist())
    payload = (
        random.getstate(),
        np.random.get_state(),
        torch_state,
    )
    return hashlib.sha256(pickle.dumps(payload, protocol=5)).hexdigest()


def object_state_digest(instance: ProbeOperator) -> str:
    return digest(getattr(instance, "__dict__", {}))


def invoke_with_seed(
    factory: Callable[[], ProbeOperator], value: int, epoch: int, seed: int
) -> tuple[str, str, str, str]:
    seed_all(seed)
    instance = factory()
    state_before = object_state_digest(instance)
    rng_before = rng_digest()
    output = instance(value, epoch=epoch)
    rng_after = rng_digest()
    state_after = object_state_digest(instance)
    return digest(output), state_before, state_after, digest((rng_before, rng_after))


def run_stateful_probe(
    unit_id: str,
    factory: Callable[[], ProbeOperator],
    *,
    value: int = 7,
    spec: ProbeSpec = ProbeSpec(),
) -> DynamicProbeResult:
    if spec.same_context_repeats != 2:
        raise ValueError("v0 requires exactly two same-context repeats")
    if spec.max_operator_calls < 7:
        raise ValueError("probe budget is smaller than the fixed v0 schedule")

    original_env = os.environ.get(spec.environment_key)
    calls = 0
    try:
        os.environ[spec.environment_key] = spec.environment_values[0]
        seed_all(spec.seed)
        same = factory()
        state_before = object_state_digest(same)
        rng_before = rng_digest()
        first = digest(same(value, epoch=spec.cross_context_epochs[0]))
        calls += 1
        state_after_first = object_state_digest(same)
        rng_after_first = rng_digest()
        second = digest(same(value, epoch=spec.cross_context_epochs[0]))
        calls += 1

        fresh_a, _, _, _ = invoke_with_seed(
            factory, value, spec.cross_context_epochs[0], spec.seed
        )
        calls += 1
        fresh_b, _, _, _ = invoke_with_seed(
            factory, value, spec.cross_context_epochs[0], spec.seed
        )
        calls += 1
        cross, _, _, _ = invoke_with_seed(
            factory, value, spec.cross_context_epochs[1], spec.seed
        )
        calls += 1

        os.environ[spec.environment_key] = spec.environment_values[0]
        env_a, _, _, _ = invoke_with_seed(
            factory, value, spec.cross_context_epochs[0], spec.seed
        )
        calls += 1
        os.environ[spec.environment_key] = spec.environment_values[1]
        env_b, _, _, _ = invoke_with_seed(
            factory, value, spec.cross_context_epochs[0], spec.seed
        )
        calls += 1
    finally:
        if original_env is None:
            os.environ.pop(spec.environment_key, None)
        else:
            os.environ[spec.environment_key] = original_env

    flags = {
        "same_context_output_changed": first != second,
        "fresh_instance_repro_mismatch": fresh_a != fresh_b,
        "cross_context_output_changed": fresh_a != cross,
        "rng_state_changed": rng_before != rng_after_first,
        "object_state_changed": state_before != state_after_first,
        "environment_output_changed": env_a != env_b,
    }
    effects = tuple(name for name, observed in flags.items() if observed)
    # The deliberately weak historical-style ablation only observes output in
    # one same context.  It is retained under an explicit name, not presented
    # as a best available dynamic analysis.
    output_only_conflict = flags["same_context_output_changed"]
    return DynamicProbeResult(
        unit_id=unit_id,
        output_only_conflict=output_only_conflict,
        stateful_conflict=bool(effects),
        observed_effects=effects,
        operator_calls=calls,
        probe_spec_sha256=digest(asdict(spec)),
        **flags,
    )


class PureOperator:
    def __call__(self, value: int, *, epoch: int) -> int:
        del epoch
        return value * 2


class HiddenRngOperator:
    def __call__(self, value: int, *, epoch: int) -> int:
        del epoch
        random.random()
        return value


class HiddenStateOperator:
    def __init__(self) -> None:
        self.counter = 0

    def __call__(self, value: int, *, epoch: int) -> int:
        del epoch
        self.counter += 1
        return value


class EnvironmentOperator:
    def __call__(self, value: int, *, epoch: int) -> int:
        del epoch
        return value * int(os.environ[ProbeSpec().environment_key])


class EpochSensitiveOperator:
    def __call__(self, value: int, *, epoch: int) -> int:
        return value + epoch


def self_test() -> dict[str, Any]:
    probe_factories: dict[str, Callable[[], ProbeOperator]] = {
        "pure": PureOperator,
        "hidden_rng": HiddenRngOperator,
        "hidden_state": HiddenStateOperator,
        "environment": EnvironmentOperator,
        "epoch_sensitive": EpochSensitiveOperator,
    }
    probes = {
        name: run_stateful_probe(name, factory) for name, factory in probe_factories.items()
    }

    base_manifest = WorkloadManifest(
        workload_id="synthetic-cache-prefix",
        dataset_cardinality=100,
        epochs=RangeInt(2, 4, 6),
        planned_runs=RangeInt(1, 1, 1),
        global_batch_size=16,
        drop_last=False,
        worker_count=4,
        replica_count=2,
        candidate_invocations_per_sample=1,
        reuse_scope="run",
    )
    stable_select = derive_horizon_decision(
        base_manifest,
        CostProfile("epoch-positive", "epoch", 3.0, 5.0),
    )
    unstable = derive_horizon_decision(
        WorkloadManifest(
            **{
                **asdict(base_manifest),
                "workload_id": "synthetic-horizon-uncertain",
                "epochs": RangeInt(1, 4, 10),
                "planned_runs": base_manifest.planned_runs,
            }
        ),
        CostProfile("epoch-crossing", "epoch", 1.0, 5.0),
    )
    worker_variant = derive_horizon_decision(
        WorkloadManifest(
            **{
                **asdict(base_manifest),
                "workload_id": "synthetic-worker-variant",
                "epochs": base_manifest.epochs,
                "planned_runs": base_manifest.planned_runs,
                "worker_count": 32,
            }
        ),
        CostProfile("epoch-positive", "epoch", 3.0, 5.0),
    )
    invalid_rejected = False
    try:
        derive_horizon_decision(
            WorkloadManifest(
                **{
                    **asdict(base_manifest),
                    "epochs": RangeInt(5, 4, 6),
                    "planned_runs": base_manifest.planned_runs,
                }
            ),
            CostProfile("invalid", "epoch", 1.0, 1.0),
        )
    except ValueError:
        invalid_rejected = True

    checks = {
        "pure_has_no_stateful_conflict": not probes["pure"].stateful_conflict,
        "hidden_rng_missed_by_output_only": not probes["hidden_rng"].output_only_conflict,
        "hidden_rng_found_by_stateful": probes["hidden_rng"].rng_state_changed,
        "hidden_state_missed_by_output_only": not probes["hidden_state"].output_only_conflict,
        "hidden_state_found_by_stateful": probes["hidden_state"].object_state_changed,
        "environment_drift_found": probes["environment"].environment_output_changed,
        "epoch_drift_found": probes["epoch_sensitive"].cross_context_output_changed,
        "fixed_probe_budget_respected": all(item.operator_calls == 7 for item in probes.values()),
        "manifest_horizon_stable_select": stable_select.decision_stability == "stable_select",
        "manifest_horizon_uncertainty_exposed": unstable.decision_stability == "horizon_unstable",
        "workers_do_not_multiply_logical_horizon": (
            worker_variant.horizon_planned == stable_select.horizon_planned
        ),
        "invalid_horizon_manifest_rejected": invalid_rejected,
    }
    return {
        "schema_version": "autocontract.final-baseline-horizon-selftest.v0",
        "artifact_role": "synthetic_internal_calibration_not_benchmark_evidence",
        "base_seed": BASE_SEED,
        "capabilities": {"numpy_rng": True, "torch_rng": torch is not None},
        "probe_spec": asdict(ProbeSpec()),
        "probe_spec_sha256": digest(asdict(ProbeSpec())),
        "dynamic_probe_results": {name: asdict(item) for name, item in probes.items()},
        "horizon_results": {
            "stable_select": asdict(stable_select),
            "horizon_unstable": asdict(unstable),
            "worker_variant": asdict(worker_variant),
        },
        "checks": checks,
        "passed": sum(checks.values()),
        "total": len(checks),
        "status": "pass" if all(checks.values()) else "fail",
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Final-v1 baseline/horizon internal self-test",
        "",
        f"Status: **{payload['status']}** ({payload['passed']}/{payload['total']})",
        "",
        "> Synthetic internal calibration only; this is not final benchmark evidence.",
        "",
        "## Checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    lines.extend(
        f"| `{name}` | {'PASS' if passed else 'FAIL'} |"
        for name, passed in payload["checks"].items()
    )
    lines.extend(
        [
            "",
            "## Dynamic probes",
            "",
            "| Unit | Output-only conflict | Stateful conflict | Observed effects |",
            "|---|---:|---:|---|",
        ]
    )
    for name, result in payload["dynamic_probe_results"].items():
        effects = ", ".join(result["observed_effects"]) or "none"
        lines.append(
            f"| {name} | {result['output_only_conflict']} | "
            f"{result['stateful_conflict']} | {effects} |"
        )
    lines.extend(
        [
            "",
            "## Horizon decisions",
            "",
            "| Scenario | Low / planned / high | Stability |",
            "|---|---|---|",
        ]
    )
    for name, result in payload["horizon_results"].items():
        horizon = f"{result['horizon_low']} / {result['horizon_planned']} / {result['horizon_high']}"
        lines.append(f"| {name} | {horizon} | {result['decision_stability']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    payload = self_test()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "passed": payload["passed"], "total": payload["total"]}))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
