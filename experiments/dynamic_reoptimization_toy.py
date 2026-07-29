"""Toy study of one-shot versus change-aware ML input-pipeline placement.

This is deliberately not a reproduction of Cachew, Pecan, or cedar.  It uses a
small analytical model to test one research hypothesis: after a placement
policy has converged, can changing host/network conditions make that placement
materially suboptimal, and can guarded re-optimization recover the loss?
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"

CLIENT_COST_PER_HOUR = 4.96
REMOTE_COST_PER_HOUR = 0.427319
MAX_REMOTE = 12
MAX_LOCAL = 8
WINDOWS_PER_PHASE = 80
HORIZON_WINDOWS = 30
RECONFIGURATION_MS = 2_000.0
CHANGE_THRESHOLD = 0.08
CHANGE_WINDOWS = 3
MIN_PROJECTED_SAVING = 0.03
COOLDOWN_WINDOWS = 10


@dataclass(frozen=True)
class Phase:
    name: str
    work_ms: float
    remote_capacity: float
    local_capacity: float
    remote_overhead_ms: float
    model_floor_ms: float
    local_model_penalty: float
    contention_knee: int
    contention_quad: float


@dataclass(frozen=True)
class Placement:
    remote: int
    local: int

    @property
    def label(self) -> str:
        return f"r{self.remote}-l{self.local}"


PHASES = (
    Phase("steady", 4200, 1.00, 0.90, 5, 550, 0.000, 7, 0.02),
    Phase("host_contention", 4600, 1.00, 0.38, 6, 600, 0.012, 4, 0.04),
    Phase("network_congestion", 4600, 0.55, 0.85, 35, 600, 0.001, 7, 0.02),
    Phase("augmentation_heavy", 7500, 1.15, 0.72, 8, 620, 0.003, 6, 0.03),
)


def candidates() -> list[Placement]:
    return [
        Placement(remote, local)
        for remote in range(MAX_REMOTE + 1)
        for local in range(MAX_LOCAL + 1)
        if remote + local > 0
    ]


def batch_ms(phase: Phase, placement: Placement) -> float:
    capacity = (
        placement.remote * phase.remote_capacity
        + placement.local * phase.local_capacity
    )
    preprocessing = phase.work_ms / capacity + placement.remote * phase.remote_overhead_ms
    accelerator = phase.model_floor_ms * (
        1.0
        + phase.local_model_penalty * placement.local**2
        + phase.contention_quad
        * max(0, placement.local - phase.contention_knee) ** 2
    )
    return max(preprocessing, accelerator)


def cost_units(phase: Phase, placement: Placement) -> float:
    hourly = CLIENT_COST_PER_HOUR + placement.remote * REMOTE_COST_PER_HOUR
    return hourly * batch_ms(phase, placement)


def best_placement(phase: Phase) -> Placement:
    return min(candidates(), key=lambda p: (cost_units(phase, p), p.remote, p.local))


def phase_at(step: int) -> Phase:
    return PHASES[min(step // WINDOWS_PER_PHASE, len(PHASES) - 1)]


def projected_reconfiguration_is_worthwhile(
    phase: Phase, current: Placement, proposed: Placement
) -> bool:
    current_total = HORIZON_WINDOWS * cost_units(phase, current)
    proposed_total = HORIZON_WINDOWS * cost_units(phase, proposed)
    proposed_total += (
        CLIENT_COST_PER_HOUR + proposed.remote * REMOTE_COST_PER_HOUR
    ) * RECONFIGURATION_MS
    saving = 1.0 - proposed_total / current_total
    return saving >= MIN_PROJECTED_SAVING


def simulate() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rng = random.Random(7)
    total_steps = WINDOWS_PER_PHASE * len(PHASES)
    initial = best_placement(PHASES[0])
    adaptive = initial
    reference_phase = PHASES[0]
    suspicious_windows = 0
    cooldown = 0
    reconfiguration_steps: set[int] = set()
    rows: list[dict[str, object]] = []

    for step in range(total_steps):
        phase = phase_at(step)
        oracle = best_placement(phase)
        observed = batch_ms(phase, adaptive) * (1.0 + rng.gauss(0.0, 0.012))
        expected = batch_ms(reference_phase, adaptive)
        relative_shift = observed / expected - 1.0

        if cooldown > 0:
            cooldown -= 1
            suspicious_windows = 0
        elif abs(relative_shift) >= CHANGE_THRESHOLD:
            suspicious_windows += 1
        else:
            suspicious_windows = 0

        if suspicious_windows >= CHANGE_WINDOWS:
            proposed = oracle
            if proposed != adaptive and projected_reconfiguration_is_worthwhile(
                phase, adaptive, proposed
            ):
                adaptive = proposed
                reconfiguration_steps.add(step)
                cooldown = COOLDOWN_WINDOWS
            reference_phase = phase
            suspicious_windows = 0

        noise = 1.0 + rng.gauss(0.0, 0.008)
        for policy, placement in (
            ("one_shot_stable", initial),
            ("change_aware", adaptive),
            ("phase_oracle", oracle),
        ):
            current_batch = batch_ms(phase, placement) * noise
            reconfigured = policy == "change_aware" and step in reconfiguration_steps
            if reconfigured:
                current_batch += RECONFIGURATION_MS
            hourly = CLIENT_COST_PER_HOUR + placement.remote * REMOTE_COST_PER_HOUR
            rows.append(
                {
                    "window": step,
                    "phase": phase.name,
                    "policy": policy,
                    "remote": placement.remote,
                    "local": placement.local,
                    "batch_ms": current_batch,
                    "cost_units": hourly * current_batch,
                    "reconfigured": int(reconfigured),
                }
            )

    summaries: list[dict[str, object]] = []
    for policy in ("one_shot_stable", "change_aware", "phase_oracle"):
        selected = [row for row in rows if row["policy"] == policy]
        total_batch = sum(float(row["batch_ms"]) for row in selected)
        total_cost = sum(float(row["cost_units"]) for row in selected)
        summaries.append(
            {
                "policy": policy,
                "total_batch_s": total_batch / 1000.0,
                "normalized_cost": total_cost / 1_000_000.0,
                "remote_worker_s": sum(
                    int(row["remote"]) * float(row["batch_ms"]) / 1000.0
                    for row in selected
                ),
                "reconfigurations": sum(int(row["reconfigured"]) for row in selected),
            }
        )
    return rows, summaries


def write_outputs(
    rows: list[dict[str, object]], summaries: list[dict[str, object]]
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "dynamic_reoptimization_trace.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (OUT / "dynamic_reoptimization_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    colors = {
        "one_shot_stable": "#E45756",
        "change_aware": "#4C78A8",
        "phase_oracle": "#54A24B",
    }
    for policy, color in colors.items():
        selected = [row for row in rows if row["policy"] == policy]
        axes[0].plot(
            [int(row["window"]) for row in selected],
            [float(row["batch_ms"]) for row in selected],
            label=policy,
            color=color,
            linewidth=1.5,
        )
        axes[1].step(
            [int(row["window"]) for row in selected],
            [int(row["remote"]) for row in selected],
            where="post",
            label=policy,
            color=color,
            linewidth=1.5,
        )
    for boundary in range(WINDOWS_PER_PHASE, WINDOWS_PER_PHASE * len(PHASES), WINDOWS_PER_PHASE):
        for axis in axes:
            axis.axvline(boundary, color="#777777", linestyle="--", linewidth=0.8)
    axes[0].set_ylabel("batch time (ms)")
    axes[0].set_title("Toy non-stationary placement study (not a paper reproduction)")
    axes[0].legend()
    axes[1].set_ylabel("remote workers")
    axes[1].set_xlabel("measurement window")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT / "dynamic_reoptimization_toy.png", dpi=220)


def main() -> None:
    rows, summaries = simulate()
    write_outputs(rows, summaries)
    print("Per-phase cost-optimal placements:")
    for phase in PHASES:
        placement = best_placement(phase)
        print(
            f"  {phase.name:20s} {placement.label:8s} "
            f"batch={batch_ms(phase, placement):7.1f} ms"
        )
    print("\nAggregate toy results:")
    for row in summaries:
        print(
            f"  {row['policy']:16s} batch={row['total_batch_s']:7.2f}s "
            f"cost={row['normalized_cost']:.4f} "
            f"remote_s={row['remote_worker_s']:.1f} "
            f"reconfigs={row['reconfigurations']}"
        )


if __name__ == "__main__":
    main()
