# AutoContract R3-P3b cross-framework runtime

Overall preregistered gate status: **fail** (6/8).

## Headline

- Constructed: 11/11; replay exact: 10/11.
- Portable full Supported: 11/11; Unknown: 0/11.
- Hot sentinel Supported: 11/11; Unknown: 0/11.
- Mutation decisions: reject=22, unknown=11, admit=0.

## Framework summary

| Framework | Units | Constructed | Replay pass | Portable Supported | Hot Supported |
|---|---:|---:|---:|---:|---:|
| imgaug | 5 | 5 | 5 | 5 | 5 |
| Albumentations | 6 | 6 | 5 | 6 | 6 |

## Failed replay units

- `albumentations.augmentations.mixing.domain_adaptation.HistogramMatching`: NotImplementedError — HistogramMatching cannot be reliably serialized due to its dependency on external data via metadata.

## Gates

- PASS `all_11_constructed`
- FAIL `all_constructed_replay_equivalent`
- PASS `caller_rng_measured_and_no_drift_silently_ignored`
- PASS `all_registered_components_nonempty`
- FAIL `portable_same_and_cross_process_stable`
- PASS `no_mutation_admit`
- PASS `all_wrapper_attacks_raw_drift`
- PASS `all_mutations_restore_baseline`

## Interpretation boundary

This is a runtime feasibility and falsification run on known admits. Exact replay is scoped to the registered operation and fixture. Unknown executable binding remains Unknown even when diagnostic digests drift.
