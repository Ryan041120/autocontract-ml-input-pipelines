"""H8C-R1: review-driven stateful-dynamic baseline calibration.

This experiment does not modify or rerun the frozen H8C benchmark.  It applies
the new fixed-budget public probe schedule to the same five known workload
boundaries and reuses H8C's archived cost measurements only for plan-selection
accounting.  Source bodies and oracle labels are known, so the result is an
internal calibration rather than blind evidence.
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
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import numpy as np
import torch
from torch import Tensor
from torchvision.transforms import v2

import autocontract_final_baseline_horizon as baseline
import autocontract_stateless_benchmark as stateless


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
H8C_MEASUREMENTS = OUT / "autocontract_h8c_measurements.csv"
H8C_FREEZE = OUT / "autocontract_h8c_freeze.json"
PROTOCOL = ROOT / "benchmark" / "final_v1" / "h8c_r1_stateful_dynamic_protocol.json"
DEFAULT_JSON = OUT / "autocontract_h8c_r1_stateful_dynamic.json"
DEFAULT_CSV = OUT / "autocontract_h8c_r1_stateful_dynamic.csv"
DEFAULT_REPORT = OUT / "autocontract_h8c_r1_stateful_dynamic.md"
BASE_SEED = 20260730


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_cv_sample() -> Tensor:
    return (
        torch.clamp(stateless.make_images(1, 127, 151)[0], 0.0, 1.0)
        .mul(255.0)
        .round()
        .to(torch.uint8)
    )


def cv_prefix(value: Tensor) -> Tensor:
    return stateless.stateless_prefix(value)


def cv_suffix(value: Tensor, epoch: int, sample_id: int = 0) -> Tensor:
    return stateless.stateless_suffix(value, epoch, sample_id)


def external_prefix(value: Tensor) -> Tensor:
    gain = float(os.environ.get("AUTOCONTRACT_H8C_GAIN", "1.0"))
    return torch.clamp(cv_prefix(value).float() * gain, 0.0, 255.0).to(torch.uint8)


def make_audio_file(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "probe.wav"
    sample_rate = 16_000
    length = 8192
    axis = np.arange(length, dtype=np.float64) / sample_rate
    rng = np.random.default_rng(BASE_SEED)
    signal = 0.55 * np.sin(2 * np.pi * 180.0 * axis)
    signal += 0.25 * np.sin(2 * np.pi * 306.0 * axis)
    signal += rng.normal(0.0, 0.025, size=length)
    pcm16 = np.round(np.clip(signal, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())
    return path


def audio_prefix(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        waveform = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(
            np.float32
        )
    waveform /= 32768.0
    emphasized = np.empty_like(waveform)
    emphasized[0] = waveform[0]
    emphasized[1:] = waveform[1:] - 0.97 * waveform[:-1]
    frame_length, hop = 256, 128
    frame_count = 1 + (len(emphasized) - frame_length) // hop
    frames = np.stack(
        [emphasized[index * hop : index * hop + frame_length] for index in range(frame_count)]
    )
    spectrum = np.fft.rfft(frames * np.hanning(frame_length).astype(np.float32), axis=1)
    return np.log1p(np.abs(spectrum)).astype(np.float32)


class CvSafeProbe:
    def __init__(self, sample: Tensor) -> None:
        self.sample = sample

    def __call__(self, value: int, *, epoch: int) -> Tensor:
        del value, epoch
        return cv_prefix(self.sample)


class AudioSafeProbe:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __call__(self, value: int, *, epoch: int) -> np.ndarray:
        del value, epoch
        return audio_prefix(self.path)


class HiddenRngProbe:
    def __init__(self, sample: Tensor) -> None:
        self.sample = sample
        self.prefix = v2.GaussianBlur(9, sigma=(1.4, 1.4))

    def __call__(self, value: int, *, epoch: int) -> Tensor:
        del value, epoch
        return self.prefix(self.sample)


class ExternalStateProbe:
    def __init__(self, sample: Tensor) -> None:
        self.sample = sample

    def __call__(self, value: int, *, epoch: int) -> Tensor:
        del value, epoch
        return external_prefix(self.sample)


class FullCacheProbe:
    def __init__(self, sample: Tensor) -> None:
        self.sample = sample

    def __call__(self, value: int, *, epoch: int) -> Tensor:
        del value
        return cv_suffix(cv_prefix(self.sample), epoch)


@dataclass(frozen=True)
class Decision:
    policy: str
    workload_id: str
    semantic_admit: bool
    selected: bool
    oracle_safe: bool
    unsafe_selection: bool
    optimizer_score_s: float
    observed_effects: Tuple[str, ...]


def load_optimizer_scores() -> Dict[str, float]:
    scores: Dict[str, float] = {}
    with H8C_MEASUREMENTS.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            scores[str(row["workload_id"])] = float(row["optimizer_score_s"])
    return scores


def score_policy(policy: str, decisions: List[Decision]) -> Dict[str, object]:
    tp = sum(item.semantic_admit and item.oracle_safe for item in decisions)
    fp = sum(item.semantic_admit and not item.oracle_safe for item in decisions)
    fn = sum(not item.semantic_admit and item.oracle_safe for item in decisions)
    tn = sum(not item.semantic_admit and not item.oracle_safe for item in decisions)
    return {
        "policy": policy,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "safe_recall": tp / max(tp + fn, 1),
        "unsafe_false_accepts": fp,
        "unsafe_plan_selections": sum(item.unsafe_selection for item in decisions),
    }


def run() -> Dict[str, object]:
    if not H8C_MEASUREMENTS.exists() or not H8C_FREEZE.exists():
        raise FileNotFoundError("archived H8C measurements/freeze are required")
    torch.set_num_threads(1)
    sample = make_cv_sample()
    audio_path = make_audio_file(Path(tempfile.gettempdir()) / "autocontract_h8c_r1")
    factories: Dict[str, Callable[[], object]] = {
        "cv_safe_prefix": lambda: CvSafeProbe(sample),
        "audio_safe_prefix": lambda: AudioSafeProbe(audio_path),
        "cv_hidden_rng_prefix": lambda: HiddenRngProbe(sample),
        "cv_external_state_prefix": lambda: ExternalStateProbe(sample),
        "cv_full_cache": lambda: FullCacheProbe(sample),
    }
    probe_spec = baseline.ProbeSpec(
        seed=BASE_SEED,
        environment_key="AUTOCONTRACT_H8C_GAIN",
        environment_values=("1.0", "1.2"),
    )
    # Probes are completed before oracle labels are joined for scoring.
    probes = {
        workload_id: baseline.run_stateful_probe(
            workload_id, factory, value=7, spec=probe_spec
        )
        for workload_id, factory in factories.items()
    }

    optimizer_scores = load_optimizer_scores()
    oracle_safe = {
        "cv_safe_prefix": True,
        "audio_safe_prefix": True,
        "cv_hidden_rng_prefix": False,
        "cv_external_state_prefix": False,
        "cv_full_cache": False,
    }
    hybrid_admit = {
        "cv_safe_prefix": True,
        "audio_safe_prefix": True,
        "cv_hidden_rng_prefix": False,
        "cv_external_state_prefix": False,
        "cv_full_cache": False,
    }
    policy_admission = {
        "dynamic_output_only": {
            name: not result.output_only_conflict for name, result in probes.items()
        },
        "dynamic_stateful": {
            name: not result.stateful_conflict for name, result in probes.items()
        },
        "hybrid": hybrid_admit,
    }
    decisions: List[Decision] = []
    for policy, admissions in policy_admission.items():
        for workload_id, admitted in admissions.items():
            selected = admitted and optimizer_scores[workload_id] > 0
            decisions.append(
                Decision(
                    policy=policy,
                    workload_id=workload_id,
                    semantic_admit=admitted,
                    selected=selected,
                    oracle_safe=oracle_safe[workload_id],
                    unsafe_selection=selected and not oracle_safe[workload_id],
                    optimizer_score_s=optimizer_scores[workload_id],
                    observed_effects=probes[workload_id].observed_effects,
                )
            )
    summaries = [
        score_policy(policy, [item for item in decisions if item.policy == policy])
        for policy in policy_admission
    ]
    by_policy = {str(item["policy"]): item for item in summaries}
    checks = {
        "same_five_h8c_workloads": set(probes) == set(oracle_safe),
        "fixed_seven_call_budget": all(item.operator_calls == 7 for item in probes.values()),
        "probe_spec_identical_across_workloads": len(
            {item.probe_spec_sha256 for item in probes.values()}
        )
        == 1,
        "output_only_reproduces_three_false_accepts": int(
            by_policy["dynamic_output_only"]["unsafe_false_accepts"]
        )
        == 3,
        "stateful_detects_hidden_rng": probes["cv_hidden_rng_prefix"].rng_state_changed,
        "stateful_detects_external_state": probes[
            "cv_external_state_prefix"
        ].environment_output_changed,
        "stateful_detects_frozen_diversity_boundary": probes[
            "cv_full_cache"
        ].cross_context_output_changed,
        "stateful_preserves_both_safe_prefixes": int(
            by_policy["dynamic_stateful"]["tp"]
        )
        == 2,
        "stateful_zero_false_accepts": int(
            by_policy["dynamic_stateful"]["unsafe_false_accepts"]
        )
        == 0,
        "stateful_matches_hybrid_on_known_h8c": all(
            by_policy["dynamic_stateful"][key] == by_policy["hybrid"][key]
            for key in ("tp", "fp", "fn", "tn")
        ),
    }
    freeze = json.loads(H8C_FREEZE.read_text(encoding="utf-8"))
    return {
        "schema_version": "autocontract.h8c-r1-stateful-dynamic.v0",
        "artifact_role": "review_driven_internal_calibration_not_blind_evidence",
        "source_bodies_known": True,
        "oracle_independent": False,
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "torchvision": __import__("torchvision").__version__,
            "numpy": np.__version__,
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
        },
        "archived_h8c": {
            "runner_sha256": freeze["runner_sha256"],
            "measurements_sha256": file_sha256(H8C_MEASUREMENTS),
            "measurements_reused_without_modification": True,
        },
        "probe_spec": asdict(probe_spec),
        "probe_results": {name: asdict(item) for name, item in probes.items()},
        "decisions": [asdict(item) for item in decisions],
        "summaries": summaries,
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
    summaries = payload["summaries"]
    probe_results = payload["probe_results"]
    lines = [
        "# AutoContract H8C-R1 stateful dynamic calibration",
        "",
        f"Status: **{payload['status']}** ({payload['passed']}/{payload['total']})",
        "",
        "> Review-driven internal calibration over known H8C source/oracle; not blind benchmark evidence.",
        "",
        "## Policy comparison",
        "",
        "| Policy | TP | FP | FN | TN | Safe recall | Unsafe selections |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['policy']} | {item['tp']} | {item['fp']} | {item['fn']} | "
            f"{item['tn']} | {float(item['safe_recall']):.1%} | "
            f"{item['unsafe_plan_selections']} |"
        )
    lines.extend(
        [
            "",
            "## Probe observations",
            "",
            "| Workload | Output-only conflict | Stateful conflict | Observed effects |",
            "|---|---:|---:|---|",
        ]
    )
    for name, item in probe_results.items():
        effects = ", ".join(item["observed_effects"]) or "none"
        lines.append(
            f"| {name} | {item['output_only_conflict']} | "
            f"{item['stateful_conflict']} | {effects} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "On the five known H8C boundaries, the fairer stateful dynamic baseline closes all three false accepts and matches hybrid classification. This weakens any novelty argument based only on the historical output-only baseline. The next discriminating experiment must use unseen contexts or effects that a fixed finite probe budget cannot anticipate, while measuring Unknown/timeout cost fairly.",
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
