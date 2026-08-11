# AutoContract H8C-R1 stateful dynamic calibration

Status: **pass** (10/10)

> Review-driven internal calibration over known H8C source/oracle; not blind benchmark evidence.

## Policy comparison

| Policy | TP | FP | FN | TN | Safe recall | Unsafe selections |
|---|---:|---:|---:|---:|---:|---:|
| dynamic_output_only | 2 | 3 | 0 | 0 | 100.0% | 3 |
| dynamic_stateful | 2 | 0 | 0 | 3 | 100.0% | 0 |
| hybrid | 2 | 0 | 0 | 3 | 100.0% | 0 |

## Probe observations

| Workload | Output-only conflict | Stateful conflict | Observed effects |
|---|---:|---:|---|
| cv_safe_prefix | False | False | none |
| audio_safe_prefix | False | False | none |
| cv_hidden_rng_prefix | False | True | rng_state_changed |
| cv_external_state_prefix | False | True | environment_output_changed |
| cv_full_cache | False | True | cross_context_output_changed |

## Interpretation

On the five known H8C boundaries, the fairer stateful dynamic baseline closes all three false accepts and matches hybrid classification. This weakens any novelty argument based only on the historical output-only baseline. The next discriminating experiment must use unseen contexts or effects that a fixed finite probe budget cannot anticipate, while measuring Unknown/timeout cost fairly.
