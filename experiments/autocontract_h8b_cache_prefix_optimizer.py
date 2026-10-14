"""H8B: content-bound cache-prefix contract and horizon-aware optimizer pilot.

The H5 performance tables are reused retrospectively. H8B adds the cache-key
and invalidation bindings that the legacy sidecar lacked; it does not relabel
the historical H5 run as a preregistered experiment.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import inspect
import json
import math
import sys
import tempfile
import textwrap
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import torch
import torchvision
from torchvision.io import ImageReadMode, read_image

import autocontract_h5_jpeg_dataloader as h5a
import autocontract_optimizer_boundary as boundary
import autocontract_stateless_benchmark as stateless


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
H5A_PROFILE = OUT / "autocontract_h5_jpeg_workers.csv"
H5B_TRAINING = OUT / "autocontract_h5b_training.csv"
H5B_DECISIONS = OUT / "autocontract_h5b_decisions.json"
SAMPLES = 600
EXPORT_SIZE = 224
JPEG_QUALITY = 92
MEASURED_EPOCHS = 4


@dataclass(frozen=True)
class PrefixAnalysis:
    resolved: bool
    calls: tuple[str, ...]
    reasons: tuple[str, ...]
    deterministic: bool
    rng_sources: tuple[str, ...]
    external_reads: tuple[str, ...]
    state_writes: tuple[str, ...]
    input_cardinality: str
    output_cardinality: str
    sample_identity: str
    source_sha256: str
    contract_sha256: str


@dataclass(frozen=True)
class SuffixContract:
    rng_address: tuple[str, ...]
    stable_operator_ids: tuple[str, ...]
    source_sha256: str
    contract_sha256: str


@dataclass(frozen=True)
class CacheArtifactProof:
    schema_version: str
    dataset_manifest_sha256: str
    prefix_contract_sha256: str
    suffix_contract_sha256: str
    cache_content_sha256: str
    cache_bytes: int
    entry_key: str
    sample_count: int
    output_shape: tuple[int, ...]
    output_dtype: str
    torch_version: str
    torchvision_version: str
    audit_samples: int
    audit_matches: int
    proof_sha256: str


@dataclass(frozen=True)
class CachePlanDecision:
    candidate: boundary.RewriteCandidate
    contract: boundary.ContractVerdict
    workers: int
    cache_state: str
    horizon_epochs: int
    predicted_saving_per_epoch_s: float
    build_cost_s: float
    predicted_net_benefit_s: float
    selected: bool
    oracle_selected: bool
    decision_correct: bool
    raw_runtime_s: float
    candidate_runtime_s: float
    oracle_runtime_s: float
    benefit_coverage: float | None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def function_source(function: object) -> str:
    return textwrap.dedent(inspect.getsource(function))


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return "<dynamic>"


def analyze_prefix() -> PrefixAnalysis:
    source = function_source(stateless.stateless_prefix)
    tree = ast.parse(source)
    calls = tuple(
        sorted(
            {
                call_name(node.func)
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            }
        )
    )
    trusted = {"F.gaussian_blur", "F.resize"}
    unknown = tuple(name for name in calls if name not in trusted)
    lowered = source.lower()
    rng_tokens = tuple(
        token
        for token in ("torch.rand", "random.", "np.random", "numpy.random")
        if token in lowered
    )
    external = tuple(
        token for token in ("open(", "read_image", "os.environ", "getenv(") if token in lowered
    )
    state_writes = tuple(
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    )
    reasons = tuple(
        [*(f"unresolved_call:{name}" for name in unknown)]
        + (["rng_in_prefix"] if rng_tokens else [])
        + (["external_read_in_prefix"] if external else [])
        + (["state_write_in_prefix"] if state_writes else [])
    )
    source_digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    payload = {
        "schema": "autocontract.cache-prefix-effect.v0",
        "function": "autocontract_stateless_benchmark.stateless_prefix",
        "source_sha256": source_digest,
        "calls": calls,
        "trusted_registry": {
            "F.gaussian_blur": "deterministic,pure,one_to_one",
            "F.resize": "deterministic,pure,one_to_one",
        },
        "configuration": {"kernel_size": [9, 9], "sigma": [1.4, 1.4], "size": [96, 104], "antialias": True},
        "torch_version": torch.__version__,
        "torchvision_version": torchvision.__version__,
        "input_cardinality": "one",
        "output_cardinality": "one",
        "sample_identity": "preserve",
        "reasons": reasons,
    }
    return PrefixAnalysis(
        resolved=not reasons,
        calls=calls,
        reasons=reasons,
        deterministic=not rng_tokens,
        rng_sources=rng_tokens,
        external_reads=external,
        state_writes=state_writes,
        input_cardinality="one",
        output_cardinality="one",
        sample_identity="preserve",
        source_sha256=source_digest,
        contract_sha256=boundary.digest(payload),
    )


def suffix_contract() -> SuffixContract:
    functions = (
        stateless.stateless_suffix,
        stateless.stateless_hflip,
        stateless.stateless_crop,
        stateless.stateless_color_jitter,
        stateless.counter_key,
        stateless.uniform01,
        stateless.uniform,
        stateless.randint,
        stateless.random_order,
    )
    combined = "\n".join(function_source(function) for function in functions)
    source_digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    stable_ids = ("random_hflip", "random_crop", "color_jitter")
    missing = [name for name in stable_ids if name not in stateless.OP_KEYS]
    if missing:
        raise RuntimeError("suffix stable operator IDs are missing: " + ",".join(missing))
    address = ("base_seed", "epoch", "sample_id", "stable_operator_id", "draw_index")
    payload = {
        "schema": "autocontract.cache-suffix-rng.v0",
        "source_sha256": source_digest,
        "rng_address": address,
        "stable_operator_ids": stable_ids,
        "operator_keys": {name: stateless.OP_KEYS[name] for name in stable_ids},
    }
    return SuffixContract(address, stable_ids, source_digest, boundary.digest(payload))


def dataset_manifest(jpeg_root: Path) -> tuple[list[dict[str, object]], str]:
    manifest = h5a.imagefolder_manifest(jpeg_root, SAMPLES)
    entries: list[dict[str, object]] = []
    for sample_id, (raw_path, label) in enumerate(manifest):
        path = Path(raw_path)
        entries.append(
            {
                "sample_id": sample_id,
                "relative_path": path.relative_to(jpeg_root).as_posix(),
                "label": label,
                "bytes": path.stat().st_size,
                "content_sha256": file_sha256(path),
            }
        )
    return entries, boundary.digest(entries)


def audit_cache(
    jpeg_root: Path,
    cache_path: Path,
    sample_ids: tuple[int, ...],
) -> list[dict[str, object]]:
    manifest = h5a.imagefolder_manifest(jpeg_root, SAMPLES)
    cache = np.memmap(
        cache_path,
        dtype=np.uint8,
        mode="r",
        shape=(SAMPLES, *h5a.PREFIX_SHAPE),
    )
    rows: list[dict[str, object]] = []
    with torch.inference_mode():
        for sample_id in sample_ids:
            source = read_image(manifest[sample_id][0], mode=ImageReadMode.RGB)
            recomputed = stateless.stateless_prefix(source)
            cached = torch.from_numpy(np.array(cache[sample_id], copy=True))
            rows.append(
                {
                    "sample_id": sample_id,
                    "match": torch.equal(recomputed, cached),
                    "recomputed_sha256": hashlib.sha256(recomputed.numpy().tobytes()).hexdigest(),
                    "cached_sha256": hashlib.sha256(cached.numpy().tobytes()).hexdigest(),
                }
            )
    del cache
    return rows


def proof_digest(proof: CacheArtifactProof) -> str:
    return boundary.digest(asdict(replace(proof, proof_sha256="")))


def validate_proof(
    proof: CacheArtifactProof,
    *,
    dataset_sha256: str,
    prefix_sha256: str,
    suffix_sha256: str,
    cache_sha256: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if proof.schema_version != "autocontract.cache-artifact.v1":
        reasons.append("cache_schema_mismatch")
    if proof.dataset_manifest_sha256 != dataset_sha256:
        reasons.append("dataset_manifest_mismatch")
    if proof.prefix_contract_sha256 != prefix_sha256:
        reasons.append("prefix_contract_mismatch")
    if proof.suffix_contract_sha256 != suffix_sha256:
        reasons.append("suffix_rng_contract_mismatch")
    if proof.cache_content_sha256 != cache_sha256:
        reasons.append("cache_content_mismatch")
    expected_bytes = SAMPLES * math.prod(h5a.PREFIX_SHAPE)
    if proof.cache_bytes != expected_bytes:
        reasons.append("cache_size_mismatch")
    if proof.entry_key != "dataset_manifest_sha256+sample_id":
        reasons.append("cache_entry_key_incomplete")
    if proof.sample_count != SAMPLES:
        reasons.append("sample_count_mismatch")
    if proof.output_shape != h5a.PREFIX_SHAPE or proof.output_dtype != "uint8":
        reasons.append("cache_output_schema_mismatch")
    if proof.torch_version != torch.__version__ or proof.torchvision_version != torchvision.__version__:
        reasons.append("runtime_version_mismatch")
    if proof.audit_samples <= 0 or proof.audit_matches != proof.audit_samples:
        reasons.append("cache_recomputation_audit_failed")
    if proof.proof_sha256 != proof_digest(proof):
        reasons.append("cache_proof_digest_mismatch")
    return tuple(reasons)


def legacy_metadata_reasons(metadata: dict[str, object]) -> tuple[str, ...]:
    required = {
        "dataset_manifest_sha256",
        "prefix_contract_sha256",
        "suffix_contract_sha256",
        "cache_content_sha256",
        "entry_key",
        "torch_version",
        "torchvision_version",
        "proof_sha256",
    }
    return tuple(f"missing:{name}" for name in sorted(required - set(metadata)))


def cache_contract_verdict(
    prefix: PrefixAnalysis,
    suffix: SuffixContract,
    proof: CacheArtifactProof,
    proof_reasons: tuple[str, ...],
) -> boundary.ContractVerdict:
    reasons = list(prefix.reasons)
    if suffix.rng_address != ("base_seed", "epoch", "sample_id", "stable_operator_id", "draw_index"):
        reasons.append("unstable_suffix_rng_address")
    reasons.extend(proof_reasons)
    payload = {
        "schema": "autocontract.cache-prefix-verdict.v0",
        "prefix": asdict(prefix),
        "suffix": asdict(suffix),
        "artifact": asdict(proof),
        "reasons": reasons,
    }
    return boundary.ContractVerdict(
        policy="cache_contract",
        admitted=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        contract_sha256=boundary.digest(payload),
        evidence_class="source_registry_plus_content_addressed_cache_artifact",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def decision_for_profile(
    row: dict[str, str],
    contract: boundary.ContractVerdict,
    cache_state: str,
    horizon: int,
) -> CachePlanDecision:
    workers = int(row["workers"])
    samples = SAMPLES
    raw_epoch = samples / float(row["uncached_steady_samples_per_s"])
    cached_epoch = samples / float(row["cached_steady_samples_per_s"])
    saving = raw_epoch - cached_epoch
    build = float(row["cache_build_time_s"]) if cache_state == "cold" else 0.0
    net = horizon * saving - build
    candidate = boundary.RewriteCandidate(
        candidate_id=f"cache-prefix:h5a:w{workers}:{cache_state}:h{horizon}",
        rewrite_kind="cache_prefix",
        pipeline_id="h5-jpeg-stateless-prefix",
        position=0,
        operators=("jpeg_decode", "gaussian_blur", "resize"),
        context_id=f"workers={workers}/cache={cache_state}/epochs={horizon}",
        optimizer_score=net,
    )
    selected = contract.admitted and net > 0
    raw_runtime = float(row["uncached_median_s"])
    cached_runtime = float(row["cached_median_s"]) + build
    oracle_selected = cached_runtime < raw_runtime
    auto_runtime = cached_runtime if selected else raw_runtime
    oracle_runtime = min(raw_runtime, cached_runtime)
    oracle_gain = raw_runtime - oracle_runtime
    coverage = (raw_runtime - auto_runtime) / oracle_gain if oracle_gain > 0 else None
    return CachePlanDecision(
        candidate,
        contract,
        workers,
        cache_state,
        horizon,
        saving,
        build,
        net,
        selected,
        oracle_selected,
        selected == oracle_selected,
        raw_runtime,
        cached_runtime,
        oracle_runtime,
        coverage,
    )


def training_decision(
    h5a_row: dict[str, str],
    training_rows: list[dict[str, str]],
    historical: dict[str, object],
    contract: boundary.ContractVerdict,
    cache_state: str,
) -> CachePlanDecision:
    workers = int(historical["workers"])
    horizon = int(historical["epochs"])
    raw_epoch = SAMPLES / float(h5a_row["uncached_steady_samples_per_s"])
    cached_epoch = SAMPLES / float(h5a_row["cached_steady_samples_per_s"])
    saving = raw_epoch - cached_epoch
    build = float(historical["cache_build_time_s"]) if cache_state == "cold" else 0.0
    net = horizon * saving - build
    by_policy = {row["policy"]: row for row in training_rows}
    raw_runtime = float(by_policy["uncached"]["median_runtime_s"])
    cached_runtime = float(by_policy["cached"]["median_runtime_s"]) + build
    selected = contract.admitted and net > 0
    oracle_selected = cached_runtime < raw_runtime
    auto_runtime = cached_runtime if selected else raw_runtime
    oracle_runtime = min(raw_runtime, cached_runtime)
    oracle_gain = raw_runtime - oracle_runtime
    coverage = (raw_runtime - auto_runtime) / oracle_gain if oracle_gain > 0 else None
    candidate = boundary.RewriteCandidate(
        candidate_id=f"cache-prefix:h5b:w{workers}:{cache_state}:h{horizon}",
        rewrite_kind="cache_prefix",
        pipeline_id="h5b-resnet18-training",
        position=0,
        operators=("jpeg_decode", "gaussian_blur", "resize"),
        context_id=f"workers={workers}/cache={cache_state}/epochs={horizon}",
        optimizer_score=net,
    )
    return CachePlanDecision(
        candidate,
        contract,
        workers,
        cache_state,
        horizon,
        saving,
        build,
        net,
        selected,
        oracle_selected,
        selected == oracle_selected,
        raw_runtime,
        cached_runtime,
        oracle_runtime,
        coverage,
    )


def decision_row(scope: str, item: CachePlanDecision) -> dict[str, object]:
    return {
        "scope": scope,
        "candidate_id": item.candidate.candidate_id,
        "workers": item.workers,
        "cache_state": item.cache_state,
        "horizon_epochs": item.horizon_epochs,
        "semantic_admitted": item.contract.admitted,
        "predicted_saving_per_epoch_s": item.predicted_saving_per_epoch_s,
        "build_cost_s": item.build_cost_s,
        "predicted_net_benefit_s": item.predicted_net_benefit_s,
        "selected": item.selected,
        "oracle_selected": item.oracle_selected,
        "decision_correct": item.decision_correct,
        "raw_runtime_s": item.raw_runtime_s,
        "candidate_runtime_s": item.candidate_runtime_s,
        "oracle_runtime_s": item.oracle_runtime_s,
        "benefit_coverage": "not_applicable" if item.benefit_coverage is None else item.benefit_coverage,
        "contract_sha256": item.contract.contract_sha256,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
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
    parser.add_argument("--audit-samples", type=int, default=24)
    args = parser.parse_args()

    jpeg_root = args.data_root / f"skimage_jpeg_n{SAMPLES}_s{EXPORT_SIZE}_q{JPEG_QUALITY}"
    cache_path = args.data_root / f"skimage_prefix_n{SAMPLES}_s{EXPORT_SIZE}_{h5a.PREFIX_SHAPE[1]}x{h5a.PREFIX_SHAPE[2]}.uint8.memmap"
    legacy_path = cache_path.with_suffix(".json")
    for path in (jpeg_root, cache_path, legacy_path, H5A_PROFILE, H5B_TRAINING, H5B_DECISIONS):
        if not path.exists():
            raise FileNotFoundError(path)

    prefix = analyze_prefix()
    suffix = suffix_contract()
    entries, manifest_digest = dataset_manifest(jpeg_root)
    cache_digest = file_sha256(cache_path)
    audit_count = min(max(args.audit_samples, 1), SAMPLES)
    sample_ids = tuple(sorted({round(index * (SAMPLES - 1) / max(audit_count - 1, 1)) for index in range(audit_count)}))
    audit_rows = audit_cache(jpeg_root, cache_path, sample_ids)
    provisional = CacheArtifactProof(
        schema_version="autocontract.cache-artifact.v1",
        dataset_manifest_sha256=manifest_digest,
        prefix_contract_sha256=prefix.contract_sha256,
        suffix_contract_sha256=suffix.contract_sha256,
        cache_content_sha256=cache_digest,
        cache_bytes=cache_path.stat().st_size,
        entry_key="dataset_manifest_sha256+sample_id",
        sample_count=SAMPLES,
        output_shape=h5a.PREFIX_SHAPE,
        output_dtype="uint8",
        torch_version=torch.__version__,
        torchvision_version=torchvision.__version__,
        audit_samples=len(audit_rows),
        audit_matches=sum(bool(row["match"]) for row in audit_rows),
        proof_sha256="",
    )
    proof = replace(provisional, proof_sha256=proof_digest(provisional))
    proof_reasons = validate_proof(
        proof,
        dataset_sha256=manifest_digest,
        prefix_sha256=prefix.contract_sha256,
        suffix_sha256=suffix.contract_sha256,
        cache_sha256=cache_digest,
    )
    contract = cache_contract_verdict(prefix, suffix, proof, proof_reasons)

    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    legacy_reasons = legacy_metadata_reasons(legacy)
    mutations = {
        "dataset": replace(proof, dataset_manifest_sha256="0" * 64),
        "prefix": replace(proof, prefix_contract_sha256="0" * 64),
        "suffix": replace(proof, suffix_contract_sha256="0" * 64),
        "cache": replace(proof, cache_content_sha256="0" * 64),
        "shape": replace(proof, output_shape=(3, 95, 104)),
        "entry_key": replace(proof, entry_key="sample_id"),
    }
    mutation_rejections = {
        name: validate_proof(
            mutated,
            dataset_sha256=manifest_digest,
            prefix_sha256=prefix.contract_sha256,
            suffix_sha256=suffix.contract_sha256,
            cache_sha256=cache_digest,
        )
        for name, mutated in mutations.items()
    }

    h5a_rows = read_csv(H5A_PROFILE)
    profile_decisions = [
        decision_for_profile(row, contract, cache_state, MEASURED_EPOCHS)
        for row in h5a_rows
        for cache_state in ("cold", "warm")
    ]
    training_rows = read_csv(H5B_TRAINING)
    historical = json.loads(H5B_DECISIONS.read_text(encoding="utf-8"))
    h5a_workers = next(row for row in h5a_rows if int(row["workers"]) == int(historical["workers"]))
    training_decisions = [
        training_decision(h5a_workers, training_rows, historical, contract, state)
        for state in ("cold", "warm")
    ]
    positive_training = [item for item in training_decisions if item.benefit_coverage is not None]
    mean_benefit_coverage = (
        sum(float(item.benefit_coverage) for item in positive_training) / len(positive_training)
        if positive_training
        else 0.0
    )

    rejected_contract = replace(
        contract,
        admitted=False,
        reasons=("test_semantic_reject",),
        contract_sha256=boundary.digest("h8b-reject"),
    )
    bypass = training_decision(h5a_workers, training_rows, historical, rejected_contract, "warm")
    checks = {
        "prefix_source_contract_resolved": prefix.resolved,
        "prefix_calls_only_trusted_deterministic_ops": set(prefix.calls) == {"F.gaussian_blur", "F.resize"},
        "suffix_rng_address_stable": suffix.rng_address == ("base_seed", "epoch", "sample_id", "stable_operator_id", "draw_index"),
        "legacy_metadata_rejected": bool(legacy_reasons),
        "legacy_same_run_dynamic_trace_was_one": all(float(row["trace_match"]) == 1.0 for row in h5a_rows),
        "content_addressed_proof_valid": not proof_reasons,
        "cache_recomputation_audit_all_match": proof.audit_matches == proof.audit_samples,
        "all_invalidation_mutations_rejected": all(bool(reasons) for reasons in mutation_rejections.values()),
        "cache_contract_admitted": contract.admitted,
        "h5a_profile_decisions_match_oracle": all(item.decision_correct for item in profile_decisions),
        "h5b_cold_decision_matches_oracle": training_decisions[0].decision_correct and not training_decisions[0].selected,
        "h5b_warm_decision_matches_oracle": training_decisions[1].decision_correct and training_decisions[1].selected,
        "h5b_warm_human_oracle_benefit_coverage_one": math.isclose(mean_benefit_coverage, 1.0),
        "semantic_reject_cannot_be_bypassed_by_positive_cost": not bypass.selected,
    }
    all_checks_pass = all(checks.values())

    manifest_payload = {
        "schema_version": "autocontract.dataset-manifest.v1",
        "dataset": "H5 skimage-derived JPEG pilot",
        "root_marker": json.loads((jpeg_root / "_READY.json").read_text(encoding="utf-8")),
        "entries": entries,
        "manifest_sha256": manifest_digest,
    }
    (OUT / "autocontract_h8b_dataset_manifest.json").write_text(
        json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
    )
    contract_payload = {
        "schema_version": "autocontract.cache-prefix-contract.v1",
        "claim_boundary": "retrospective binding of H5 artifact; not preregistered H8B performance",
        "prefix_analysis": asdict(prefix),
        "suffix_contract": asdict(suffix),
        "artifact_proof": asdict(proof),
        "artifact_validation_reasons": list(proof_reasons),
        "contract_verdict": asdict(contract),
        "legacy_metadata_reasons": list(legacy_reasons),
        "source_files": {
            "h5a_sha256": file_sha256(Path(h5a.__file__)),
            "stateless_sha256": file_sha256(Path(stateless.__file__)),
            "h5a_profile_sha256": file_sha256(H5A_PROFILE),
            "h5b_training_sha256": file_sha256(H5B_TRAINING),
            "h5b_decisions_sha256": file_sha256(H5B_DECISIONS),
        },
    }
    (OUT / "autocontract_h8b_cache_contract.json").write_text(
        json.dumps(contract_payload, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(OUT / "autocontract_h8b_cache_audit.csv", audit_rows)
    write_csv(
        OUT / "autocontract_h8b_profile_decisions.csv",
        [decision_row("H5a_profile", item) for item in profile_decisions],
    )
    write_csv(
        OUT / "autocontract_h8b_training_decisions.csv",
        [decision_row("H5b_training", item) for item in training_decisions],
    )
    selftest = {
        "protocol": "AutoContract H8B content-bound cache-prefix optimizer pilot",
        "claim_boundary": "retrospective H5 integration; not a new CUDA rerun",
        "contract_sha256": contract.contract_sha256,
        "dataset_manifest_sha256": manifest_digest,
        "cache_content_sha256": cache_digest,
        "legacy_metadata_reasons": list(legacy_reasons),
        "mutation_rejections": {name: list(reasons) for name, reasons in mutation_rejections.items()},
        "benefit_positive_training_workloads": len(positive_training),
        "mean_human_oracle_benefit_coverage": mean_benefit_coverage,
        "checks": checks,
        "all_checks_pass": all_checks_pass,
    }
    (OUT / "autocontract_h8b_selftest.json").write_text(
        json.dumps(selftest, indent=2) + "\n", encoding="utf-8"
    )

    cold, warm = training_decisions
    lines = [
        "# AutoContract H8B contract-carrying cache prefix",
        "",
        "> Scope: retrospective integration of the existing H5 pilot. H8B binds the current cache artifact after the historical performance run; it is not a preregistered CUDA rerun.",
        "",
        f"Prefix analysis: **{'RESOLVED' if prefix.resolved else 'UNKNOWN'}**; calls: {', '.join(prefix.calls)}.",
        f"Cache audit: {proof.audit_matches}/{proof.audit_samples} sampled entries exactly match recomputation.",
        f"Contract verdict: **{'ADMIT' if contract.admitted else 'REJECT'}**; digest `{contract.contract_sha256}`.",
        f"Legacy sidecar: **REJECT** ({len(legacy_reasons)} missing safety bindings) despite historical same-run trace match=1.0.",
        "",
        "## H5b held-workload decision",
        "",
        "| Cache state | Predicted net benefit | AutoContract | Measured oracle | Runtime if cached | Raw runtime | Benefit coverage |",
        "|---|---:|---|---|---:|---:|---:|",
        f"| cold | {cold.predicted_net_benefit_s:.3f} s | {'CACHE' if cold.selected else 'NO CACHE'} | {'CACHE' if cold.oracle_selected else 'NO CACHE'} | {cold.candidate_runtime_s:.3f} s | {cold.raw_runtime_s:.3f} s | n/a |",
        f"| warm | {warm.predicted_net_benefit_s:.3f} s | {'CACHE' if warm.selected else 'NO CACHE'} | {'CACHE' if warm.oracle_selected else 'NO CACHE'} | {warm.candidate_runtime_s:.3f} s | {warm.raw_runtime_s:.3f} s | {float(warm.benefit_coverage):.1%} |",
        "",
        "## Checks",
        "",
        *[f"- {name}: **{'PASS' if passed else 'FAIL'}**" for name, passed in checks.items()],
        "",
        f"Overall H8B mechanism gate: **{'PASS' if all_checks_pass else 'FAIL'}**.",
        "",
        "## Interpretation",
        "",
        "- Same-run differential trace alone is insufficient for reusable caching; the legacy sidecar cannot detect dataset, prefix, suffix-RNG, or artifact drift.",
        "- The H5a profile predicts both H5b decisions correctly without using the H5b measured runtime as its score.",
        "- Warm H5b reaches 100% of measured human-oracle benefit, but the denominator contains only one benefit-positive workload and is therefore pilot evidence, not the RQ3 headline.",
        "- The next mainline task is a preregistered multi-workload cache benchmark that writes the contract before profiling/execution and includes at least one deliberately unsafe cache boundary.",
        "",
    ]
    report = "\n".join(lines)
    (OUT / "autocontract_h8b_cache_prefix_optimizer.md").write_text(report, encoding="utf-8")
    print(report)
    if not all_checks_pass:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
