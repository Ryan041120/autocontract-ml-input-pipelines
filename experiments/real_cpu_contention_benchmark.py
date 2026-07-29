"""Real local benchmark for ML input-pipeline adaptation under CPU contention.

The benchmark uses PyTorch DataLoader workers to generate and augment synthetic
images on CPU while a small CNN trains on CUDA.  A second scenario starts
independent CPU/memory stress processes to emulate checkpointing, logging, or a
collocated job consuming accelerator-host resources.

This is a mechanism microbenchmark, not a reproduction of Cachew or Pecan.
It requires no downloaded dataset and writes its measurements to outputs/.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import psutil
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


@dataclass
class Measurement:
    scenario: str
    num_workers: int
    measured_batches: int
    batch_size: int
    mean_batch_ms: float
    p95_batch_ms: float
    mean_input_wait_ms: float
    p95_input_wait_ms: float
    mean_gpu_step_ms: float
    input_stall_ratio: float
    samples_per_s: float
    loader_startup_ms: float
    system_cpu_percent: float


class SyntheticAugmentationDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    """CPU-heavy deterministic image generation and augmentation."""

    def __init__(self, length: int, image_size: int, augmentation_rounds: int) -> None:
        self.length = length
        self.image_size = image_size
        self.augmentation_rounds = augmentation_rounds

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        size = self.image_size + 24
        rng = np.random.default_rng(index + 1729)
        image = rng.integers(0, 256, size=(3, size, size), dtype=np.uint8)
        work = image.astype(np.float32) / 255.0

        # Memory- and compute-heavy stand-in for decode, blur, color jitter,
        # normalization, and other online augmentations.
        for round_index in range(self.augmentation_rounds):
            work = (
                work
                + np.roll(work, 1, axis=1)
                + np.roll(work, -1, axis=1)
                + np.roll(work, 1, axis=2)
                + np.roll(work, -1, axis=2)
            ) * 0.2
            work = np.tanh(work * (1.05 + 0.01 * round_index))

        offset_y = (index * 7) % 24
        offset_x = (index * 11) % 24
        work = work[
            :,
            offset_y : offset_y + self.image_size,
            offset_x : offset_x + self.image_size,
        ]
        if index % 2:
            work = work[:, :, ::-1]
        work = np.ascontiguousarray((work - 0.45) / 0.25, dtype=np.float32)
        label = np.int64(index % 10)
        return torch.from_numpy(work), torch.tensor(label, dtype=torch.long)


class SmallCudaCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 24, 3, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(24, 48, 3, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.Conv2d(48, 64, 3, stride=2, padding=1),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = nn.Linear(64, 10)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(images).flatten(1))


def worker_init(worker_id: int) -> None:
    torch.set_num_threads(1)
    np.random.seed(9000 + worker_id)
    random.seed(9000 + worker_id)


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def build_loader(
    dataset: Dataset[tuple[torch.Tensor, torch.Tensor]],
    batch_size: int,
    num_workers: int,
) -> DataLoader:
    kwargs: dict[str, object] = {
        "dataset": dataset,
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": num_workers,
        "pin_memory": True,
        "drop_last": True,
        "worker_init_fn": worker_init,
        "persistent_workers": num_workers > 0,
    }
    if num_workers > 0:
        kwargs["prefetch_factor"] = 2
    return DataLoader(**kwargs)


def measure_configuration(
    scenario: str,
    num_workers: int,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    loss_fn: nn.Module,
    device: torch.device,
    batch_size: int,
    image_size: int,
    augmentation_rounds: int,
    warmup_batches: int,
    measured_batches: int,
) -> Measurement:
    total_batches = warmup_batches + measured_batches
    dataset = SyntheticAugmentationDataset(
        length=(total_batches + 3) * batch_size,
        image_size=image_size,
        augmentation_rounds=augmentation_rounds,
    )
    loader = build_loader(dataset, batch_size, num_workers)

    startup_start = time.perf_counter()
    iterator = iter(loader)
    first_images, first_labels = next(iterator)
    loader_startup_ms = (time.perf_counter() - startup_start) * 1000.0

    batch_times: list[float] = []
    input_waits: list[float] = []
    gpu_steps: list[float] = []
    psutil.cpu_percent(interval=None)

    def train_batch(images: torch.Tensor, labels: torch.Tensor) -> tuple[float, float]:
        batch_start = time.perf_counter()
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        logits = model(images)
        loss = loss_fn(logits, labels)
        loss.backward()
        optimizer.step()
        torch.cuda.synchronize(device)
        return batch_start, time.perf_counter()

    # Consume the batch used to start persistent workers.
    train_batch(first_images, first_labels)

    for batch_index in range(total_batches - 1):
        overall_start = time.perf_counter()
        input_start = overall_start
        images, labels = next(iterator)
        input_end = time.perf_counter()
        gpu_start, gpu_end = train_batch(images, labels)
        overall_end = gpu_end

        if batch_index >= warmup_batches - 1:
            input_waits.append((input_end - input_start) * 1000.0)
            gpu_steps.append((gpu_end - gpu_start) * 1000.0)
            batch_times.append((overall_end - overall_start) * 1000.0)

    mean_batch = statistics.fmean(batch_times)
    mean_input = statistics.fmean(input_waits)
    cpu_percent = psutil.cpu_percent(interval=None)
    # Explicit deletion shuts down persistent DataLoader workers before the
    # next configuration starts.
    del iterator, loader
    return Measurement(
        scenario=scenario,
        num_workers=num_workers,
        measured_batches=len(batch_times),
        batch_size=batch_size,
        mean_batch_ms=mean_batch,
        p95_batch_ms=percentile(batch_times, 0.95),
        mean_input_wait_ms=mean_input,
        p95_input_wait_ms=percentile(input_waits, 0.95),
        mean_gpu_step_ms=statistics.fmean(gpu_steps),
        input_stall_ratio=mean_input / mean_batch,
        samples_per_s=batch_size * 1000.0 / mean_batch,
        loader_startup_ms=loader_startup_ms,
        system_cpu_percent=cpu_percent,
    )


def start_contention(process_count: int) -> tuple[None, list[subprocess.Popen[bytes]]]:
    """Start stressors without importing the CUDA-enabled torch package in them."""

    script = Path(__file__).with_name("contention_stressor.py")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    environment = os.environ.copy()
    environment["OMP_NUM_THREADS"] = "1"
    environment["MKL_NUM_THREADS"] = "1"
    processes = [
        subprocess.Popen(
            [sys.executable, str(script), "--seed", str(4100 + index)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            env=environment,
        )
        for index in range(process_count)
    ]
    for process in processes:
        if process.poll() is not None:
            raise RuntimeError("contention stress process exited during startup")
    return None, processes


def stop_contention(
    stop: None, processes: list[subprocess.Popen[bytes]]
) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def write_results(measurements: list[Measurement], output_tag: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f"_{output_tag}" if output_tag else ""
    csv_path = OUT / f"real_cpu_contention_profiles{suffix}.csv"
    rows = [asdict(measurement) for measurement in measurements]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    scenarios = sorted({measurement.scenario for measurement in measurements})
    best = {
        scenario: min(
            (item for item in measurements if item.scenario == scenario),
            key=lambda item: item.mean_batch_ms,
        )
        for scenario in scenarios
    }
    initial = best["normal"]
    stressed_rows = {
        item.num_workers: item
        for item in measurements
        if item.scenario == "cpu_memory_contention"
    }
    fixed_stressed = stressed_rows[initial.num_workers]
    adaptive_stressed = best["cpu_memory_contention"]
    phase_batches = 5_000
    fixed_total_ms = phase_batches * (
        initial.mean_batch_ms + fixed_stressed.mean_batch_ms
    )
    adaptive_total_ms = (
        phase_batches * (initial.mean_batch_ms + adaptive_stressed.mean_batch_ms)
        + adaptive_stressed.loader_startup_ms
    )
    replay_rows = [
        {
            "policy": "fixed_normal_optimum",
            "normal_workers": initial.num_workers,
            "contention_workers": initial.num_workers,
            "assumed_batches_per_phase": phase_batches,
            "reconfiguration_ms": 0.0,
            "total_runtime_s": fixed_total_ms / 1000.0,
            "improvement_vs_fixed": 0.0,
        },
        {
            "policy": "phase_aware_oracle_with_startup_cost",
            "normal_workers": initial.num_workers,
            "contention_workers": adaptive_stressed.num_workers,
            "assumed_batches_per_phase": phase_batches,
            "reconfiguration_ms": adaptive_stressed.loader_startup_ms,
            "total_runtime_s": adaptive_total_ms / 1000.0,
            "improvement_vs_fixed": 1.0 - adaptive_total_ms / fixed_total_ms,
        },
    ]
    with (OUT / f"real_cpu_contention_replay{suffix}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(replay_rows[0]))
        writer.writeheader()
        writer.writerows(replay_rows)

    saving_ms = fixed_stressed.mean_batch_ms - adaptive_stressed.mean_batch_ms
    if saving_ms > 0:
        break_even_batches = adaptive_stressed.loader_startup_ms / saving_ms
        break_even_samples = break_even_batches * adaptive_stressed.batch_size
        fixed_time_to_break_even_s = (
            break_even_batches * fixed_stressed.mean_batch_ms / 1000.0
        )
    else:
        break_even_batches = float("inf")
        break_even_samples = float("inf")
        fixed_time_to_break_even_s = float("inf")
    break_even_row = {
        "normal_best_workers": initial.num_workers,
        "contention_best_workers": adaptive_stressed.num_workers,
        "fixed_contention_batch_ms": fixed_stressed.mean_batch_ms,
        "adaptive_contention_batch_ms": adaptive_stressed.mean_batch_ms,
        "per_batch_saving_ms": saving_ms,
        "reconfiguration_startup_ms": adaptive_stressed.loader_startup_ms,
        "break_even_batches": break_even_batches,
        "break_even_samples": break_even_samples,
        "fixed_time_to_break_even_s": fixed_time_to_break_even_s,
    }
    with (OUT / f"real_cpu_contention_break_even{suffix}.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(break_even_row))
        writer.writeheader()
        writer.writerow(break_even_row)

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    colors = {"normal": "#4C78A8", "cpu_memory_contention": "#E45756"}
    for scenario in scenarios:
        selected = sorted(
            (item for item in measurements if item.scenario == scenario),
            key=lambda item: item.num_workers,
        )
        axes[0].plot(
            [item.num_workers for item in selected],
            [item.mean_batch_ms for item in selected],
            marker="o",
            label=scenario,
            color=colors[scenario],
        )
        axes[1].plot(
            [item.num_workers for item in selected],
            [100.0 * item.input_stall_ratio for item in selected],
            marker="o",
            label=scenario,
            color=colors[scenario],
        )
    axes[0].set_xlabel("PyTorch DataLoader workers")
    axes[0].set_ylabel("mean end-to-end batch time (ms)")
    axes[0].set_title("Worker-count optimum can move under contention")
    axes[1].set_xlabel("PyTorch DataLoader workers")
    axes[1].set_ylabel("input wait / batch time (%)")
    axes[1].set_title("Observed input-stall ratio")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend()
    fig.tight_layout()
    fig.savefig(OUT / f"real_cpu_contention_profiles{suffix}.png", dpi=220)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--stress-processes", type=int, default=4)
    parser.add_argument("--image-size", type=int, default=128)
    parser.add_argument("--augmentation-rounds", type=int, default=2)
    parser.add_argument(
        "--workers",
        help="optional comma-separated worker counts overriding the selected mode",
    )
    parser.add_argument("--warmup-batches", type=int)
    parser.add_argument("--measured-batches", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--output-tag", default="")
    parser.add_argument(
        "--analyze-existing",
        type=Path,
        help="regenerate replay, break-even analysis, and plot from an existing profile CSV",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.analyze_existing is not None:
        measurements: list[Measurement] = []
        with args.analyze_existing.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                measurements.append(
                    Measurement(
                        scenario=row["scenario"],
                        num_workers=int(row["num_workers"]),
                        measured_batches=int(row["measured_batches"]),
                        batch_size=int(row["batch_size"]),
                        mean_batch_ms=float(row["mean_batch_ms"]),
                        p95_batch_ms=float(row["p95_batch_ms"]),
                        mean_input_wait_ms=float(row["mean_input_wait_ms"]),
                        p95_input_wait_ms=float(row["p95_input_wait_ms"]),
                        mean_gpu_step_ms=float(row["mean_gpu_step_ms"]),
                        input_stall_ratio=float(row["input_stall_ratio"]),
                        samples_per_s=float(row["samples_per_s"]),
                        loader_startup_ms=float(row["loader_startup_ms"]),
                        system_cpu_percent=float(row["system_cpu_percent"]),
                    )
                )
        write_results(measurements, args.output_tag)
        print(f"analyzed {args.analyze_existing}", flush=True)
        return
    if not torch.cuda.is_available():
        raise RuntimeError("This benchmark requires a CUDA-capable PyTorch runtime")

    mp.set_start_method("spawn", force=True)
    torch.manual_seed(7)
    np.random.seed(7)
    torch.set_num_threads(1)
    device = torch.device("cuda:0")
    model = SmallCudaCNN().to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
    loss_fn = nn.CrossEntropyLoss()

    if args.mode == "quick":
        worker_counts = [0, 2, 4, 6]
        warmup_batches = 4
        measured_batches = 12
        batch_size = 24
    else:
        # A fixed shuffled order reduces the chance that process startup,
        # thermal drift, or CUDA warm-up is mistaken for a worker-count trend.
        worker_counts = [4, 0, 6, 2, 8, 1, 3]
        warmup_batches = 6
        measured_batches = 20
        batch_size = 24
    if args.workers:
        worker_counts = [int(value) for value in args.workers.split(",")]
    if args.warmup_batches is not None:
        warmup_batches = args.warmup_batches
    if args.measured_batches is not None:
        measured_batches = args.measured_batches
    if args.batch_size is not None:
        batch_size = args.batch_size

    measurements: list[Measurement] = []
    print(
        f"device={torch.cuda.get_device_name(0)!r}, mode={args.mode}, "
        f"workers={worker_counts}, stress_processes={args.stress_processes}",
        flush=True,
    )

    for scenario in ("normal", "cpu_memory_contention"):
        stop: None = None
        stress_processes: list[subprocess.Popen[bytes]] = []
        if scenario == "cpu_memory_contention":
            stop, stress_processes = start_contention(args.stress_processes)
            time.sleep(1.0)
        try:
            for workers in worker_counts:
                measurement = measure_configuration(
                    scenario=scenario,
                    num_workers=workers,
                    model=model,
                    optimizer=optimizer,
                    loss_fn=loss_fn,
                    device=device,
                    batch_size=batch_size,
                    image_size=args.image_size,
                    augmentation_rounds=args.augmentation_rounds,
                    warmup_batches=warmup_batches,
                    measured_batches=measured_batches,
                )
                measurements.append(measurement)
                print(
                    f"{scenario:22s} workers={workers:2d} "
                    f"batch={measurement.mean_batch_ms:7.2f} ms "
                    f"input={measurement.mean_input_wait_ms:7.2f} ms "
                    f"stall={measurement.input_stall_ratio:6.1%} "
                    f"throughput={measurement.samples_per_s:7.1f}/s",
                    flush=True,
                )
        finally:
            if stress_processes:
                stop_contention(stop, stress_processes)

    write_results(measurements, args.output_tag)
    suffix = f"_{args.output_tag}" if args.output_tag else ""
    print(f"wrote {OUT / f'real_cpu_contention_profiles{suffix}.csv'}", flush=True)


if __name__ == "__main__":
    main()
