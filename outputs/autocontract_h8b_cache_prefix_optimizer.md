# AutoContract H8B contract-carrying cache prefix

> Scope: retrospective integration of the existing H5 pilot. H8B binds the current cache artifact after the historical performance run; it is not a preregistered CUDA rerun.

Prefix analysis: **RESOLVED**; calls: F.gaussian_blur, F.resize.
Cache audit: 24/24 sampled entries exactly match recomputation.
Contract verdict: **ADMIT**; digest `f545cdbe367fc96307b8f5e561b7bf3e2ce1b4e324974e273e1435c352c30338`.
Legacy sidecar: **REJECT** (8 missing safety bindings) despite historical same-run trace match=1.0.

## H5b held-workload decision

| Cache state | Predicted net benefit | AutoContract | Measured oracle | Runtime if cached | Raw runtime | Benefit coverage |
|---|---:|---|---|---:|---:|---:|
| cold | -7.084 s | NO CACHE | NO CACHE | 25.113 s | 18.794 s | n/a |
| warm | 4.422 s | CACHE | CACHE | 13.608 s | 18.794 s | 100.0% |

## Checks

- prefix_source_contract_resolved: **PASS**
- prefix_calls_only_trusted_deterministic_ops: **PASS**
- suffix_rng_address_stable: **PASS**
- legacy_metadata_rejected: **PASS**
- legacy_same_run_dynamic_trace_was_one: **PASS**
- content_addressed_proof_valid: **PASS**
- cache_recomputation_audit_all_match: **PASS**
- all_invalidation_mutations_rejected: **PASS**
- cache_contract_admitted: **PASS**
- h5a_profile_decisions_match_oracle: **PASS**
- h5b_cold_decision_matches_oracle: **PASS**
- h5b_warm_decision_matches_oracle: **PASS**
- h5b_warm_human_oracle_benefit_coverage_one: **PASS**
- semantic_reject_cannot_be_bypassed_by_positive_cost: **PASS**

Overall H8B mechanism gate: **PASS**.

## Interpretation

- Same-run differential trace alone is insufficient for reusable caching; the legacy sidecar cannot detect dataset, prefix, suffix-RNG, or artifact drift.
- The H5a profile predicts both H5b decisions correctly without using the H5b measured runtime as its score.
- Warm H5b reaches 100% of measured human-oracle benefit, but the denominator contains only one benefit-positive workload and is therefore pilot evidence, not the RQ3 headline.
- The next mainline task is a preregistered multi-workload cache benchmark that writes the contract before profiling/execution and includes at least one deliberately unsafe cache boundary.
