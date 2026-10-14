# AutoContract P4A adapter burden accounting

Preregistered status: **fail** (5/6 gates).

- Accounted contaminated frameworks: 10; adapters: 8; unsupported/example-only: 2.
- Framework-specific semantic adapter SLOC: 1286; binding glue SLOC: 87; shared infrastructure SLOC: 79.
- Declared rules: 53 over 50 formal symbols.
- Lightweight diagnostic: 4/8 frameworks.
- Prospective onboarding time: 0/8; human-time displacement claim: **unsupported**.

| Framework | Status | Formal | Rules | Semantic SLOC | Binding SLOC | Runtime slots | Lightweight |
|---|---|---:|---:|---:|---:|---:|---|
| MONAI | adapter | 4 | 4 | 31 | 0 | 0 | True |
| MMDetection | adapter | 6 | 6 | 72 | 0 | 0 | True |
| TorchIO | adapter | 7 | 6 | 115 | 0 | 0 | True |
| TorchGeo | adapter | 5 | 5 | 91 | 0 | 0 | True |
| audiomentations | adapter | 7 | 7 | 197 | 26 | 0 | False |
| imgaug | adapter_plus_runtime_policy | 8 | 8 | 315 | 23 | 3 | False |
| Albumentations | adapter_plus_runtime_policy | 8 | 9 | 415 | 22 | 11 | False |
| Kornia | adapter_plus_shared_runtime_policy | 5 | 8 | 50 | 16 | 7 | False |
| NVIDIA DALI | unsupported_no_adapter | 2 | 0 | 0 | 0 | 0 | None |
| torchvision | development_example_no_frozen_adapter | 0 | 0 | 0 | 0 | 0 | None |

## Gates

- PASS `all_10_contaminated_frameworks_accounted`
- PASS `all_registered_items_exist_without_category_overlap`
- PASS `all_8_adapters_have_rules_and_denominator`
- FAIL `at_least_75_percent_meet_lightweight_diagnostic`
- PASS `human_time_claim_correctly_unsupported`
- PASS `frozen_inputs_unchanged`

## Interpretation

This audit quantifies retained code and declarations, not the effort required to discover them. Retrospective SLOC/rule ratios cannot support a claim that AutoContract reduces human annotation time. A prospective unseen-framework onboarding log remains required.
