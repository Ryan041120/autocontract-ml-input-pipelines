# AutoContract R3-P2 Kornia contract invalidation calibration

Status: **pass** (9/9 harness checks).

> Posthoc/adversarial calibration on the known H7I pipeline; not blind evidence.

## Policy comparison

| Policy | TP | FP | FN | TN | Invalidation recall | Benign preservation | Median ms | Calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dynamic_reprobe | 2 | 10 | 0 | 1 | 9.1% | 100.0% | 40.896 | 48 |
| output_snapshot_guard | 2 | 6 | 0 | 5 | 45.5% | 100.0% | 41.490 | 48 |
| lineage_v1 | 2 | 1 | 0 | 10 | 90.9% | 100.0% | 1.922 | 0 |
| measured_source_v2_candidate | 2 | 0 | 0 | 11 | 100.0% | 100.0% | 252.764 | 0 |

## Silent executable drift

- lineage_v1: ADMIT (false accept).
- measured_source_v2_candidate: REJECT; reasons=executable_source_mismatch.
- AST canonicalization control ignores formatting/comments and detects an executable expression change.

## Interpretation

The v1 lineage certificate is metadata/graph/record-bound, but it is not yet measured-executable-source-bound: a same-commit callable replacement can retain the operator repr and pass v1. Any stronger source-bound wording must be withdrawn. The v2 result is a candidate repair demonstrated on this known pipeline, not a frozen or cross-framework contribution.
