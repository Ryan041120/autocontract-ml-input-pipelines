# AutoContract H8A EffectV7 optimizer integration

> Scope: mechanism/runtime integration on the completed Kornia calibration pipeline. This is not a new blind holdout. The candidate preserves supplied-parameter replay semantics; it does not replace fresh sampling with replay.

EffectV7 leaf contracts: 3/3 admitted in replay context; 0/3 admitted in sampling context.
Composite contract: **ADMIT**; digest `c838d8468d22bf0700eb38681262d31a65de65e5ad794788403df83366a5f476`.

| Profile | Horizon | H7J atomic | H7K registered | Saving/call | Registration | Net benefit | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| B1x3x32x32 | 1 | 14.149 ms | 11.038 ms | 3.112 ms | 8.337 ms | -5.225 ms | REJECT |
| B1x3x32x32 | 10 | 14.149 ms | 11.038 ms | 3.112 ms | 8.337 ms | 22.780 ms | SELECT |
| B4x3x64x64 | 1 | 16.563 ms | 14.071 ms | 2.492 ms | 10.194 ms | -7.703 ms | REJECT |
| B4x3x64x64 | 10 | 16.563 ms | 14.071 ms | 2.492 ms | 10.194 ms | 14.721 ms | SELECT |
| B8x3x128x128 | 1 | 52.164 ms | 46.424 ms | 5.740 ms | 8.181 ms | -2.441 ms | REJECT |
| B8x3x128x128 | 10 | 52.164 ms | 46.424 ms | 5.740 ms | 8.181 ms | 49.220 ms | SELECT |

## Safety and integration checks

- h7h_freeze_verified: **PASS**
- leaf_proof_set_valid: **PASS**
- three_leaf_analyses_bound: **PASS**
- replay_context_all_admitted: **PASS**
- sample_context_all_rejected: **PASS**
- sample_rejection_mentions_sampling_or_proof_context: **PASS**
- composite_contract_admitted: **PASS**
- composite_contract_digest_bound: **PASS**
- tampered_leaf_proof_rejected: **PASS**
- three_real_profiles_loaded: **PASS**
- profile_savings_positive: **PASS**
- one_call_horizon_rejected_by_cost: **PASS**
- ten_call_horizon_selected: **PASS**
- semantic_reject_cannot_be_bypassed_by_large_benefit: **PASS**

Overall H8A integration gate: **PASS**.

## Interpretation

- EffectV7 and the bound leaf proofs authorize only `kornia.params_provided/replay_apply`; the same leaf operators fail closed on the fresh-sampling path.
- The profiler independently decides amortization: one call does not repay registration, while ten calls do for all three measured profiles.
- A large positive benefit cannot revive a semantic reject, preserving the optimizer-boundary invariant.
- The next independent work item is a real `cache_prefix` candidate, because registered replay improves safety-path amortization but does not yet establish end-to-end input-pipeline throughput gain.
