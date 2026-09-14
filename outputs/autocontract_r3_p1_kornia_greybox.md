# AutoContract R3-P1 Kornia real-source greybox calibration

Status: **pass** (8/8)

> Posthoc method calibration on the already-known H7H source/oracle; not a new blind result.

## Policy comparison

| Policy | Budget | TP | FP | FN | TN | Safe recall | Reason accuracy | Classified/Crash | Median prep | Median policy | Calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| effect_v7_frozen | 0 ms | 4 | 0 | 0 | 5 | 100.0% | 100.0% | 9/0 | 0.000 ms | 11.916 ms | 0 |
| dynamic_blackbox | 25 ms | 4 | 1 | 0 | 4 | 100.0% | 88.9% | 9/0 | 3.198 ms | 45.500 ms | 10 |
| dynamic_blackbox | 100 ms | 4 | 1 | 0 | 4 | 100.0% | 88.9% | 9/0 | 3.637 ms | 87.145 ms | 45 |
| dynamic_blackbox | 500 ms | 4 | 1 | 0 | 4 | 100.0% | 88.9% | 9/0 | 2.979 ms | 118.089 ms | 84 |
| dynamic_source_guided | 25 ms | 4 | 0 | 0 | 5 | 100.0% | 100.0% | 9/0 | 2.813 ms | 6.760 ms | 25 |
| dynamic_source_guided | 100 ms | 4 | 0 | 0 | 5 | 100.0% | 100.0% | 9/0 | 3.367 ms | 35.936 ms | 52 |
| dynamic_source_guided | 500 ms | 4 | 0 | 0 | 5 | 100.0% | 100.0% | 9/0 | 3.188 ms | 81.462 ms | 65 |
| manual_full | 0 ms | 4 | 0 | 0 | 5 | 100.0% | 100.0% | 9/0 | 0.000 ms | 0.000 ms | 0 |

## Burden accounting

- EffectV7 Kornia adapter: 8 rules, 40 LOC proxy.
- Greybox semantic guidance: 1 rule, 3 LOC.
- Shared runtime factories: 5 entries, 17 LOC.
- Manual upper bound: 9 unit hints / 18 decision+reason fields.

## Interpretation

The decisive question is whether one public MRO/container heuristic lets source-guided dynamic close the black-box child-delegation false accept while preserving replay cases. If so, this nine-unit scope does not establish a detection-accuracy advantage for the full EffectV7 adapter; any retained contribution must come from broader effect coverage, stable contract reasons, and invalidation/audit artifacts.
