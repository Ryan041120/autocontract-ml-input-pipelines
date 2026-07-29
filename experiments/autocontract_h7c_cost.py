"""Cost sensitivity analysis for the H7C single-researcher timing proxy."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    protocol = json.loads((OUT / "autocontract_h7c_protocol.json").read_text(encoding="utf-8"))
    freeze = json.loads((OUT / "autocontract_h7c_freeze.json").read_text(encoding="utf-8"))
    review = json.loads((OUT / "autocontract_h7c_manual_review.json").read_text(encoding="utf-8"))
    holdout = list(csv.DictReader(OUT.joinpath("autocontract_h7c_holdout_summary.csv").open(encoding="utf-8")))[0]

    # .NET emitted seven fractional digits; Python datetime stores six.
    review_started = datetime.fromisoformat("2026-07-28T22:53:01.017866+08:00")
    review_finished = datetime.fromisoformat("2026-07-28T22:53:01.742814+08:00")
    n_holdout = len(review["units"])
    marginal_seconds = (review_finished - review_started).total_seconds() / n_holdout
    setup_seconds = float(freeze["adapter_setup_seconds"])
    rows: list[dict[str, object]] = []
    for estimator in ("mean", "median"):
        manual_seconds = float(review["aggregate"][f"{estimator}_seconds"])
        denominator = manual_seconds - marginal_seconds
        break_even = setup_seconds / denominator
        reduction_50 = 1 - (setup_seconds + 50 * marginal_seconds) / (50 * manual_seconds)
        rows.append(
            {
                "manual_estimator": estimator,
                "adapter_setup_seconds": setup_seconds,
                "manual_seconds_per_operator": manual_seconds,
                "adapter_marginal_seconds_per_operator": marginal_seconds,
                "break_even_operators": break_even,
                "projected_reduction_at_50": reduction_50,
                "break_even_gate_le_20": break_even <= protocol["cost_metrics"]["pilot_gate_break_even_operators"],
                "reduction_gate_ge_70pct": reduction_50 >= protocol["cost_metrics"]["pilot_gate_projected_reduction_at_50_operators"],
            }
        )
    write_csv(OUT / "autocontract_h7c_cost.csv", rows)
    break_even_robust = all(row["break_even_gate_le_20"] for row in rows)
    reduction_robust = all(row["reduction_gate_ge_70pct"] for row in rows)
    report = "\n".join(
        [
            "# AutoContract H7C adapter-cost sensitivity",
            "",
            f"Adapter setup proxy: {setup_seconds:.1f} s ({setup_seconds / 60:.2f} min).",
            f"Frozen analyzer run/review proxy: {marginal_seconds:.3f} s per operator.",
            "",
            "| Manual estimator | Manual s/op | Break-even operators | Reduction at 50 |",
            "|---|---:|---:|---:|",
            *[
                f"| {row['manual_estimator']} | {row['manual_seconds_per_operator']:.3f} | "
                f"{row['break_even_operators']:.2f} | {row['projected_reduction_at_50']:.1%} |"
                for row in rows
            ],
            "",
            f"Break-even <=20 is **{'ROBUST PASS' if break_even_robust else 'NOT ROBUST'}** across mean/median.",
            f"Projected reduction >=70% at 50 operators is **{'ROBUST PASS' if reduction_robust else 'SENSITIVE / INCONCLUSIVE'}**.",
            "",
            "This is not a human annotation-time result. The manual denominator is only source-confirmation time, "
            "and the adapter marginal value is automated execution latency, not a blinded human review. It is useful "
            "as an engineering lower-bound pilot only.",
            "",
            f"The frozen transfer gate remained **{'PASS' if holdout['h7c_transfer_gate_pass'] == 'True' else 'FAIL'}** "
            "and is not overridden by the cost calculation.",
            "",
        ]
    )
    (OUT / "autocontract_h7c_cost.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
