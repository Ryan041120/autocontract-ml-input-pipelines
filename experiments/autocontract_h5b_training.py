"""H5b pilot: train a real model through uncached and contract-safe plans.

This experiment reuses the JPEG/DataLoader and stateless augmentation path from
the H5a benchmark.  It measures ResNet-18 forward/backward/optimizer steps and
tests whether a horizon-aware admission rule makes the correct choice for a
cold one-run cache and a reusable warm cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from torch import Tensor, nn
from torch.optim import SGD
from torch.utils.data import DataLoader
from torchvision.models import resnet18

from autocontract_h5_jpeg_dataloader import (
    OUT,
    PREFIX_SHAPE,
    PipelineDataset,
    configure_worker,
    imagefolder_manifest,
    prepare_jpeg_tree,
)


ROOT = Path(__file__).resolve().parents[1]
TRAIN_SEED = 20260728
Policy = Literal["uncached", "cached"]


def seed_training() -> None:
    np.random.seed(TRAIN_SEED)
    torch.manual_seed(TRAIN_SEED)
    torch.cuda.manual_seed_all(TRAIN_SEED)


class NvidiaSmiSampler:
    """Best-effort end-to-end GPU utilization and memory sampler."""

    def __init__(self, interval_ms: int = 200) -> None:
        self.interval_ms = interval_ms
        self.samples: list[tuple[float, float]] = []
        self.process: subprocess.Popen[str] | None = None
        self.thread: threading.Thread | None = None

    def _read(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            try:
                utilization, memory = (float(part.strip()) for part in line.split(",")[:2])
                self.samples.append((utilization, memory))
            except (ValueError, IndexError):
                continue

    def start(self) -> None:
        command = [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used",
            "--format=csv,noheader,nounits",
            f"--loop-ms={self.interval_ms}",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creationflags,
            )
        except OSError:
            self.process = None
            return
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def stop(self) -> tuple[float, float, float, int]:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            if self.thread is not None:
                self.thread.join(timeout=2)
        if not self.samples:
            return float("nan"), float("nan"), float("nan"), 0
        utilization = np.asarray([sample[0] for sample in self.samples])
        memory = np.asarray([sample[1] for sample in self.samples])
        return (
            float(utilization.mean()),
            float(np.quantile(utilization, 0.95)),
            float(memory.max()),
            len(self.samples),
        )


def batch_digest(values: Tensor, labels: Tensor) -> str:
    digest = hashlib.blake2b(digest_size=12)
    digest.update(values.detach().contiguous().cpu().numpy().tobytes())
    digest.update(labels.detach().contiguous().cpu().numpy().tobytes())
    return digest.hexdigest()


def model_digest(model: nn.Module) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for name, value in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(value.detach().contiguous().cpu().numpy().tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class TrainingRun:
    policy: Policy
    runtime_s: float
    first_batch_ready_s: float
    data_wait_s: float
    compute_s: float
    data_wait_fraction: float
    samples_per_s: float
    median_step_s: float
    p95_step_s: float
    mean_loss: float
    final_loss: float
    accuracy: float
    gpu_util_mean: float
    gpu_util_p95: float
    gpu_memory_peak_mb: float
    gpu_samples: int
    batch_digests: tuple[str, ...]
    losses: tuple[float, ...]
    final_model_digest: str


def make_loader(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    policy: Policy,
    epochs: int,
    batch_size: int,
    workers: int,
) -> DataLoader:
    dataset = PipelineDataset(manifest, epochs, policy, cache_path)
    options: dict[str, object] = {
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": workers,
        "pin_memory": True,
        "worker_init_fn": configure_worker if workers else None,
    }
    if workers:
        options["prefetch_factor"] = 2
    return DataLoader(dataset, **options)


def build_model(num_classes: int) -> nn.Module:
    seed_training()
    model = resnet18(weights=None, num_classes=num_classes).cuda()
    return model


def warm_cuda(num_classes: int, batch_size: int) -> None:
    model = build_model(num_classes)
    optimizer = SGD(model.parameters(), lr=0.01, momentum=0.9)
    values = torch.zeros((batch_size, 3, 88, 92), device="cuda")
    labels = torch.zeros(batch_size, dtype=torch.long, device="cuda")
    optimizer.zero_grad(set_to_none=True)
    loss = nn.functional.cross_entropy(model(values), labels)
    loss.backward()
    optimizer.step()
    torch.cuda.synchronize()
    del model, optimizer, values, labels, loss
    torch.cuda.empty_cache()


def train_once(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    policy: Policy,
    epochs: int,
    batch_size: int,
    workers: int,
) -> TrainingRun:
    loader = make_loader(manifest, cache_path, policy, epochs, batch_size, workers)
    model = build_model(num_classes=7)
    optimizer = SGD(model.parameters(), lr=0.01, momentum=0.9, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    mean = torch.tensor((0.485, 0.456, 0.406), device="cuda").view(1, 3, 1, 1)
    std = torch.tensor((0.229, 0.224, 0.225), device="cuda").view(1, 3, 1, 1)

    losses: list[float] = []
    step_times: list[float] = []
    digests: list[str] = []
    correct = 0
    total = 0
    data_wait_s = 0.0
    compute_s = 0.0
    first_batch_ready_s = 0.0
    sampler = NvidiaSmiSampler()
    sampler.start()
    started = time.perf_counter()
    iterator = iter(loader)
    batch_index = 0
    while True:
        wait_started = time.perf_counter()
        try:
            values, labels, _, _ = next(iterator)
        except StopIteration:
            break
        waited = time.perf_counter() - wait_started
        data_wait_s += waited
        if batch_index == 0:
            first_batch_ready_s = time.perf_counter() - started
        digests.append(batch_digest(values, labels))

        compute_started = time.perf_counter()
        device_values = values.cuda(non_blocking=True).float().div_(255.0)
        device_values = (device_values - mean) / std
        device_labels = labels.cuda(non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        logits = model(device_values)
        loss = criterion(logits, device_labels)
        loss.backward()
        optimizer.step()
        torch.cuda.synchronize()
        computed = time.perf_counter() - compute_started
        compute_s += computed
        step_times.append(waited + computed)
        losses.append(float(loss.detach().cpu()))
        correct += int((logits.argmax(dim=1) == device_labels).sum())
        total += len(labels)
        batch_index += 1

    runtime = time.perf_counter() - started
    gpu_mean, gpu_p95, memory_peak, gpu_samples = sampler.stop()
    digest = model_digest(model)
    del model, optimizer, criterion, mean, std
    torch.cuda.empty_cache()
    return TrainingRun(
        policy=policy,
        runtime_s=runtime,
        first_batch_ready_s=first_batch_ready_s,
        data_wait_s=data_wait_s,
        compute_s=compute_s,
        data_wait_fraction=data_wait_s / runtime,
        samples_per_s=total / runtime,
        median_step_s=statistics.median(step_times),
        p95_step_s=float(np.quantile(step_times, 0.95)),
        mean_loss=statistics.mean(losses),
        final_loss=losses[-1],
        accuracy=correct / total,
        gpu_util_mean=gpu_mean,
        gpu_util_p95=gpu_p95,
        gpu_memory_peak_mb=memory_peak,
        gpu_samples=gpu_samples,
        batch_digests=tuple(digests),
        losses=tuple(losses),
        final_model_digest=digest,
    )


@dataclass(frozen=True)
class TrainingSummary:
    policy: Policy
    median_runtime_s: float
    q1_runtime_s: float
    q3_runtime_s: float
    median_first_batch_ready_s: float
    median_data_wait_s: float
    median_compute_s: float
    median_data_wait_fraction: float
    median_samples_per_s: float
    median_step_s: float
    median_p95_step_s: float
    median_gpu_util_mean: float
    median_gpu_util_p95: float
    gpu_memory_peak_mb: float
    representative: TrainingRun


def summarize(policy: Policy, runs: list[TrainingRun]) -> TrainingSummary:
    runtimes = [run.runtime_s for run in runs]
    median_runtime = statistics.median(runtimes)
    representative = min(runs, key=lambda run: abs(run.runtime_s - median_runtime))
    return TrainingSummary(
        policy=policy,
        median_runtime_s=median_runtime,
        q1_runtime_s=float(np.quantile(runtimes, 0.25)),
        q3_runtime_s=float(np.quantile(runtimes, 0.75)),
        median_first_batch_ready_s=statistics.median(run.first_batch_ready_s for run in runs),
        median_data_wait_s=statistics.median(run.data_wait_s for run in runs),
        median_compute_s=statistics.median(run.compute_s for run in runs),
        median_data_wait_fraction=statistics.median(run.data_wait_fraction for run in runs),
        median_samples_per_s=statistics.median(run.samples_per_s for run in runs),
        median_step_s=statistics.median(run.median_step_s for run in runs),
        median_p95_step_s=statistics.median(run.p95_step_s for run in runs),
        median_gpu_util_mean=statistics.median(run.gpu_util_mean for run in runs),
        median_gpu_util_p95=statistics.median(run.gpu_util_p95 for run in runs),
        gpu_memory_peak_mb=max(run.gpu_memory_peak_mb for run in runs),
        representative=representative,
    )


def paired_training(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    epochs: int,
    batch_size: int,
    workers: int,
    repeats: int,
) -> tuple[TrainingSummary, TrainingSummary]:
    collected: dict[Policy, list[TrainingRun]] = {"uncached": [], "cached": []}
    for repeat in range(repeats):
        order: tuple[Policy, Policy] = (
            ("uncached", "cached") if repeat % 2 == 0 else ("cached", "uncached")
        )
        for policy in order:
            collected[policy].append(
                train_once(manifest, cache_path, policy, epochs, batch_size, workers)
            )
    return summarize("uncached", collected["uncached"]), summarize("cached", collected["cached"])


def read_h5a_profile(workers: int) -> dict[str, str]:
    with (OUT / "autocontract_h5_jpeg_workers.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if int(row["workers"]) == workers:
            return row
    raise RuntimeError(f"No H5a profile for workers={workers}")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "autocontract_h5",
    )
    parser.add_argument("--samples", type=int, default=600)
    parser.add_argument("--export-size", type=int, default=224)
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("H5b requires CUDA for the training-path experiment")
    torch.set_num_threads(1)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    OUT.mkdir(exist_ok=True)

    jpeg_root, _, _, _ = prepare_jpeg_tree(
        args.data_root, args.samples, args.export_size, args.jpeg_quality
    )
    manifest = imagefolder_manifest(jpeg_root, args.samples)
    cache_path = args.data_root / (
        f"skimage_prefix_n{args.samples}_s{args.export_size}_{PREFIX_SHAPE[1]}x{PREFIX_SHAPE[2]}.uint8.memmap"
    )
    if not cache_path.exists():
        raise FileNotFoundError("Run the H5a cache benchmark before H5b")

    h5a = read_h5a_profile(args.workers)
    build_time = float(h5a["cache_build_time_s"])
    predicted_break_even = float(h5a["conservative_break_even_epochs"])
    cold_accept = args.epochs >= predicted_break_even
    warm_accept = float(h5a["steady_speedup"]) > 1.0

    warm_cuda(num_classes=7, batch_size=min(args.batch_size, 16))
    uncached, cached = paired_training(
        manifest,
        cache_path,
        args.epochs,
        args.batch_size,
        args.workers,
        args.repeats,
    )

    left = uncached.representative
    right = cached.representative
    batch_trace_equal = left.batch_digests == right.batch_digests
    losses_left = np.asarray(left.losses)
    losses_right = np.asarray(right.losses)
    max_loss_difference = float(np.max(np.abs(losses_left - losses_right)))
    loss_trace_equal = bool(np.allclose(losses_left, losses_right, rtol=1e-6, atol=1e-7))
    model_equal = left.final_model_digest == right.final_model_digest

    warm_speedup = uncached.median_runtime_s / cached.median_runtime_s
    naive_cold_runtime = build_time + cached.median_runtime_s
    cold_optimal_is_cache = naive_cold_runtime < uncached.median_runtime_s
    cold_decision_correct = cold_accept == cold_optimal_is_cache
    warm_optimal_is_cache = cached.median_runtime_s < uncached.median_runtime_s
    warm_decision_correct = warm_accept == warm_optimal_is_cache
    semantics_pass = batch_trace_equal and loss_trace_equal and model_equal
    performance_pass = warm_speedup >= 1.20
    admission_pass = cold_decision_correct and warm_decision_correct
    h5b_pass = semantics_pass and performance_pass and admission_pass

    summaries = [uncached, cached]
    rows: list[dict[str, object]] = []
    for summary in summaries:
        run = summary.representative
        rows.append(
            {
                "policy": summary.policy,
                "median_runtime_s": summary.median_runtime_s,
                "runtime_q1_s": summary.q1_runtime_s,
                "runtime_q3_s": summary.q3_runtime_s,
                "first_batch_ready_s": summary.median_first_batch_ready_s,
                "data_wait_s": summary.median_data_wait_s,
                "compute_s": summary.median_compute_s,
                "data_wait_fraction": summary.median_data_wait_fraction,
                "samples_per_s": summary.median_samples_per_s,
                "median_step_s": summary.median_step_s,
                "p95_step_s": summary.median_p95_step_s,
                "gpu_util_mean_percent": summary.median_gpu_util_mean,
                "gpu_util_p95_percent": summary.median_gpu_util_p95,
                "gpu_memory_peak_mb": summary.gpu_memory_peak_mb,
                "mean_loss": run.mean_loss,
                "final_loss": run.final_loss,
                "accuracy": run.accuracy,
                "final_model_digest": run.final_model_digest,
            }
        )
    write_csv(OUT / "autocontract_h5b_training.csv", rows)
    decisions = {
        "workers": args.workers,
        "epochs": args.epochs,
        "cache_build_time_s": build_time,
        "profile_predicted_break_even_epochs": predicted_break_even,
        "cold_horizon_accept_cache": cold_accept,
        "cold_measured_optimal_is_cache": cold_optimal_is_cache,
        "cold_decision_correct": cold_decision_correct,
        "warm_horizon_accept_cache": warm_accept,
        "warm_measured_optimal_is_cache": warm_optimal_is_cache,
        "warm_decision_correct": warm_decision_correct,
        "warm_training_speedup": warm_speedup,
        "batch_trace_equal": batch_trace_equal,
        "loss_trace_equal": loss_trace_equal,
        "max_loss_difference": max_loss_difference,
        "final_model_equal": model_equal,
        "h5b_pass": h5b_pass,
    }
    (OUT / "autocontract_h5b_decisions.json").write_text(
        json.dumps(decisions, indent=2), encoding="utf-8"
    )

    lines = [
        "# AutoContract H5b: real ResNet-18 training-path pilot",
        "",
        f"Samples: {args.samples}; epochs: {args.epochs}; batch size: {args.batch_size}; "
        f"workers: {args.workers}; paired repeats: {args.repeats}; device: CUDA.",
        "Each run creates the same ResNet-18 initialization and executes forward, backward, and SGD step.",
        "",
        "| Policy | Runtime median [Q1,Q3] | First batch | Data wait | Compute | Samples/s | Median / p95 step | GPU util mean / p95 | Final loss | Accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['policy']} | {row['median_runtime_s']:.2f} "
            f"[{row['runtime_q1_s']:.2f},{row['runtime_q3_s']:.2f}]s | "
            f"{row['first_batch_ready_s']:.2f}s | {row['data_wait_s']:.2f}s "
            f"({row['data_wait_fraction']:.1%}) | {row['compute_s']:.2f}s | "
            f"{row['samples_per_s']:.1f} | {row['median_step_s']:.3f}/"
            f"{row['p95_step_s']:.3f}s | {row['gpu_util_mean_percent']:.1f}%/"
            f"{row['gpu_util_p95_percent']:.1f}% | {row['final_loss']:.5f} | "
            f"{row['accuracy']:.3f} |"
        )

    lines.extend(
        (
            "",
            "## Semantic equivalence",
            "",
            f"- Batch trace identical: **{batch_trace_equal}**.",
            f"- Loss trace allclose: **{loss_trace_equal}**; maximum difference {max_loss_difference:.3e}.",
            f"- Final model digest identical: **{model_equal}**.",
            "",
            "## Horizon-aware admission",
            "",
            f"- Warm-cache training speedup: {warm_speedup:.2f}×.",
            f"- H5a predicted cold break-even: {predicted_break_even:.2f} epochs; requested horizon: {args.epochs}.",
            f"- Cold cache: rule says {'ACCEPT' if cold_accept else 'REJECT'}; measured optimum is "
            f"{'CACHE' if cold_optimal_is_cache else 'NO CACHE'}; correct={cold_decision_correct}.",
            f"- Reusable warm cache: rule says {'ACCEPT' if warm_accept else 'REJECT'}; measured optimum is "
            f"{'CACHE' if warm_optimal_is_cache else 'NO CACHE'}; correct={warm_decision_correct}.",
            f"- Naive cold-cache total: {naive_cold_runtime:.2f}s versus uncached {uncached.median_runtime_s:.2f}s.",
            "",
            "## Gate verdict",
            "",
            f"- Semantic trace/model gate: **{'PASS' if semantics_pass else 'FAIL'}**.",
            f"- Warm training speedup >=1.20×: **{'PASS' if performance_pass else 'FAIL'}**.",
            f"- Cold/warm admission decisions both correct: **{'PASS' if admission_pass else 'FAIL'}**.",
            f"- H5b pilot: **{'PASS' if h5b_pass else 'FAIL'}**.",
            "",
            "This is a real training execution but not a model-quality claim: the dataset contains "
            "deterministic crops from seven source photographs and is intended only to stress the systems path.",
            "",
        )
    )
    report = "\n".join(lines)
    (OUT / "autocontract_h5b_training.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
