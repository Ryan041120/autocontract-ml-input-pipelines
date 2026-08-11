# AutoContract optimizer-boundary MVP

> This replays the completed H3 corpus to validate a common candidate/contract/plan interface. Unit opportunity coverage is not a throughput or latency result, and this is not a new EffectV7 blind evaluation.

Operators: 30; pipelines: 10; adjacent candidates: 37; human-oracle non-overlapping opportunities: 10.

| Policy | TP | FP | FN | TN | Safe recall | Selected safe | Selected unsafe | Plan opportunity coverage | Hints/signatures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fail_closed | 0 | 0 | 15 | 22 | 0.0% | 0 | 0 | 0.0% | 0 |
| registry_only | 6 | 0 | 9 | 22 | 40.0% | 4 | 0 | 40.0% | 6 |
| static_only | 15 | 0 | 0 | 22 | 100.0% | 10 | 0 | 100.0% | 0 |
| dynamic_only | 15 | 1 | 0 | 21 | 100.0% | 10 | 1 | 100.0% | 0 |
| hybrid | 15 | 0 | 0 | 22 | 100.0% | 10 | 0 | 100.0% | 7 |
| manual_full | 15 | 0 | 0 | 22 | 100.0% | 10 | 0 | 100.0% | 30 |
| human_oracle | 15 | 0 | 0 | 22 | 100.0% | 10 | 0 | 100.0% | candidate_oracle |

## Interface checks

- fail_closed_only_eligible_selected: **PASS**
- fail_closed_non_overlap: **PASS**
- registry_only_only_eligible_selected: **PASS**
- registry_only_non_overlap: **PASS**
- static_only_only_eligible_selected: **PASS**
- static_only_non_overlap: **PASS**
- dynamic_only_only_eligible_selected: **PASS**
- dynamic_only_non_overlap: **PASS**
- hybrid_only_eligible_selected: **PASS**
- hybrid_non_overlap: **PASS**
- manual_full_only_eligible_selected: **PASS**
- manual_full_non_overlap: **PASS**
- human_oracle_only_eligible_selected: **PASS**
- human_oracle_non_overlap: **PASS**
- fail_closed_high_score_cannot_bypass_semantics: **PASS**
- hybrid_zero_unsafe_false_accepts: **PASS**
- hybrid_safe_recall_gate: **PASS**
- dynamic_only_false_accept_preserved: **PASS**
- human_oracle_plan_has_no_unsafe_selection: **PASS**
- all_contract_digests_bound: **PASS**

Overall optimizer-boundary self-test: **PASS**.

## Interpretation

- The semantic gate is upstream of plan selection: a high score cannot revive a rejected candidate.
- Dynamic-only retains its finite-probe unsafe false accept; the experiment does not hide it with posthoc repair.
- The next adapter should convert EffectV7 AnalysisV7 plus validator_v7 reasons into ContractVerdict, without changing the optimizer interface.
- RQ3 still requires a real cache/replay profiler; unit opportunity coverage is only a structural integration metric.
