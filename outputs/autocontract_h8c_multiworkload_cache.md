# AutoContract H8C registered multi-workload cache benchmark

> Internal calibration benchmark: protocol and runner were hash-frozen before the registered run, but source bodies and the oracle were not independently blinded.

Workloads: 5 (2 safe, 3 unsafe); domains: CV + audio; samples/workload: 48; epochs: 4; repeats: 3.

| Workload | Safe oracle | Raw | Build+cached | Net benefit | Trace match | Raw diversity | Cached diversity |
|---|---|---:|---:|---:|---|---:|---:|
| cv_safe_prefix | True | 1.306s | 0.815s | 0.491s | True | 4.00 | 4.00 |
| audio_safe_prefix | True | 0.259s | 0.080s | 0.178s | True | 4.00 | 4.00 |
| cv_hidden_rng_prefix | False | 0.549s | 0.227s | 0.322s | False | 4.00 | 4.00 |
| cv_external_state_prefix | False | 1.289s | 0.808s | 0.481s | False | 4.00 | 4.00 |
| cv_full_cache | False | 1.454s | 0.308s | 1.146s | False | 4.00 | 1.00 |

| Policy | TP | FP | FN | TN | Safe recall | Unsafe plan selections | Benefit-positive safe workloads | Mean oracle benefit coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fail_closed | 0 | 0 | 2 | 3 | 0.0% | 0 | 2 | 0.0% |
| registry_only | 1 | 0 | 1 | 3 | 50.0% | 0 | 2 | 50.0% |
| static_only | 2 | 0 | 0 | 3 | 100.0% | 0 | 2 | 100.0% |
| dynamic_only | 2 | 3 | 0 | 0 | 100.0% | 3 | 2 | 100.0% |
| hybrid | 2 | 0 | 0 | 3 | 100.0% | 0 | 2 | 100.0% |
| manual_hint | 2 | 0 | 0 | 3 | 100.0% | 0 | 2 | 100.0% |
| human_oracle | 2 | 0 | 0 | 3 | 100.0% | 0 | 2 | 100.0% |

## Registered checks

- two_safe_and_three_unsafe_workloads: **PASS**
- cv_and_audio_domains_present: **PASS**
- semantic_traces_match_registered_expectations: **PASS**
- safe_workloads_preserve_epoch_diversity: **PASS**
- full_cache_freezes_diversity: **PASS**
- hybrid_zero_unsafe_false_accepts: **PASS**
- hybrid_safe_recall_gate: **PASS**
- hybrid_benefit_coverage_gate: **PASS**
- hybrid_zero_unsafe_plan_selections: **PASS**
- dynamic_only_unsafe_false_accepts_exposed: **PASS**
- dynamic_only_unsafe_plan_selection_exposed: **PASS**
- semantic_reject_dominates_positive_cost: **PASS**

Overall H8C calibration gate: **PASS**.

## Claim boundary

H8C validates the benchmark harness and shows how dynamic-only can turn same-context probes into unsafe plans. It is not the final blind result because the source bodies and oracle were known and no independent annotator sealed the corpus.
