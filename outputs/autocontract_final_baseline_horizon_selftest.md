# Final-v1 baseline/horizon internal self-test

Status: **pass** (12/12)

> Synthetic internal calibration only; this is not final benchmark evidence.

## Checks

| Check | Result |
|---|---|
| `pure_has_no_stateful_conflict` | PASS |
| `hidden_rng_missed_by_output_only` | PASS |
| `hidden_rng_found_by_stateful` | PASS |
| `hidden_state_missed_by_output_only` | PASS |
| `hidden_state_found_by_stateful` | PASS |
| `environment_drift_found` | PASS |
| `epoch_drift_found` | PASS |
| `fixed_probe_budget_respected` | PASS |
| `manifest_horizon_stable_select` | PASS |
| `manifest_horizon_uncertainty_exposed` | PASS |
| `workers_do_not_multiply_logical_horizon` | PASS |
| `invalid_horizon_manifest_rejected` | PASS |

## Dynamic probes

| Unit | Output-only conflict | Stateful conflict | Observed effects |
|---|---:|---:|---|
| pure | False | False | none |
| hidden_rng | False | True | rng_state_changed |
| hidden_state | False | True | object_state_changed |
| environment | False | True | environment_output_changed |
| epoch_sensitive | False | True | cross_context_output_changed |

## Horizon decisions

| Scenario | Low / planned / high | Stability |
|---|---|---|
| stable_select | 2 / 4 / 6 | stable_select |
| horizon_unstable | 1 / 4 / 10 | horizon_unstable |
| worker_variant | 2 / 4 / 6 | stable_select |
