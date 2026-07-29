"""Randomized paired and component performance study for H7L provenance."""

from __future__ import annotations

import argparse
import copy
import csv
import random
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

import autocontract_h7i_lineage_certificate as lineage  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402
import autocontract_h7j_auto_leaf_proofs as auto  # noqa: E402
import autocontract_h7l_bound_executor as bound  # noqa: E402
import autocontract_h7l_kornia_bound as runtime  # noqa: E402
import autocontract_h7l_provenance_token as provenance  # noqa: E402


PROFILES = ((1, 32), (4, 64), (8, 128))


def median_ms(callable_obj, iterations: int) -> tuple[float, list[float]]:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples), samples


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--component-iterations", type=int, default=30)
    args = parser.parse_args()
    torch.set_num_threads(1)
    rng = random.Random(20260803)
    paired_rows: list[dict[str, object]] = []
    component_rows: list[dict[str, object]] = []

    for batch, size in PROFILES:
        torch.manual_seed(3000 + batch + size)
        source = pilot.build_pipeline()
        input_value = torch.rand(batch, 3, size, size)
        with torch.no_grad():
            expected_output = source(input_value)
        params = copy.deepcopy(source._params)
        proofs = auto.generate_leaf_proofs(source)
        policy = auto.policy_from_proofs(proofs)
        proof_digest = lineage.digest_payload([asdict(proof) for proof in proofs])
        baseline = runtime.make_executor(source, input_value, params, policy, proof_digest)
        secured_executor = runtime.make_executor(source, input_value, params, policy, proof_digest)

        registry_path = OUT / f"autocontract_h7l_perf_B{batch}S{size}.sqlite"
        registry = provenance.SqliteReplayRegistry(
            registry_path, reset=True, persistent_connections=True,
        )
        authority = provenance.ProvenanceAuthority.generate(registry)
        verifier = provenance.ProvenanceVerifier(authority.public_key_bytes(), registry)
        expected = runtime.base_expectation(
            input_value, secured_executor.registration_receipt.registration_sha256,
        )
        secured = bound.ProvenanceBoundExecutor(secured_executor, verifier, expected)

        issue_median, issue_samples = median_ms(
            lambda: authority.issue(expected), args.component_iterations,
        )
        verify_token = authority.issue(expected)
        verify_median, verify_samples = median_ms(
            lambda: verifier.verify_claims(verify_token, expected), args.component_iterations,
        )
        consume_tokens = [authority.issue(expected) for _ in range(args.component_iterations)]
        consume_index = iter(enumerate(consume_tokens))

        def consume_one() -> None:
            index, token = next(consume_index)
            registry.consume(
                token.token_sha256,
                provenance.sha256_bytes(provenance.payload_bytes(token.payload)),
                f"component/{index}",
            )

        consume_median, consume_samples = median_ms(consume_one, args.component_iterations)
        seal_median, seal_samples = median_ms(
            lambda: lineage.digest_payload(bound.seal_input(input_value)),
            args.component_iterations,
        )
        for operation, median, samples in (
            ("issue_sign_and_register", issue_median, issue_samples),
            ("verify_signature_and_claims", verify_median, verify_samples),
            ("registry_consume", consume_median, consume_samples),
            ("seal_input_and_digest", seal_median, seal_samples),
        ):
            component_rows.append({
                "profile": f"B{batch}x3x{size}x{size}",
                "operation": operation,
                "median_ms": median,
                "mean_ms": statistics.mean(samples),
                "iterations": len(samples),
            })

        token_count = 5 + args.rounds * args.iterations
        paired_tokens = iter([authority.issue(expected) for _ in range(token_count)])
        consumer_sequence = 0

        def h7k_call():
            return baseline.apply(input_value=input_value, sample_id=runtime.SAMPLE_ID)

        def h7l_call():
            nonlocal consumer_sequence
            token = next(paired_tokens)
            consumer_sequence += 1
            return secured.apply(
                input_value=input_value,
                token=token,
                consumer_id=f"paired/{batch}/{size}/{consumer_sequence}",
            )

        with torch.no_grad():
            for _ in range(5):
                h7k_output, _ = h7k_call()
                h7l_output, _ = h7l_call()
                if not torch.equal(h7k_output, expected_output) or not torch.equal(h7l_output, expected_output):
                    raise RuntimeError("paired performance output mismatch")
            for round_index in range(args.rounds):
                order = ["h7k", "h7l"]
                rng.shuffle(order)
                timings: dict[str, float] = {}
                for operation in order:
                    callable_obj = h7k_call if operation == "h7k" else h7l_call
                    timings[operation], _ = median_ms(callable_obj, args.iterations)
                paired_rows.append({
                    "batch": batch,
                    "size": size,
                    "round": round_index,
                    "order": "->".join(order),
                    "iterations": args.iterations,
                    "h7k_minimal_ms": timings["h7k"],
                    "h7l_signed_registry_ms": timings["h7l"],
                    "h7l_over_h7k": timings["h7l"] / timings["h7k"],
                    "absolute_overhead_ms": timings["h7l"] - timings["h7k"],
                })

    write_csv(OUT / "autocontract_h7l_paired_performance.csv", paired_rows)
    write_csv(OUT / "autocontract_h7l_component_performance.csv", component_rows)
    summaries: list[dict[str, object]] = []
    for batch, size in PROFILES:
        selected = [item for item in paired_rows if item["batch"] == batch and item["size"] == size]
        ratios = [float(item["h7l_over_h7k"]) for item in selected]
        overheads = [float(item["absolute_overhead_ms"]) for item in selected]
        summaries.append({
            "profile": f"B{batch}x3x{size}x{size}",
            "median_h7l_over_h7k": statistics.median(ratios),
            "min_ratio": min(ratios),
            "max_ratio": max(ratios),
            "median_absolute_overhead_ms": statistics.median(overheads),
            "h7l_faster_rounds": sum(value < 1.0 for value in ratios),
            "rounds": len(ratios),
        })
    write_csv(OUT / "autocontract_h7l_paired_performance_summary.csv", summaries)
    all_ratios = [float(item["h7l_over_h7k"]) for item in paired_rows]
    component_lookup = {
        (str(item["profile"]), str(item["operation"])): float(item["median_ms"])
        for item in component_rows
    }
    report = "\n".join([
        "# H7L randomized paired and component performance",
        "",
        f"Profiles: {len(PROFILES)}; paired rounds/profile: {args.rounds}; calls/within-round median: {args.iterations}.",
        f"Overall median H7L/H7K ratio: {statistics.median(all_ratios):.3f}x; H7L faster rounds: {sum(value < 1.0 for value in all_ratios)}/{len(all_ratios)}.",
        "Token issuance is measured separately and excluded from consumer-path paired timing.",
        "",
        "| Profile | H7L/H7K | Range | Absolute overhead | H7L faster rounds |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| {item['profile']} | {item['median_h7l_over_h7k']:.3f}x | "
            f"{item['min_ratio']:.3f}-{item['max_ratio']:.3f}x | "
            f"{item['median_absolute_overhead_ms']:.3f} ms | {item['h7l_faster_rounds']}/{item['rounds']} |"
            for item in summaries
        ],
        "",
        "| Profile | Issue+register | Verify claims | Registry consume | Seal input+digest |",
        "|---|---:|---:|---:|---:|",
        *[
            f"| B{batch}x3x{size}x{size} | "
            f"{component_lookup[(f'B{batch}x3x{size}x{size}', 'issue_sign_and_register')]:.3f} ms | "
            f"{component_lookup[(f'B{batch}x3x{size}x{size}', 'verify_signature_and_claims')]:.3f} ms | "
            f"{component_lookup[(f'B{batch}x3x{size}x{size}', 'registry_consume')]:.3f} ms | "
            f"{component_lookup[(f'B{batch}x3x{size}x{size}', 'seal_input_and_digest')]:.3f} ms |"
            for batch, size in PROFILES
        ],
        "",
        "SQLite commits provide a durable cross-process baseline, not a claim of optimal registry design. "
        "Randomized order reduces systematic order bias but does not eliminate OS/filesystem noise.",
        "",
    ])
    (OUT / "autocontract_h7l_paired_performance.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
