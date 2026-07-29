"""Cost ablation for H7J sealed atomic replay."""

from __future__ import annotations

import argparse
import copy
import csv
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(ROOT / "experiments"), str(REPO)]

import torch  # noqa: E402
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_atomic_replay as atomic  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402


def median_ms(callable_obj, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=50)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(909)
    source = pilot.build_pipeline()
    target = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 64, 64)
    with torch.no_grad():
        output = source(input_value)
    params = copy.deepcopy(source._params)
    proofs = auto.generate_leaf_proofs(source)
    policy = auto.policy_from_proofs(proofs)
    proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
    certificate = lineage.create_certificate(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=source,
        input_value=input_value,
        params=params,
        sample_id="cost/sample0",
    )
    sealed = atomic.SealedReplayRecord.seal(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=source,
        input_value=input_value,
        params=params,
        sample_id="cost/sample0",
        leaf_policy=policy,
        leaf_proof_set_sha256=proof_digest,
    )
    common = dict(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=target,
        input_value=input_value,
        params=params,
        sample_id="cost/sample0",
    )
    for _ in range(5):
        target(input_value, params=copy.deepcopy(params))
        sealed.atomic_apply(operator=target, input_value=input_value, sample_id="cost/sample0")
    operations = {
        "deepcopy_params": lambda: copy.deepcopy(params),
        "full_certificate_validate": lambda: lineage.validate_certificate(certificate, **common),
        "child_contract_compose": lambda: lineage.compose_child_contracts(target, params, policy),
        "params_digest": lambda: lineage.digest_payload(params),
        "output_digest": lambda: lineage.digest_payload(output),
        "direct_replay_no_copy": lambda: target(input_value, params=params),
        "direct_replay_with_copy": lambda: target(input_value, params=copy.deepcopy(params)),
        "sealed_atomic_replay": lambda: sealed.atomic_apply(operator=target, input_value=input_value, sample_id="cost/sample0"),
    }
    rows = [
        {"operation": name, "median_ms": median_ms(callable_obj, args.iterations), "iterations": args.iterations}
        for name, callable_obj in operations.items()
    ]
    baseline = next(float(row["median_ms"]) for row in rows if row["operation"] == "direct_replay_no_copy")
    for row in rows:
        row["relative_to_direct"] = float(row["median_ms"]) / baseline
    with (OUT / "autocontract_h7j_cost_ablation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    atomic_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "sealed_atomic_replay")
    copy_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "deepcopy_params")
    validate_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "full_certificate_validate")
    compose_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "child_contract_compose")
    params_hash_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "params_digest")
    output_hash_ms = next(float(row["median_ms"]) for row in rows if row["operation"] == "output_digest")
    report = "\n".join(
        [
            "# H7J sealed atomic replay cost ablation",
            "",
            f"Iterations per median: {args.iterations}; direct replay baseline: {baseline:.3f} ms; sealed atomic: {atomic_ms:.3f} ms ({atomic_ms / baseline:.3f}x).",
            "",
            "| Operation | Median ms | Relative to direct replay |",
            "|---|---:|---:|",
            *[f"| {row['operation']} | {row['median_ms']:.3f} | {row['relative_to_direct']:.3f}x |" for row in rows],
            "",
            f"Standalone bookkeeping sum (copy + validate + compose + two params hashes + output hash): "
            f"{copy_ms + validate_ms + compose_ms + 2 * params_hash_ms + output_hash_ms:.3f} ms.",
            "The sum is diagnostic rather than additive ground truth because full validation repeats several hashes.",
            "",
        ]
    )
    (OUT / "autocontract_h7j_cost_ablation.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
