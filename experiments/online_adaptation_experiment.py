"""Continuous fixed-versus-adaptive DataLoader experiment.

The run has two phases: normal execution and CPU/memory contention.  The fixed
policy keeps eight DataLoader workers.  The adaptive policy watches batch time,
detects a sustained phase shift, and changes to six workers at a safe point only
when a short candidate probe predicts a worthwhile improvement.

The worker choices come from the preceding local sweep.  This script tests the
runtime control path and charges loader shutdown/startup to the adaptive policy.
It remains a single-machine mechanism experiment, not a Pecan reproduction.
"""

from __future__ import annotations

import argparse
import csv
import gc
import multiprocessing as mp
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from real_cpu_contention_benchmark import (
    SmallCudaCNN,
    SyntheticAugmentationDataset,
    build_loader,
    start_contention,
    stop_contention,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


@dataclass
class LoaderSession:
    workers: int
    loader: object
    iterator: object
    pending: tuple[torch.Tensor, torch.Tensor] | None
    startup_ms: float


def start_session(
    workers: int,
    total_batches: int,
    batch_size: int,
    image_size: int,
    augmentation_rounds: int,
) -> LoaderSession:
    dataset = SyntheticAugmentationDataset(
        length=(total_batches + 4) * batch_size,
        image_size=image_size,
        augmentation_rounds=augmentation_rounds,
    )
    loader = build_loader(dataset, batch_size, workers)
    started = time.perf_counter()
    iterator = iter(loader)
    pending = next(iterator)
    startup_ms = (time.perf_counter() - started) * 1000.0
    return LoaderSession(workers, loader, iterator, pending, startup_ms)


def close_session(session: LoaderSession) -> float:
    started = time.perf_counter()
    shutdown = getattr(session.iterator, "_shutdown_workers", None)
    if shutdown is not None:
        shutdown()
    session.pending = None
    del session.iterator, session.loader
    gc.collect()
    return (time.perf_counter() - started) * 1000.0


def train_one_batch(
    session: LoaderSession,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    device: torch.device,
) -> tuple[float, float, float]:
    overall_start = time.perf_counter()
    input_start = overall_start
    if session.pending is not None:
        images, labels = session.pending
        session.pending = None
    else:
        images, labels = next(session.iterator)
    input_end = time.perf_counter()
    images = images.to(device, non_blocking=True)
    labels = labels.to(device, non_blocking=True)
    optimizer.zero_grad(set_to_none=True)
    logits = model(images)
    loss = loss_fn(logits, labels)
    loss.backward()
    optimizer.step()
    torch.cuda.synchronize(device)
    gpu_end = time.perf_counter()
    return (
        (gpu_end - overall_start) * 1000.0,
        (input_end - input_start) * 1000.0,
        (gpu_end - input_end) * 1000.0,
    )


def run_segment(
    policy: str,
    phase: str,
    session: LoaderSession,
    count: int,
    global_batch: int,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    device: torch.device,
    trace: list[dict[str, object]],
) -> tuple[int, list[float]]:
    times: list[float] = []
    for _ in range(count):
        batch_ms, input_ms, gpu_ms = train_one_batch(
            session, model, optimizer, loss_fn, device
        )
        trace.append(
            {
                "policy": policy,
                "global_batch": global_batch,
                "phase": phase,
                "workers": session.workers,
                "batch_ms": batch_ms,
                "input_wait_ms": input_ms,
                "gpu_step_ms": gpu_ms,
            }
        )
        times.append(batch_ms)
        global_batch += 1
    return global_batch, times


def run_policy(
    policy: str,
    adaptive: bool,
    args: argparse.Namespace,
    device: torch.device,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    torch.manual_seed(17)
    model = SmallCudaCNN().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    loss_fn = nn.CrossEntropyLoss()
    trace: list[dict[str, object]] = []
    total_batches = args.normal_batches + args.contention_batches
    session = start_session(
        workers=args.initial_workers,
        total_batches=total_batches + args.warmup_batches,
        batch_size=args.batch_size,
        image_size=args.image_size,
        augmentation_rounds=args.augmentation_rounds,
    )
    startup_ms = session.startup_ms
    reconfiguration_ms = 0.0
    switched = False
    global_batch = 0

    # Warm CUDA and workers. These batches are charged to neither phase.
    _, _ = run_segment(
        policy,
        "warmup",
        session,
        args.warmup_batches,
        -args.warmup_batches,
        model,
        optimizer,
        loss_fn,
        device,
        [],
    )

    global_batch, normal_times = run_segment(
        policy,
        "normal",
        session,
        args.normal_batches,
        global_batch,
        model,
        optimizer,
        loss_fn,
        device,
        trace,
    )
    baseline_ms = statistics.median(normal_times[-args.baseline_window :])

    stop, stress_processes = start_contention(args.stress_processes)
    time.sleep(1.0)
    try:
        detection_count = min(args.detection_window, args.contention_batches)
        global_batch, detection_times = run_segment(
            policy,
            "contention_detect",
            session,
            detection_count,
            global_batch,
            model,
            optimizer,
            loss_fn,
            device,
            trace,
        )
        stressed_ms = statistics.median(detection_times)
        shift_ratio = stressed_ms / baseline_ms - 1.0
        remaining = args.contention_batches - detection_count

        if adaptive and shift_ratio >= args.change_threshold and remaining > 0:
            shutdown_ms = close_session(session)
            session = start_session(
                workers=args.candidate_workers,
                total_batches=remaining,
                batch_size=args.batch_size,
                image_size=args.image_size,
                augmentation_rounds=args.augmentation_rounds,
            )
            reconfiguration_ms += shutdown_ms + session.startup_ms
            probe_count = min(args.candidate_probe_batches, remaining)
            global_batch, candidate_times = run_segment(
                policy,
                "contention_probe",
                session,
                probe_count,
                global_batch,
                model,
                optimizer,
                loss_fn,
                device,
                trace,
            )
            remaining -= probe_count
            candidate_ms = statistics.median(candidate_times)
            per_batch_saving = stressed_ms - candidate_ms
            predicted_saving = max(0.0, per_batch_saving) * remaining
            if (
                candidate_ms <= stressed_ms * (1.0 - args.minimum_improvement)
                and predicted_saving >= reconfiguration_ms
            ):
                switched = True
            else:
                # A failed probe rolls back and charges the second switch too.
                shutdown_ms = close_session(session)
                session = start_session(
                    workers=args.initial_workers,
                    total_batches=remaining,
                    batch_size=args.batch_size,
                    image_size=args.image_size,
                    augmentation_rounds=args.augmentation_rounds,
                )
                reconfiguration_ms += shutdown_ms + session.startup_ms

        if remaining > 0:
            global_batch, _ = run_segment(
                policy,
                "contention_steady",
                session,
                remaining,
                global_batch,
                model,
                optimizer,
                loss_fn,
                device,
                trace,
            )
    finally:
        stop_contention(stop, stress_processes)
        final_shutdown_ms = close_session(session)

    charged_batch_ms = sum(float(row["batch_ms"]) for row in trace)
    total_ms = startup_ms + reconfiguration_ms + charged_batch_ms
    contention_rows = [row for row in trace if str(row["phase"]).startswith("contention")]
    summary = {
        "policy": policy,
        "normal_batches": args.normal_batches,
        "contention_batches": args.contention_batches,
        "initial_workers": args.initial_workers,
        "final_workers": int(contention_rows[-1]["workers"]),
        "switched": int(switched),
        "baseline_median_ms": baseline_ms,
        "detected_contention_median_ms": stressed_ms,
        "detected_shift_ratio": shift_ratio,
        "initial_startup_ms": startup_ms,
        "reconfiguration_ms": reconfiguration_ms,
        "final_shutdown_ms_not_charged": final_shutdown_ms,
        "mean_normal_batch_ms": statistics.fmean(normal_times),
        "mean_contention_batch_ms": statistics.fmean(
            float(row["batch_ms"]) for row in contention_rows
        ),
        "total_charged_runtime_s": total_ms / 1000.0,
    }
    return summary, trace


def write_outputs(
    summaries: list[dict[str, object]], trace: list[dict[str, object]]
) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "online_adaptation_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    with (OUT / "online_adaptation_trace.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trace[0]))
        writer.writeheader()
        writer.writerows(trace)

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    colors = {"fixed_8": "#E45756", "change_aware": "#4C78A8"}
    for policy in colors:
        rows = [row for row in trace if row["policy"] == policy]
        # Smooth only for readability; raw values stay in the CSV.
        window = 40
        batches = [int(row["global_batch"]) for row in rows]
        values = [float(row["batch_ms"]) for row in rows]
        smooth = [
            statistics.fmean(values[max(0, index - window + 1) : index + 1])
            for index in range(len(values))
        ]
        axes[0].plot(batches, smooth, color=colors[policy], label=policy)
        axes[1].step(
            batches,
            [int(row["workers"]) for row in rows],
            where="post",
            color=colors[policy],
            label=policy,
        )
    normal_batches = int(summaries[0]["normal_batches"])
    for axis in axes:
        axis.axvline(normal_batches, color="#555555", linestyle="--", linewidth=1)
        axis.grid(alpha=0.2)
        axis.legend()
    axes[0].set_ylabel("rolling mean batch time (ms)")
    axes[0].set_title("Continuous contention phase: fixed versus change-aware workers")
    axes[1].set_ylabel("DataLoader workers")
    axes[1].set_xlabel("training batch")
    fig.tight_layout()
    fig.savefig(OUT / "online_adaptation_trace.png", dpi=220)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-batches", type=int, default=300)
    parser.add_argument("--contention-batches", type=int, default=2_500)
    parser.add_argument("--warmup-batches", type=int, default=20)
    parser.add_argument("--baseline-window", type=int, default=100)
    parser.add_argument("--detection-window", type=int, default=60)
    parser.add_argument("--candidate-probe-batches", type=int, default=60)
    parser.add_argument("--change-threshold", type=float, default=0.25)
    parser.add_argument("--minimum-improvement", type=float, default=0.05)
    parser.add_argument("--initial-workers", type=int, default=8)
    parser.add_argument("--candidate-workers", type=int, default=6)
    parser.add_argument("--stress-processes", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--augmentation-rounds", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    mp.set_start_method("spawn", force=True)
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    summaries: list[dict[str, object]] = []
    trace: list[dict[str, object]] = []
    for policy, adaptive in (("fixed_8", False), ("change_aware", True)):
        print(f"running {policy}", flush=True)
        summary, policy_trace = run_policy(policy, adaptive, args, device)
        summaries.append(summary)
        trace.extend(policy_trace)
        print(summary, flush=True)
    write_outputs(summaries, trace)
    fixed = float(summaries[0]["total_charged_runtime_s"])
    adaptive = float(summaries[1]["total_charged_runtime_s"])
    print(
        f"total runtime improvement: {100.0 * (1.0 - adaptive / fixed):.2f}%",
        flush=True,
    )


if __name__ == "__main__":
    main()
