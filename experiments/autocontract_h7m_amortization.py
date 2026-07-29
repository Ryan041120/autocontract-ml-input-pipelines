"""H7L per-token versus H7M Merkle-batch authentication/registry amortization."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import autocontract_h7l_provenance_token as h7l  # noqa: E402
import autocontract_h7m_batch_lease as h7m  # noqa: E402


BATCH_SIZES = (1, 4, 16, 64)


def elapsed_ms(callable_obj):
    start = time.perf_counter_ns()
    result = callable_obj()
    return (time.perf_counter_ns() - start) / 1e6, result


def compact_batch_bytes(tickets: tuple[h7m.BatchTicket, ...]) -> int:
    root = len(h7l.canonical_bytes(asdict(tickets[0].root)))
    leaves_and_proofs = sum(
        len(h7l.canonical_bytes({"leaf": asdict(ticket.leaf), "proof": [asdict(node) for node in ticket.proof]}))
        for ticket in tickets
    )
    return root + leaves_and_proofs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    for size in BATCH_SIZES:
        expectations = h7m._expectations(size)
        h7l_registry = h7l.SqliteReplayRegistry(
            ROOT / "outputs" / f"autocontract_h7m_amort_h7l_N{size}.sqlite",
            reset=True,
            persistent_connections=True,
        )
        h7l_authority = h7l.ProvenanceAuthority.generate(h7l_registry)
        h7l_verifier = h7l.ProvenanceVerifier(h7l_authority.public_key_bytes(), h7l_registry)
        h7m_registry = h7m.SqliteBatchRegistry(
            ROOT / "outputs" / f"autocontract_h7m_amort_batch_N{size}.sqlite",
            reset=True,
            persistent_connections=True,
        )
        h7m_authority = h7m.BatchAuthority.generate()
        h7m_verifier = h7m.BatchVerifier(h7m_authority.public_key_bytes())

        warm_tokens = tuple(h7l_authority.issue(item) for item in expectations)
        for index, (token, expected) in enumerate(zip(warm_tokens, expectations)):
            h7l_verifier.verify_and_consume(token, expected, consumer_id=f"warm/h7l/{index}")
        warm_tickets = h7m_authority.issue_batch(expectations, batch_id=f"warm/h7m/N{size}")
        h7m_registry.register(warm_tickets[0].root)
        h7m_verifier.verify_batch(warm_tickets, expectations)
        warm_lease = h7m_registry.claim(warm_tickets[0].root.statement.batch_id, "warm/h7m")
        h7m_registry.commit(warm_lease, "0" * 64)

        for round_index in range(args.rounds):
            def issue_h7l():
                return tuple(h7l_authority.issue(item) for item in expectations)

            h7l_issue_ms, h7l_tokens = elapsed_ms(issue_h7l)
            batch_id = f"amort/N{size}/round{round_index}"

            def issue_h7m():
                tickets = h7m_authority.issue_batch(expectations, batch_id=batch_id)
                h7m_registry.register(tickets[0].root)
                return tickets

            h7m_issue_ms, h7m_tickets = elapsed_ms(issue_h7m)

            def consume_h7l():
                for index, (token, expected) in enumerate(zip(h7l_tokens, expectations)):
                    h7l_verifier.verify_and_consume(
                        token, expected, consumer_id=f"round{round_index}/h7l/{index}",
                    )

            h7l_consume_ms, _ = elapsed_ms(consume_h7l)

            def consume_h7m():
                root = h7m_verifier.verify_batch(h7m_tickets, expectations)
                lease = h7m_registry.claim(root.statement.batch_id, f"round{round_index}/h7m")
                return h7m_registry.commit(lease, f"{round_index:064x}"[-64:])

            h7m_consume_ms, commit = elapsed_ms(consume_h7m)
            h7l_wire_bytes = sum(len(token.to_json().encode("utf-8")) for token in h7l_tokens)
            h7m_wire_bytes = compact_batch_bytes(h7m_tickets)
            rows.append({
                "batch_size": size,
                "round": round_index,
                "h7l_issue_total_ms": h7l_issue_ms,
                "h7m_issue_total_ms": h7m_issue_ms,
                "h7l_consume_total_ms": h7l_consume_ms,
                "h7m_consume_total_ms": h7m_consume_ms,
                "h7l_issue_per_sample_ms": h7l_issue_ms / size,
                "h7m_issue_per_sample_ms": h7m_issue_ms / size,
                "h7l_consume_per_sample_ms": h7l_consume_ms / size,
                "h7m_consume_per_sample_ms": h7m_consume_ms / size,
                "h7m_over_h7l_consumer": h7m_consume_ms / h7l_consume_ms,
                "h7l_wire_bytes_total": h7l_wire_bytes,
                "h7m_wire_bytes_total": h7m_wire_bytes,
                "h7l_wire_bytes_per_sample": h7l_wire_bytes / size,
                "h7m_wire_bytes_per_sample": h7m_wire_bytes / size,
                "commit_idempotent": commit.idempotent,
            })
        h7l_registry.close()
        h7m_registry.close()

    import csv

    with (ROOT / "outputs" / "autocontract_h7m_amortization.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summaries: list[dict[str, object]] = []
    for size in BATCH_SIZES:
        selected = [item for item in rows if item["batch_size"] == size]
        summaries.append({
            "batch_size": size,
            "h7l_issue_per_sample_ms": statistics.median(float(item["h7l_issue_per_sample_ms"]) for item in selected),
            "h7m_issue_per_sample_ms": statistics.median(float(item["h7m_issue_per_sample_ms"]) for item in selected),
            "h7l_consume_per_sample_ms": statistics.median(float(item["h7l_consume_per_sample_ms"]) for item in selected),
            "h7m_consume_per_sample_ms": statistics.median(float(item["h7m_consume_per_sample_ms"]) for item in selected),
            "median_h7m_over_h7l_consumer": statistics.median(float(item["h7m_over_h7l_consumer"]) for item in selected),
            "h7l_wire_bytes_per_sample": statistics.median(float(item["h7l_wire_bytes_per_sample"]) for item in selected),
            "h7m_wire_bytes_per_sample": statistics.median(float(item["h7m_wire_bytes_per_sample"]) for item in selected),
            "rounds": len(selected),
        })
    with (ROOT / "outputs" / "autocontract_h7m_amortization_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    report = "\n".join([
        "# H7M Merkle-batch amortization",
        "",
        f"Independent rounds per batch size: {args.rounds}. H7L uses N signed/registered/consumed tokens; H7M uses one signed root plus one register, claim, and commit per batch.",
        "",
        "| N | H7L issue/sample | H7M issue/sample | H7L consume/sample | H7M consume/sample | H7M/H7L consumer | H7L bytes/sample | H7M bytes/sample |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[
            f"| {item['batch_size']} | {item['h7l_issue_per_sample_ms']:.3f} ms | "
            f"{item['h7m_issue_per_sample_ms']:.3f} ms | {item['h7l_consume_per_sample_ms']:.3f} ms | "
            f"{item['h7m_consume_per_sample_ms']:.3f} ms | {item['median_h7m_over_h7l_consumer']:.3f}x | "
            f"{item['h7l_wire_bytes_per_sample']:.0f} | {item['h7m_wire_bytes_per_sample']:.0f} |"
            for item in summaries
        ],
        "",
        "H7M uses two consumer-side durable transitions (claim and commit) per batch, so N=1 is expected to lose. "
        "The compact-wire calculation sends the signed root once per batch and leaf/proof data per sample.",
        "",
    ])
    (ROOT / "outputs" / "autocontract_h7m_amortization.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
