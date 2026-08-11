"""H8C registered multi-workload cache benchmark calibration.

The harness exercises one common optimizer boundary over safe CV/audio prefix
caches and three unsafe cache boundaries. It is registered and hash-frozen, but
not independently blinded; its role is to calibrate the final benchmark design.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import math
import os
import random
import statistics
import struct
import sys
import tempfile
import textwrap
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2

import autocontract_optimizer_boundary as boundary
import autocontract_stateless_benchmark as stateless


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
PROTOCOL = ROOT / "benchmark" / "autocontract_h8c_cache_protocol.json"
FREEZE = OUT / "autocontract_h8c_freeze.json"
BASE_SEED = 20260729
Policy = Literal[
    "fail_closed",
    "registry_only",
    "static_only",
    "dynamic_only",
    "hybrid",
    "manual_hint",
    "human_oracle",
]
POLICIES: tuple[Policy, ...] = (
    "fail_closed",
    "registry_only",
    "static_only",
    "dynamic_only",
    "hybrid",
    "manual_hint",
    "human_oracle",
)


@dataclass(frozen=True)
class WorkloadSpec:
    workload_id: str
    domain: str
    expected_safe: bool
    coarse_reason: str
    registry_known: bool
    static_admit: bool
    static_reason: str


@dataclass(frozen=True)
class Measurement:
    workload_id: str
    raw_median_s: float
    cached_median_s: float
    build_median_s: float
    cold_candidate_s: float
    optimizer_score_s: float
    trace_match: bool
    raw_unique_outputs: float
    cached_unique_outputs: float


@dataclass(frozen=True)
class PolicyDecision:
    policy: Policy
    workload_id: str
    semantic_admit: bool
    semantic_reason: str
    cost_positive: bool
    selected: bool
    oracle_safe: bool
    oracle_selected: bool
    unsafe_selection: bool
    benefit_coverage: float | None


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tensor_digest(value: Tensor) -> str:
    return hashlib.sha256(value.detach().contiguous().cpu().numpy().tobytes()).hexdigest()


def array_digest(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def stable_audio_key(epoch: int, sample_id: int, operator_id: str) -> int:
    return (
        BASE_SEED
        ^ ((epoch + 1) * stateless.EPOCH_MIX)
        ^ ((sample_id + 1) * stateless.SAMPLE_MIX)
        ^ stateless.stable_operator_key(operator_id)
    ) & stateless.MASK64


def make_cv_samples(count: int) -> list[Tensor]:
    return [
        torch.clamp(stateless.make_images(1, 127, 151)[0] + index * 0.001, 0.0, 1.0)
        .mul(255.0)
        .round()
        .to(torch.uint8)
        for index in range(count)
    ]


def cv_prefix(value: Tensor) -> Tensor:
    return stateless.stateless_prefix(value)


def cv_suffix(value: Tensor, epoch: int, sample_id: int) -> Tensor:
    return stateless.stateless_suffix(value, epoch, sample_id)


def external_prefix(value: Tensor) -> Tensor:
    gain = float(os.environ.get("AUTOCONTRACT_H8C_GAIN", "1.0"))
    return torch.clamp(stateless.stateless_prefix(value).float() * gain, 0.0, 255.0).to(torch.uint8)


def generate_audio_tree(root: Path, count: int) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    sample_rate = 16_000
    length = 8192
    time_axis = np.arange(length, dtype=np.float64) / sample_rate
    for sample_id in range(count):
        path = root / f"sample_{sample_id:04d}.wav"
        paths.append(path)
        if path.exists():
            continue
        rng = np.random.default_rng(BASE_SEED + sample_id)
        frequency = 180.0 + 7.0 * (sample_id % 17)
        signal = 0.55 * np.sin(2 * np.pi * frequency * time_axis)
        signal += 0.25 * np.sin(2 * np.pi * (frequency * 1.7) * time_axis + 0.1 * sample_id)
        signal += rng.normal(0.0, 0.025, size=length)
        pcm = np.clip(signal, -1.0, 1.0)
        pcm16 = np.round(pcm * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm16.tobytes())
    return paths


def audio_prefix(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("H8C audio input must be mono PCM16")
        waveform = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32)
    waveform /= 32768.0
    emphasized = np.empty_like(waveform)
    emphasized[0] = waveform[0]
    emphasized[1:] = waveform[1:] - 0.97 * waveform[:-1]
    frame_length, hop = 256, 128
    frame_count = 1 + (len(emphasized) - frame_length) // hop
    frames = np.stack(
        [emphasized[index * hop : index * hop + frame_length] for index in range(frame_count)]
    )
    window = np.hanning(frame_length).astype(np.float32)
    spectrum = np.fft.rfft(frames * window, axis=1)
    return np.log1p(np.abs(spectrum)).astype(np.float32)


def audio_suffix(value: np.ndarray, epoch: int, sample_id: int) -> np.ndarray:
    key = stable_audio_key(epoch, sample_id, "audio_gain")
    gain = stateless.uniform(key, 0, 0.85, 1.15)
    width = 4
    max_start = max(value.shape[1] - width + 1, 1)
    start = stateless.randint(key, 1, max_start)
    output = np.array(value, copy=True) * gain
    output[:, start : start + width] = 0.0
    return output


def fixed_rng_prefix() -> v2.GaussianBlur:
    return v2.GaussianBlur(9, sigma=(1.4, 1.4))


def global_rng_suffix() -> v2.Compose:
    return v2.Compose((v2.RandomHorizontalFlip(p=0.5), v2.RandomCrop((88, 92))))


def cv_trace(
    samples: list[Tensor],
    epochs: int,
    prefix: Callable[[Tensor], Tensor],
    suffix: Callable[[Tensor, int, int], Tensor],
    *,
    cached: list[Tensor] | None = None,
) -> tuple[list[str], float]:
    digests: list[str] = []
    checksum = 0.0
    for epoch in range(epochs):
        for sample_id, source in enumerate(samples):
            value = cached[sample_id] if cached is not None else prefix(source)
            output = suffix(value.clone(), epoch, sample_id)
            digests.append(tensor_digest(output))
            checksum += float(output.float().mean())
    return digests, checksum


def audio_trace(
    paths: list[Path],
    epochs: int,
    *,
    cached: list[np.ndarray] | None = None,
) -> tuple[list[str], float]:
    digests: list[str] = []
    checksum = 0.0
    for epoch in range(epochs):
        for sample_id, path in enumerate(paths):
            value = cached[sample_id] if cached is not None else audio_prefix(path)
            output = audio_suffix(value, epoch, sample_id)
            digests.append(array_digest(output))
            checksum += float(output.mean())
    return digests, checksum


def global_rng_trace(
    samples: list[Tensor], epochs: int, *, cached: list[Tensor] | None = None
) -> tuple[list[str], float]:
    prefix = fixed_rng_prefix()
    suffix = global_rng_suffix()
    torch.manual_seed(BASE_SEED)
    digests: list[str] = []
    checksum = 0.0
    for _epoch in range(epochs):
        for sample_id, source in enumerate(samples):
            value = cached[sample_id] if cached is not None else prefix(source)
            output = suffix(value.clone())
            digests.append(tensor_digest(output))
            checksum += float(output.float().mean())
    return digests, checksum


def full_cache_trace(
    samples: list[Tensor], epochs: int, *, cached: list[Tensor] | None = None
) -> tuple[list[str], float]:
    if cached is None:
        return cv_trace(samples, epochs, cv_prefix, cv_suffix)
    digests: list[str] = []
    checksum = 0.0
    for _epoch in range(epochs):
        for output in cached:
            digests.append(tensor_digest(output))
            checksum += float(output.float().mean())
    return digests, checksum


def median_timed(callable_obj: Callable[[], tuple[list[str], float]], repeats: int) -> tuple[float, list[str]]:
    samples: list[float] = []
    representative: list[str] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        digests, checksum = callable_obj()
        elapsed = (time.perf_counter_ns() - started) / 1e9
        if not math.isfinite(checksum):
            raise RuntimeError("non-finite workload checksum")
        samples.append(elapsed)
        representative = digests
    return statistics.median(samples), representative


def paired_timed(
    raw_callable: Callable[[], tuple[list[str], float]],
    cached_callable: Callable[[], tuple[list[str], float]],
    repeats: int,
) -> tuple[float, list[str], float, list[str]]:
    collected: dict[str, list[float]] = {"raw": [], "cached": []}
    traces: dict[str, list[str]] = {"raw": [], "cached": []}
    operations = {"raw": raw_callable, "cached": cached_callable}
    for repeat in range(repeats):
        order = ("raw", "cached") if repeat % 2 == 0 else ("cached", "raw")
        for name in order:
            started = time.perf_counter_ns()
            digests, checksum = operations[name]()
            elapsed = (time.perf_counter_ns() - started) / 1e9
            if not math.isfinite(checksum):
                raise RuntimeError("non-finite workload checksum")
            collected[name].append(elapsed)
            traces[name] = digests
    return (
        statistics.median(collected["raw"]),
        traces["raw"],
        statistics.median(collected["cached"]),
        traces["cached"],
    )


def median_build(build: Callable[[], object], repeats: int) -> tuple[float, object]:
    samples: list[float] = []
    artifact: object = None
    for _ in range(repeats):
        started = time.perf_counter_ns()
        artifact = build()
        samples.append((time.perf_counter_ns() - started) / 1e9)
    return statistics.median(samples), artifact


def mean_unique(digests: list[str], sample_count: int, epochs: int) -> float:
    return statistics.mean(
        len({digests[epoch * sample_count + sample_id] for epoch in range(epochs)})
        for sample_id in range(sample_count)
    )


def measure_cv_safe(samples: list[Tensor], epochs: int, repeats: int) -> Measurement:
    build_s, artifact = median_build(lambda: [cv_prefix(value) for value in samples], repeats)
    cache = artifact  # type: ignore[assignment]
    raw_s, raw, cached_s, cached = paired_timed(
        lambda: cv_trace(samples, epochs, cv_prefix, cv_suffix),
        lambda: cv_trace(samples, epochs, cv_prefix, cv_suffix, cached=cache),
        repeats,
    )
    return Measurement("cv_safe_prefix", raw_s, cached_s, build_s, build_s + cached_s, raw_s - build_s - cached_s, raw == cached, mean_unique(raw, len(samples), epochs), mean_unique(cached, len(samples), epochs))


def measure_audio_safe(paths: list[Path], epochs: int, repeats: int) -> Measurement:
    build_s, artifact = median_build(lambda: [audio_prefix(path) for path in paths], repeats)
    cache = artifact  # type: ignore[assignment]
    raw_s, raw, cached_s, cached = paired_timed(
        lambda: audio_trace(paths, epochs),
        lambda: audio_trace(paths, epochs, cached=cache),
        repeats,
    )
    return Measurement("audio_safe_prefix", raw_s, cached_s, build_s, build_s + cached_s, raw_s - build_s - cached_s, raw == cached, mean_unique(raw, len(paths), epochs), mean_unique(cached, len(paths), epochs))


def measure_hidden_rng(samples: list[Tensor], epochs: int, repeats: int) -> Measurement:
    def build() -> list[Tensor]:
        torch.manual_seed(BASE_SEED)
        prefix = fixed_rng_prefix()
        return [prefix(value) for value in samples]

    build_s, artifact = median_build(build, repeats)
    cache = artifact  # type: ignore[assignment]
    raw_s, raw, cached_s, cached = paired_timed(
        lambda: global_rng_trace(samples, epochs),
        lambda: global_rng_trace(samples, epochs, cached=cache),
        repeats,
    )
    return Measurement("cv_hidden_rng_prefix", raw_s, cached_s, build_s, build_s + cached_s, raw_s - build_s - cached_s, raw == cached, mean_unique(raw, len(samples), epochs), mean_unique(cached, len(samples), epochs))


def measure_external(samples: list[Tensor], epochs: int, repeats: int) -> Measurement:
    previous = os.environ.get("AUTOCONTRACT_H8C_GAIN")
    try:
        os.environ["AUTOCONTRACT_H8C_GAIN"] = "1.0"
        build_s, artifact = median_build(lambda: [external_prefix(value) for value in samples], repeats)
        cache = artifact  # type: ignore[assignment]
        os.environ["AUTOCONTRACT_H8C_GAIN"] = "1.2"
        raw_s, raw, cached_s, cached = paired_timed(
            lambda: cv_trace(samples, epochs, external_prefix, cv_suffix),
            lambda: cv_trace(samples, epochs, external_prefix, cv_suffix, cached=cache),
            repeats,
        )
    finally:
        if previous is None:
            os.environ.pop("AUTOCONTRACT_H8C_GAIN", None)
        else:
            os.environ["AUTOCONTRACT_H8C_GAIN"] = previous
    return Measurement("cv_external_state_prefix", raw_s, cached_s, build_s, build_s + cached_s, raw_s - build_s - cached_s, raw == cached, mean_unique(raw, len(samples), epochs), mean_unique(cached, len(samples), epochs))


def measure_full_cache(samples: list[Tensor], epochs: int, repeats: int) -> Measurement:
    build_s, artifact = median_build(
        lambda: [cv_suffix(cv_prefix(value), 0, sample_id) for sample_id, value in enumerate(samples)],
        repeats,
    )
    cache = artifact  # type: ignore[assignment]
    raw_s, raw, cached_s, cached = paired_timed(
        lambda: full_cache_trace(samples, epochs),
        lambda: full_cache_trace(samples, epochs, cached=cache),
        repeats,
    )
    return Measurement("cv_full_cache", raw_s, cached_s, build_s, build_s + cached_s, raw_s - build_s - cached_s, raw == cached, mean_unique(raw, len(samples), epochs), mean_unique(cached, len(samples), epochs))


def source_digest(functions: tuple[object, ...]) -> str:
    source = "\n".join(textwrap.dedent(inspect.getsource(function)) for function in functions)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def workload_specs() -> tuple[WorkloadSpec, ...]:
    external_source = textwrap.dedent(inspect.getsource(external_prefix))
    return (
        WorkloadSpec("cv_safe_prefix", "computer_vision", True, "none", True, True, "resolved_pure_prefix"),
        WorkloadSpec("audio_safe_prefix", "audio", True, "none", False, True, "content_bound_file_read_and_pure_features"),
        WorkloadSpec("cv_hidden_rng_prefix", "computer_vision", False, "hidden_rng_effect", False, False, "unresolved_library_rng_effect"),
        WorkloadSpec("cv_external_state_prefix", "computer_vision", False, "external_state_drift", False, "os.environ" not in external_source, "external_environment_read"),
        WorkloadSpec("cv_full_cache", "computer_vision", False, "augmentation_diversity_frozen", False, False, "cache_boundary_crosses_epoch_rng"),
    )


def policy_admit(policy: Policy, spec: WorkloadSpec, measurement: Measurement) -> tuple[bool, str]:
    if policy == "fail_closed":
        return False, "missing_contract"
    if policy == "registry_only":
        return spec.registry_known, "trusted_registry" if spec.registry_known else "unregistered_prefix"
    if policy == "static_only":
        return spec.static_admit, spec.static_reason
    if policy == "dynamic_only":
        # Weak baseline: probe only the current build context / epoch-0 value.
        # All five candidates can look equal at that point, so future drift and
        # diversity obligations are not proven.
        return True, "same_context_probe_no_counterexample"
    if policy == "hybrid":
        return spec.static_admit, "static_and_dynamic_agree" if spec.static_admit else spec.static_reason
    if policy in ("manual_hint", "human_oracle"):
        return spec.expected_safe, "sealed_manual_oracle"
    raise ValueError(policy)


def decide(policy: Policy, spec: WorkloadSpec, measurement: Measurement) -> PolicyDecision:
    admitted, reason = policy_admit(policy, spec, measurement)
    cost_positive = measurement.optimizer_score_s > 0
    selected = admitted and cost_positive
    oracle_selected = spec.expected_safe and cost_positive
    raw = measurement.raw_median_s
    oracle_runtime = measurement.cold_candidate_s if oracle_selected else raw
    auto_runtime = measurement.cold_candidate_s if selected else raw
    oracle_gain = raw - oracle_runtime
    benefit = (raw - auto_runtime) / oracle_gain if oracle_gain > 0 and spec.expected_safe else None
    return PolicyDecision(
        policy,
        spec.workload_id,
        admitted,
        reason,
        cost_positive,
        selected,
        spec.expected_safe,
        oracle_selected,
        selected and not spec.expected_safe,
        benefit,
    )


def metrics(policy: Policy, decisions: list[PolicyDecision]) -> dict[str, object]:
    tp = sum(item.semantic_admit and item.oracle_safe for item in decisions)
    fp = sum(item.semantic_admit and not item.oracle_safe for item in decisions)
    fn = sum(not item.semantic_admit and item.oracle_safe for item in decisions)
    tn = sum(not item.semantic_admit and not item.oracle_safe for item in decisions)
    benefits = [float(item.benefit_coverage) for item in decisions if item.benefit_coverage is not None]
    return {
        "policy": policy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "unsafe_false_accepts": fp,
        "unsafe_plan_selections": sum(item.unsafe_selection for item in decisions),
        "benefit_positive_safe_workloads": len(benefits),
        "mean_human_oracle_benefit_coverage": statistics.mean(benefits) if benefits else 0.0,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def seal() -> None:
    if FREEZE.exists():
        raise RuntimeError("H8C freeze already exists; create a new benchmark version instead")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = {
        "protocol": protocol["protocol"],
        "claim_boundary": protocol["claim_boundary"],
        "runner_sha256": sha256(Path(__file__)),
        "protocol_sha256": sha256(PROTOCOL),
        "stateless_module_sha256": sha256(Path(stateless.__file__)),
        "torch_version": torch.__version__,
        "torchvision_version": __import__("torchvision").__version__,
        "python_version": sys.version.split()[0],
        "source_bodies_already_known": True,
        "independent_oracle": False,
    }
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(freeze, indent=2))


def verify_freeze() -> dict[str, object]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    checks = {
        "runner_sha256": Path(__file__),
        "protocol_sha256": PROTOCOL,
        "stateless_module_sha256": Path(stateless.__file__),
    }
    for key, path in checks.items():
        if sha256(path) != freeze[key]:
            raise RuntimeError("H8C freeze violation: " + key)
    return freeze


def run_benchmark(*, sample_count: int, epochs: int, repeats: int, write_outputs: bool) -> dict[str, object]:
    torch.set_num_threads(1)
    random.seed(BASE_SEED)
    np.random.seed(BASE_SEED % (2**32 - 1))
    torch.manual_seed(BASE_SEED)
    data_root = Path(tempfile.gettempdir()) / "autocontract_h8c"
    cv_samples = make_cv_samples(sample_count)
    audio_paths = generate_audio_tree(data_root / f"audio_n{sample_count}", sample_count)

    measurements = [
        measure_cv_safe(cv_samples, epochs, repeats),
        measure_audio_safe(audio_paths, epochs, repeats),
        measure_hidden_rng(cv_samples, epochs, repeats),
        measure_external(cv_samples, epochs, repeats),
        measure_full_cache(cv_samples, epochs, repeats),
    ]
    specs = workload_specs()
    by_measurement = {item.workload_id: item for item in measurements}
    decisions = [
        decide(policy, spec, by_measurement[spec.workload_id])
        for policy in POLICIES
        for spec in specs
    ]
    summaries = [metrics(policy, [item for item in decisions if item.policy == policy]) for policy in POLICIES]
    hybrid = next(row for row in summaries if row["policy"] == "hybrid")
    dynamic = next(row for row in summaries if row["policy"] == "dynamic_only")
    expected_trace = all(
        measurement.trace_match == spec.expected_safe
        for spec, measurement in zip(specs, measurements)
    )
    checks = {
        "two_safe_and_three_unsafe_workloads": sum(spec.expected_safe for spec in specs) == 2 and sum(not spec.expected_safe for spec in specs) == 3,
        "cv_and_audio_domains_present": {spec.domain for spec in specs} == {"computer_vision", "audio"},
        "semantic_traces_match_registered_expectations": expected_trace,
        "safe_workloads_preserve_epoch_diversity": all(measurement.raw_unique_outputs > 1 and measurement.cached_unique_outputs > 1 for spec, measurement in zip(specs, measurements) if spec.expected_safe),
        "full_cache_freezes_diversity": by_measurement["cv_full_cache"].cached_unique_outputs == 1.0,
        "hybrid_zero_unsafe_false_accepts": int(hybrid["unsafe_false_accepts"]) == 0,
        "hybrid_safe_recall_gate": float(hybrid["safe_recall"]) >= 0.8,
        "hybrid_benefit_coverage_gate": float(hybrid["mean_human_oracle_benefit_coverage"]) >= 0.9,
        "hybrid_zero_unsafe_plan_selections": int(hybrid["unsafe_plan_selections"]) == 0,
        "dynamic_only_unsafe_false_accepts_exposed": int(dynamic["unsafe_false_accepts"]) == 3,
        "dynamic_only_unsafe_plan_selection_exposed": int(dynamic["unsafe_plan_selections"]) >= 1,
        "semantic_reject_dominates_positive_cost": all(
            not item.selected for item in decisions if item.policy == "hybrid" and not item.oracle_safe
        ),
    }
    all_checks_pass = all(checks.values())
    result = {
        "measurements": measurements,
        "decisions": decisions,
        "summaries": summaries,
        "checks": checks,
        "all_checks_pass": all_checks_pass,
    }
    if not write_outputs:
        return result

    freeze = verify_freeze()
    measurement_rows = [asdict(item) for item in measurements]
    decision_rows = [asdict(item) for item in decisions]
    for row in decision_rows:
        row["benefit_coverage"] = "not_applicable" if row["benefit_coverage"] is None else row["benefit_coverage"]
    write_csv(OUT / "autocontract_h8c_measurements.csv", measurement_rows)
    write_csv(OUT / "autocontract_h8c_decisions.csv", decision_rows)
    write_csv(OUT / "autocontract_h8c_summary.csv", summaries)
    selftest = {
        "protocol": freeze["protocol"],
        "claim_boundary": freeze["claim_boundary"],
        "sample_count": sample_count,
        "epochs": epochs,
        "repeats": repeats,
        "checks": checks,
        "all_checks_pass": all_checks_pass,
    }
    (OUT / "autocontract_h8c_selftest.json").write_text(json.dumps(selftest, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# AutoContract H8C registered multi-workload cache benchmark",
        "",
        "> Internal calibration benchmark: protocol and runner were hash-frozen before the registered run, but source bodies and the oracle were not independently blinded.",
        "",
        f"Workloads: {len(specs)} (2 safe, 3 unsafe); domains: CV + audio; samples/workload: {sample_count}; epochs: {epochs}; repeats: {repeats}.",
        "",
        "| Workload | Safe oracle | Raw | Build+cached | Net benefit | Trace match | Raw diversity | Cached diversity |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for spec, item in zip(specs, measurements):
        lines.append(
            f"| {item.workload_id} | {spec.expected_safe} | {item.raw_median_s:.3f}s | {item.cold_candidate_s:.3f}s | "
            f"{item.optimizer_score_s:.3f}s | {item.trace_match} | {item.raw_unique_outputs:.2f} | {item.cached_unique_outputs:.2f} |"
        )
    lines.extend(
        [
            "",
            "| Policy | TP | FP | FN | TN | Safe recall | Unsafe plan selections | Benefit-positive safe workloads | Mean oracle benefit coverage |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summaries:
        lines.append(
            f"| {row['policy']} | {row['tp']} | {row['fp']} | {row['fn']} | {row['tn']} | "
            f"{float(row['safe_recall']):.1%} | {row['unsafe_plan_selections']} | "
            f"{row['benefit_positive_safe_workloads']} | {float(row['mean_human_oracle_benefit_coverage']):.1%} |"
        )
    lines.extend(
        [
            "",
            "## Registered checks",
            "",
            *[f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in checks.items()],
            "",
            f"Overall H8C calibration gate: **{'PASS' if all_checks_pass else 'FAIL'}**.",
            "",
            "## Claim boundary",
            "",
            "H8C validates the benchmark harness and shows how dynamic-only can turn same-context probes into unsafe plans. It is not the final blind result because the source bodies and oracle were known and no independent annotator sealed the corpus.",
            "",
        ]
    )
    report = "\n".join(lines)
    (OUT / "autocontract_h8c_multiworkload_cache.md").write_text(report, encoding="utf-8")
    print(report)
    if not all_checks_pass:
        raise SystemExit(1)
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--smoke", action="store_true")
    group.add_argument("--seal", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.seal:
        seal()
        return
    if args.smoke:
        result = run_benchmark(sample_count=8, epochs=2, repeats=1, write_outputs=False)
        smoke_checks = {
            name: passed
            for name, passed in result["checks"].items()
            if name != "hybrid_benefit_coverage_gate"
        }
        print(json.dumps({"checks": smoke_checks, "smoke_pass": all(smoke_checks.values())}, indent=2))
        return
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    measurement = protocol["measurement"]
    run_benchmark(
        sample_count=int(measurement["samples"]),
        epochs=int(measurement["epochs"]),
        repeats=int(measurement["repeats"]),
        write_outputs=True,
    )


if __name__ == "__main__":
    main()
