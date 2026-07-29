"""H5a benchmark: safe prefix caching in a real JPEG/DataLoader path.

The script creates an ImageFolder-compatible JPEG tree from real photographs
bundled with scikit-image, then compares these semantically identical pipelines:

    uncached: JPEG read/decode -> deterministic prefix -> stateless suffix
    cached:   uint8 memmap prefix cache          -> stateless suffix

The suffix is addressed by (epoch, sample_id, stable_operator_id), so worker
scheduling and cache hits cannot change its decisions.  Cache construction is
reported separately and used to estimate a conservative offline break-even.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import torch
from PIL import Image
from torch import Tensor
from torch.utils.data import DataLoader, Dataset
from torchvision.datasets import ImageFolder
from torchvision.io import ImageReadMode, read_image

from autocontract_stateless_benchmark import stateless_prefix, stateless_suffix


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
DATA_SEED = 20260727
PREFIX_SHAPE = (3, 96, 104)
Policy = Literal["uncached", "cached"]


def configure_worker(_: int) -> None:
    torch.set_num_threads(1)


def prepare_jpeg_tree(
    data_root: Path,
    sample_count: int,
    export_size: int,
    jpeg_quality: int,
) -> tuple[Path, float, bool, list[str]]:
    """Export deterministic crops of bundled real photographs as JPEG files."""

    source_names = [
        "astronaut",
        "camera",
        "chelsea",
        "coffee",
        "rocket",
        "hubble_deep_field",
        "immunohistochemistry",
    ]
    jpeg_root = data_root / f"skimage_jpeg_n{sample_count}_s{export_size}_q{jpeg_quality}"
    marker = jpeg_root / "_READY.json"
    if marker.exists():
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        if (
            metadata.get("sample_count") == sample_count
            and metadata.get("export_size") == export_size
            and metadata.get("jpeg_quality") == jpeg_quality
        ):
            return jpeg_root, 0.0, False, source_names

    started = time.perf_counter()
    from skimage import data as skimage_data

    sources: list[np.ndarray] = []
    for name in source_names:
        array = np.asarray(getattr(skimage_data, name)())
        if array.ndim == 2:
            array = np.repeat(array[:, :, None], 3, axis=2)
        if array.shape[2] == 4:
            array = array[:, :, :3]
        sources.append(array.astype(np.uint8, copy=False))
    jpeg_root.mkdir(parents=True, exist_ok=True)
    resampling = getattr(Image, "Resampling", Image).BICUBIC
    for sample_id in range(sample_count):
        source_id = sample_id % len(sources)
        array = sources[source_id]
        height, width = array.shape[:2]
        rng = np.random.default_rng(DATA_SEED + sample_id)
        crop_size = int(min(height, width) * rng.uniform(0.55, 1.0))
        top = int(rng.integers(0, height - crop_size + 1))
        left = int(rng.integers(0, width - crop_size + 1))
        cropped = array[top : top + crop_size, left : left + crop_size]
        image = Image.fromarray(cropped, mode="RGB")
        class_dir = jpeg_root / f"class_{source_id:02d}"
        class_dir.mkdir(exist_ok=True)
        destination = class_dir / f"sample_{sample_id:06d}.jpg"
        if not destination.exists():
            image.resize((export_size, export_size), resampling).save(
                destination,
                format="JPEG",
                quality=jpeg_quality,
                optimize=False,
            )
    metadata = {
        "source": "scikit-image bundled real photographs",
        "source_images": source_names,
        "sample_count": sample_count,
        "export_size": export_size,
        "jpeg_quality": jpeg_quality,
    }
    marker.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return jpeg_root, time.perf_counter() - started, True, source_names


def imagefolder_manifest(jpeg_root: Path, sample_count: int) -> list[tuple[str, int]]:
    folder = ImageFolder(str(jpeg_root))
    # Filenames retain the original sample ID, but ImageFolder sorts by class.
    by_id: dict[int, tuple[str, int]] = {}
    for path, label in folder.samples:
        sample_id = int(Path(path).stem.split("_")[-1])
        by_id[sample_id] = (path, label)
    if len(by_id) != sample_count:
        raise RuntimeError(f"Expected {sample_count} JPEG files, found {len(by_id)}")
    return [by_id[sample_id] for sample_id in range(sample_count)]


class PrefixDataset(Dataset[tuple[int, Tensor]]):
    def __init__(self, manifest: list[tuple[str, int]]) -> None:
        self.manifest = manifest

    def __len__(self) -> int:
        return len(self.manifest)

    def __getitem__(self, sample_id: int) -> tuple[int, Tensor]:
        image = read_image(self.manifest[sample_id][0], mode=ImageReadMode.RGB)
        return sample_id, stateless_prefix(image)


def build_prefix_cache(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    batch_size: int,
    workers: int,
) -> float:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = np.memmap(
        cache_path,
        dtype=np.uint8,
        mode="w+",
        shape=(len(manifest), *PREFIX_SHAPE),
    )
    dataset = PrefixDataset(manifest)
    loader_options: dict[str, object] = {
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": workers,
        "worker_init_fn": configure_worker if workers else None,
    }
    if workers:
        loader_options["prefetch_factor"] = 2
    loader = DataLoader(dataset, **loader_options)
    started = time.perf_counter()
    with torch.inference_mode():
        for sample_ids, values in loader:
            cache[sample_ids.numpy()] = values.numpy()
    cache.flush()
    elapsed = time.perf_counter() - started
    del cache
    metadata = {
        "sample_count": len(manifest),
        "shape": [len(manifest), *PREFIX_SHAPE],
        "dtype": "uint8",
        "build_time_s": elapsed,
        "workers": workers,
    }
    cache_path.with_suffix(".json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return elapsed


def epoch_sample_order(sample_count: int, epochs: int) -> list[tuple[int, int]]:
    order: list[tuple[int, int]] = []
    for epoch in range(epochs):
        rng = np.random.default_rng(DATA_SEED + epoch)
        order.extend((epoch, int(sample_id)) for sample_id in rng.permutation(sample_count))
    return order


class PipelineDataset(Dataset[tuple[Tensor, int, int, int]]):
    def __init__(
        self,
        manifest: list[tuple[str, int]],
        epochs: int,
        policy: Policy,
        cache_path: Path,
    ) -> None:
        self.manifest = manifest
        self.order = epoch_sample_order(len(manifest), epochs)
        self.policy = policy
        self.cache_path = cache_path
        self._cache: np.memmap | None = None

    def __getstate__(self) -> dict[str, object]:
        state = self.__dict__.copy()
        state["_cache"] = None
        return state

    def __len__(self) -> int:
        return len(self.order)

    def _cached_prefix(self, sample_id: int) -> Tensor:
        if self._cache is None:
            self._cache = np.memmap(
                self.cache_path,
                dtype=np.uint8,
                mode="r",
                shape=(len(self.manifest), *PREFIX_SHAPE),
            )
        # Copy into writable memory before random functional transforms.
        return torch.from_numpy(np.array(self._cache[sample_id], copy=True))

    def __getitem__(self, index: int) -> tuple[Tensor, int, int, int]:
        epoch, sample_id = self.order[index]
        path, label = self.manifest[sample_id]
        if self.policy == "cached":
            value = self._cached_prefix(sample_id)
        else:
            value = stateless_prefix(read_image(path, mode=ImageReadMode.RGB))
        output = stateless_suffix(value, epoch, sample_id)
        return output, label, epoch, sample_id


@dataclass(frozen=True)
class Execution:
    runtime_s: float
    samples_per_s: float
    input_wait_fraction: float
    first_batch_latency_s: float
    steady_samples_per_s: float
    steady_input_wait_fraction: float
    trace: dict[tuple[int, int], str]
    checksum: float


@dataclass(frozen=True)
class PolicySummary:
    policy: Policy
    workers: int
    median_runtime_s: float
    q1_runtime_s: float
    q3_runtime_s: float
    samples_per_s: float
    median_input_wait_fraction: float
    median_first_batch_latency_s: float
    median_steady_samples_per_s: float
    median_steady_input_wait_fraction: float
    trace: dict[tuple[int, int], str]


def digest_tensor(value: Tensor) -> str:
    array = value.detach().contiguous().cpu().numpy()
    return hashlib.blake2b(array.tobytes(), digest_size=12).hexdigest()


def run_pipeline(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    policy: Policy,
    epochs: int,
    batch_size: int,
    workers: int,
    trace_samples: int,
    use_cuda: bool,
) -> Execution:
    dataset = PipelineDataset(manifest, epochs, policy, cache_path)
    loader_options: dict[str, object] = {
        "batch_size": batch_size,
        "shuffle": False,
        "num_workers": workers,
        "pin_memory": use_cuda,
        "worker_init_fn": configure_worker if workers else None,
    }
    if workers:
        loader_options["prefetch_factor"] = 2
    loader = DataLoader(dataset, **loader_options)
    trace: dict[tuple[int, int], str] = {}
    checksum = 0.0
    wait_s = 0.0
    steady_wait_s = 0.0
    first_batch_latency_s = 0.0
    first_batch_samples = 0
    batch_index = 0
    started = time.perf_counter()
    iterator = iter(loader)
    while True:
        wait_started = time.perf_counter()
        try:
            values, _, epoch_ids, sample_ids = next(iterator)
        except StopIteration:
            break
        batch_wait_s = time.perf_counter() - wait_started
        wait_s += batch_wait_s
        if batch_index > 0:
            steady_wait_s += batch_wait_s
        for row, epoch, sample_id in zip(values, epoch_ids.tolist(), sample_ids.tolist()):
            if sample_id < trace_samples:
                trace[(epoch, sample_id)] = digest_tensor(row)
        if use_cuda:
            device_values = values.to("cuda", non_blocking=True).float().div_(255.0)
            checksum += float(device_values.mean())
            torch.cuda.synchronize()
        else:
            checksum += float(values.float().mean())
        if batch_index == 0:
            first_batch_latency_s = time.perf_counter() - started
            first_batch_samples = len(values)
        batch_index += 1
    runtime = time.perf_counter() - started
    steady_runtime_s = max(runtime - first_batch_latency_s, 1e-12)
    steady_sample_count = max(len(dataset) - first_batch_samples, 0)
    return Execution(
        runtime_s=runtime,
        samples_per_s=len(dataset) / runtime,
        input_wait_fraction=wait_s / runtime,
        first_batch_latency_s=first_batch_latency_s,
        steady_samples_per_s=steady_sample_count / steady_runtime_s,
        steady_input_wait_fraction=steady_wait_s / steady_runtime_s,
        trace=trace,
        checksum=checksum,
    )


def summarize_executions(
    policy: Policy, workers: int, executions: list[Execution]
) -> PolicySummary:
    runtimes = [execution.runtime_s for execution in executions]
    representative = min(executions, key=lambda item: abs(item.runtime_s - statistics.median(runtimes)))
    median_runtime = statistics.median(runtimes)
    return PolicySummary(
        policy=policy,
        workers=workers,
        median_runtime_s=median_runtime,
        q1_runtime_s=float(np.quantile(runtimes, 0.25)),
        q3_runtime_s=float(np.quantile(runtimes, 0.75)),
        samples_per_s=statistics.median(
            execution.samples_per_s for execution in executions
        ),
        median_input_wait_fraction=statistics.median(
            execution.input_wait_fraction for execution in executions
        ),
        median_first_batch_latency_s=statistics.median(
            execution.first_batch_latency_s for execution in executions
        ),
        median_steady_samples_per_s=statistics.median(
            execution.steady_samples_per_s for execution in executions
        ),
        median_steady_input_wait_fraction=statistics.median(
            execution.steady_input_wait_fraction for execution in executions
        ),
        trace=representative.trace,
    )


def paired_benchmark(
    manifest: list[tuple[str, int]],
    cache_path: Path,
    epochs: int,
    batch_size: int,
    workers: int,
    repeats: int,
    trace_samples: int,
    use_cuda: bool,
) -> tuple[PolicySummary, PolicySummary]:
    collected: dict[Policy, list[Execution]] = {"uncached": [], "cached": []}
    # One warm-up per policy initializes torchvision kernels and CUDA context.
    warm_count = min(len(manifest), batch_size * 2)
    warm_manifest = manifest[:warm_count]
    for policy in ("uncached", "cached"):
        run_pipeline(
            warm_manifest,
            cache_path,
            policy,
            1,
            batch_size,
            0,
            0,
            use_cuda,
        )
    for repeat in range(repeats):
        order: tuple[Policy, Policy] = (
            ("uncached", "cached") if repeat % 2 == 0 else ("cached", "uncached")
        )
        for policy in order:
            collected[policy].append(
                run_pipeline(
                    manifest,
                    cache_path,
                    policy,
                    epochs,
                    batch_size,
                    workers,
                    trace_samples,
                    use_cuda,
                )
            )
    return (
        summarize_executions("uncached", workers, collected["uncached"]),
        summarize_executions("cached", workers, collected["cached"]),
    )


def trace_match(left: PolicySummary, right: PolicySummary) -> float:
    keys = sorted(set(left.trace) & set(right.trace))
    if not keys or set(left.trace) != set(right.trace):
        return 0.0
    return sum(left.trace[key] == right.trace[key] for key in keys) / len(keys)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    default_data = Path(tempfile.gettempdir()) / "autocontract_h5"
    parser.add_argument("--data-root", type=Path, default=default_data)
    parser.add_argument("--samples", type=int, default=1200)
    parser.add_argument("--export-size", type=int, default=224)
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--workers", type=int, nargs="+", default=[0, 2, 4])
    parser.add_argument("--cache-build-workers", type=int, default=4)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--trace-samples", type=int, default=24)
    parser.add_argument("--rebuild-cache", action="store_true")
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()

    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True)
    args.data_root.mkdir(parents=True, exist_ok=True)
    use_cuda = torch.cuda.is_available() and not args.cpu_only

    jpeg_root, export_time, exported, source_names = prepare_jpeg_tree(
        args.data_root, args.samples, args.export_size, args.jpeg_quality
    )
    manifest = imagefolder_manifest(jpeg_root, args.samples)
    cache_path = args.data_root / (
        f"skimage_prefix_n{args.samples}_s{args.export_size}_{PREFIX_SHAPE[1]}x{PREFIX_SHAPE[2]}.uint8.memmap"
    )
    expected_bytes = args.samples * math.prod(PREFIX_SHAPE)
    cache_metadata_path = cache_path.with_suffix(".json")
    cache_valid = cache_path.exists() and cache_path.stat().st_size == expected_bytes
    if args.rebuild_cache or not cache_valid:
        cache_build_time = build_prefix_cache(
            manifest, cache_path, args.batch_size, args.cache_build_workers
        )
        cache_rebuilt = True
    else:
        metadata = json.loads(cache_metadata_path.read_text(encoding="utf-8"))
        cache_build_time = float(metadata["build_time_s"])
        cache_rebuilt = False

    rows: list[dict[str, object]] = []
    any_gate_pass = False
    for workers in args.workers:
        uncached, cached = paired_benchmark(
            manifest,
            cache_path,
            args.epochs,
            args.batch_size,
            workers,
            args.repeats,
            args.trace_samples,
            use_cuda,
        )
        match = trace_match(uncached, cached)
        end_to_end_speedup = uncached.median_runtime_s / cached.median_runtime_s
        steady_speedup = (
            cached.median_steady_samples_per_s / uncached.median_steady_samples_per_s
        )
        uncached_epoch = args.samples / uncached.median_steady_samples_per_s
        cached_epoch = args.samples / cached.median_steady_samples_per_s
        savings_per_epoch = uncached_epoch - cached_epoch
        break_even = (
            cache_build_time / savings_per_epoch if savings_per_epoch > 0 else math.inf
        )
        amortized_speedup = uncached.median_runtime_s / (
            cache_build_time + cached.median_runtime_s
        )
        gate_pass = steady_speedup >= 1.20 and match == 1.0
        any_gate_pass = any_gate_pass or gate_pass
        rows.append(
            {
                "workers": workers,
                "device_consumer": "cuda" if use_cuda else "cpu",
                "uncached_median_s": uncached.median_runtime_s,
                "uncached_q1_s": uncached.q1_runtime_s,
                "uncached_q3_s": uncached.q3_runtime_s,
                "cached_median_s": cached.median_runtime_s,
                "cached_q1_s": cached.q1_runtime_s,
                "cached_q3_s": cached.q3_runtime_s,
                "uncached_samples_per_s": uncached.samples_per_s,
                "cached_samples_per_s": cached.samples_per_s,
                "end_to_end_speedup": end_to_end_speedup,
                "steady_speedup": steady_speedup,
                "uncached_input_wait_fraction": uncached.median_input_wait_fraction,
                "cached_input_wait_fraction": cached.median_input_wait_fraction,
                "uncached_first_batch_latency_s": uncached.median_first_batch_latency_s,
                "cached_first_batch_latency_s": cached.median_first_batch_latency_s,
                "uncached_steady_samples_per_s": uncached.median_steady_samples_per_s,
                "cached_steady_samples_per_s": cached.median_steady_samples_per_s,
                "uncached_steady_input_wait_fraction": uncached.median_steady_input_wait_fraction,
                "cached_steady_input_wait_fraction": cached.median_steady_input_wait_fraction,
                "trace_match": match,
                "cache_build_time_s": cache_build_time,
                "conservative_break_even_epochs": break_even,
                "offline_amortized_speedup_at_measured_epochs": amortized_speedup,
                "h5a_steady_gate_pass": gate_pass,
            }
        )

    write_csv(OUT / "autocontract_h5_jpeg_workers.csv", rows)
    lines = [
        "# AutoContract H5a: JPEG/DataLoader prefix-cache benchmark",
        "",
        f"Dataset: {args.samples} deterministic crops from {len(source_names)} bundled real photographs "
        f"({', '.join(source_names)}), exported as {args.export_size}×{args.export_size} JPEG "
        f"(quality {args.jpeg_quality}) in an ImageFolder-compatible tree.",
        f"Epochs: {args.epochs}; batch size: {args.batch_size}; paired repeats: {args.repeats}; "
        f"consumer: {'CUDA' if use_cuda else 'CPU'}.",
        f"JPEG export performed in this run: {exported} ({export_time:.2f}s). "
        f"Prefix cache rebuilt in this run: {cache_rebuilt} ({cache_build_time:.2f}s).",
        "",
        "| Workers | Total uncached→cached (s) | First batch uncached→cached (s) | Post-first-batch samples/s | End-to-end speedup | Steady speedup | Steady input-wait | Trace | Break-even | Offline amortized speedup | H5a |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        break_even_text = (
            f"{row['conservative_break_even_epochs']:.2f} epochs"
            if math.isfinite(float(row["conservative_break_even_epochs"]))
            else "never"
        )
        lines.append(
            f"| {row['workers']} | {row['uncached_median_s']:.2f}→{row['cached_median_s']:.2f} | "
            f"{row['uncached_first_batch_latency_s']:.2f}→{row['cached_first_batch_latency_s']:.2f} | "
            f"{row['uncached_steady_samples_per_s']:.1f}→{row['cached_steady_samples_per_s']:.1f} | "
            f"{row['end_to_end_speedup']:.2f}× | {row['steady_speedup']:.2f}× | "
            f"{row['uncached_steady_input_wait_fraction']:.1%}→{row['cached_steady_input_wait_fraction']:.1%} | "
            f"{row['trace_match']:.3f} | {break_even_text} | "
            f"{row['offline_amortized_speedup_at_measured_epochs']:.2f}× | "
            f"{'PASS' if row['h5a_steady_gate_pass'] else 'FAIL'} |"
        )

    lines.extend(
        (
            "",
            "## Verdict",
            "",
            f"- H5a steady-state gate (>=1.20× and exact trace): **{'PASS' if any_gate_pass else 'FAIL'}**.",
            "- Steady-state metrics exclude the first batch, which contains DataLoader worker spawn and initial prefetch.",
            "- Cache construction is treated as an extra offline pass; the amortized figure is deliberately conservative.",
            "- H5b is not yet a training result: the CUDA consumer only transfers, normalizes, and reduces each batch.",
            "- This is a systems-path pilot over seven real source photographs; content diversity is insufficient for a training-quality dataset claim.",
            "",
        )
    )
    report = "\n".join(lines)
    (OUT / "autocontract_h5_jpeg_dataloader.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    # Required for Windows DataLoader spawn workers.
    main()
