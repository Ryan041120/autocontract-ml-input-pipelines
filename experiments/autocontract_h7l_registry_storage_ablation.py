"""Compare H7L SQLite registry costs on workspace and local-temp storage."""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import autocontract_h7l_provenance_token as provenance  # noqa: E402


def expectation() -> provenance.ProvenanceExpectation:
    subject = provenance.SubjectClaim("primary", "17", "a" * 64)
    return provenance.ProvenanceExpectation(
        run_id="storage/run0",
        replay_sample_id="storage/sample17",
        dataset_id="storage-dataset",
        dataset_revision="rev0",
        split="train",
        dataset_manifest_sha256=provenance.dataset_manifest_digest({"17": subject.content_sha256}),
        epoch=1,
        sampler_context_sha256="b" * 64,
        subjects=(subject,),
        operator_path="train/augment",
        registration_sha256="c" * 64,
        input_content_sha256=subject.content_sha256,
    )


def timed(callable_obj, iterations: int) -> float:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter_ns()
        callable_obj()
        samples.append((time.perf_counter_ns() - start) / 1e6)
    return statistics.median(samples)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()
    rng = random.Random(20260804)
    expected = expectation()
    with tempfile.TemporaryDirectory(prefix="autocontract-h7l-storage-") as temp_directory:
        paths = {
            "workspace_onedrive": ROOT / "outputs" / "autocontract_h7l_storage_workspace.sqlite",
            "local_temp": Path(temp_directory) / "registry.sqlite",
        }
        registries = {
            name: provenance.SqliteReplayRegistry(path, reset=True, persistent_connections=True)
            for name, path in paths.items()
        }
        authorities = {
            name: provenance.ProvenanceAuthority.generate(registry)
            for name, registry in registries.items()
        }
        consume_tokens = {
            name: iter([authorities[name].issue(expected) for _ in range(args.rounds * args.iterations)])
            for name in paths
        }
        rows: list[dict[str, object]] = []
        for round_index in range(args.rounds):
            order = list(paths)
            rng.shuffle(order)
            for name in order:
                authority = authorities[name]
                registry = registries[name]
                issue_ms = timed(lambda: authority.issue(expected), args.iterations)

                def consume_one() -> None:
                    token = next(consume_tokens[name])
                    registry.consume(
                        token.token_sha256,
                        provenance.sha256_bytes(provenance.payload_bytes(token.payload)),
                        f"{name}/{round_index}",
                    )

                consume_ms = timed(consume_one, args.iterations)
                rows.append({
                    "round": round_index,
                    "order": "->".join(order),
                    "storage": name,
                    "iterations": args.iterations,
                    "issue_register_ms": issue_ms,
                    "consume_ms": consume_ms,
                })
        summaries: list[dict[str, object]] = []
        for name in paths:
            selected = [item for item in rows if item["storage"] == name]
            summaries.append({
                "storage": name,
                "median_issue_register_ms": statistics.median(float(item["issue_register_ms"]) for item in selected),
                "median_consume_ms": statistics.median(float(item["consume_ms"]) for item in selected),
                "rounds": len(selected),
            })
        for registry in registries.values():
            registry.close()

    write_csv(ROOT / "outputs" / "autocontract_h7l_registry_storage_ablation.csv", rows)
    write_csv(ROOT / "outputs" / "autocontract_h7l_registry_storage_ablation_summary.csv", summaries)
    workspace = next(item for item in summaries if item["storage"] == "workspace_onedrive")
    local = next(item for item in summaries if item["storage"] == "local_temp")
    report = "\n".join([
        "# H7L registry storage ablation",
        "",
        f"Randomized rounds: {args.rounds}; operations per within-round median: {args.iterations}; persistent connection per registry.",
        "",
        "| Storage | Issue+register | Consume | Rounds |",
        "|---|---:|---:|---:|",
        *[
            f"| {item['storage']} | {item['median_issue_register_ms']:.3f} ms | "
            f"{item['median_consume_ms']:.3f} ms | {item['rounds']} |"
            for item in summaries
        ],
        "",
        f"Workspace/local consume ratio: {workspace['median_consume_ms'] / local['median_consume_ms']:.3f}x.",
        "The comparison isolates storage placement, not SQLite versus alternative registry architectures.",
        "",
    ])
    (ROOT / "outputs" / "autocontract_h7l_registry_storage_ablation.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
