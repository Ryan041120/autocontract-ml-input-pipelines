"""Posthoc TOCTOU audit for H7I replay certificates (non-gating)."""

from __future__ import annotations

import copy
import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / ".research" / "semantics_safe_reconfiguration" / "h7h_corpus" / "kornia_repo"
OUT = ROOT / "outputs"
sys.path[:0] = [str(REPO), str(ROOT / "experiments")]

import torch  # noqa: E402
import kornia  # noqa: E402

import autocontract_h7i_lineage_certificate as cert  # noqa: E402
import autocontract_h7i_kornia_reconfiguration as pilot  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main() -> None:
    torch.manual_seed(707)
    source = pilot.build_pipeline()
    target = pilot.build_pipeline()
    input_value = torch.rand(4, 3, 32, 32)
    recorded = source(input_value)
    params = copy.deepcopy(source._params)
    certificate = cert.create_certificate(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=source,
        input_value=input_value,
        params=params,
        sample_id="toctou/sample0",
    )
    common = dict(
        framework="kornia",
        framework_version=kornia.__version__,
        repository_commit=pilot.COMMIT,
        operator=target,
        input_value=input_value,
        params=params,
        sample_id="toctou/sample0",
    )
    before = cert.validate_certificate(certificate, **common)
    immutable_snapshot = copy.deepcopy(params)
    with torch.no_grad():
        params[1].data["angle"][0] += 10.0
    after = cert.validate_certificate(certificate, **common)
    raced_output = target(input_value, params=params)
    snapshot_output = target(input_value, params=immutable_snapshot)
    rows = [
        {
            "scenario": "validate_then_mutate_then_apply_shared_record",
            "pre_validation": before.decision,
            "post_mutation_validation": after.decision,
            "output_matches_recorded": torch.equal(recorded, raced_output),
            "interpretation": "TOCTOU counterexample: prior admit is stale at use",
        },
        {
            "scenario": "validate_snapshot_then_mutate_original_then_apply_snapshot",
            "pre_validation": before.decision,
            "post_mutation_validation": "not_needed_for_snapshot",
            "output_matches_recorded": torch.equal(recorded, snapshot_output),
            "interpretation": "immutable snapshot preserves validated bytes",
        },
    ]
    write_csv(OUT / "autocontract_h7i_posthoc_toctou.csv", rows)
    report = "\n".join(
        [
            "# H7I posthoc TOCTOU audit (non-gating)",
            "",
            f"Pre-mutation certificate decision: {before.decision}.",
            f"Post-mutation certificate decision: {after.decision} ({';'.join(after.reasons)}).",
            f"Shared mutated record preserves output: {torch.equal(recorded, raced_output)}.",
            f"Immutable validated snapshot preserves output: {torch.equal(recorded, snapshot_output)}.",
            "",
            "The certificate is sound only if the validated parameter bytes are the bytes used by apply. "
            "A separate validate call followed by mutable shared-record use has a TOCTOU gap. "
            "The next design must use an immutable snapshot, sealed buffer, or atomic validate-and-apply boundary.",
            "",
        ]
    )
    (OUT / "autocontract_h7i_posthoc_toctou.md").write_text(report, encoding="utf-8")
    print(report)
    if before.decision != "admit" or after.decision != "reject" or torch.equal(recorded, raced_output) or not torch.equal(recorded, snapshot_output):
        raise RuntimeError("TOCTOU audit did not exhibit the expected contrast")


if __name__ == "__main__":
    main()
