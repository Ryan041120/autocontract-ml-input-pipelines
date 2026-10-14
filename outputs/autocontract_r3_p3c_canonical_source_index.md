# AutoContract R3-P3c canonical SourceIndexV1

Preregistered status: **pass** (7/7 gates).

- Three-process stable: 11/11 (V0 was 3/11).
- Supported/no entry drop: 11/11.
- Portable mutation decisions: Reject=22, Unknown=11, Admit=0.
- Synthetic fixtures: 9/9; cross-process constant fixtures=True.
- Aggregate serialized bytes: V0=474,337, V1=504,588 (1.064x).
- Per-unit cold-index median of medians: V0=125.297 ms, V1=130.512 ms.

## Gates

- PASS `all_11_complete_component_coverage`
- PASS `all_11_supported_and_no_v0_entry_drop`
- PASS `all_11_same_and_three_process_stable`
- PASS `portable_mutations_22_reject_11_unknown_0_admit`
- PASS `all_33_restore_baseline`
- PASS `all_source_and_constant_fixtures`
- PASS `frozen_inputs_unchanged`

## Boundary

P3c repairs deployment-artifact determinism only. It does not change the P3b HistogramMatching replay failure, the frozen EffectV7 decision, native Unknown handling, or concurrent TOCTOU scope.
