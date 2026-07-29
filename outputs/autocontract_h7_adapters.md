# AutoContract H7A adapter mechanism calibration

> This reuses the opened H6 blind set for postmortem calibration; it is not a new blind result.

Decisions correct: 12/12 (100.0%).
Known-unsafe false accepts: 0.
Supported safe recall: 2/2 (100.0%).
Generic unknown-reject safe recall counterfactual: 0/2 (0.0%).
Unsupported reason coverage: 2/2 (100.0%).
H7A safety/recall mechanism gate: **PASS**.
H7 overall gate: **INCOMPLETE** (adapters are not frozen and no unseen-project holdout has run).

## Decisions

| Unit | Adapter | Status | Decision | Correct | Reason |
|---|---|---|---|---:|---|
| `monai_compose::Compose` | monai | resolved | reject | yes | parametric_target_signature |
| `monai_compose::OneOf` | monai | resolved | reject | yes | parametric_target_signature |
| `monai_compose::RandomOrder` | monai | resolved | reject | yes | parametric_target_signature |
| `monai_compose::SomeOf` | monai | resolved | reject | yes | parametric_target_signature |
| `mmdet_transforms::RandomFlip` | mmdetection | resolved | admit | yes | none |
| `mmdet_transforms::RandomCrop` | mmdetection | resolved | admit | yes | none |
| `mmdet_transforms::Mosaic` | mmdetection | resolved | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms::MixUp` | mmdetection | resolved | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms::CopyPaste` | mmdetection | resolved | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms::CachedMosaic` | mmdetection | resolved | reject | yes | unsupported_cardinality:many->one;combined_sample_identity;execution_state_write |
| `dali_pipeline::Pipeline` | generic | unknown | reject | yes | analysis_unknown;missing_execution_entrypoint;unsupported_backend_graph:dali |
| `dali_pipeline::pipeline_def` | generic | unknown | reject | yes | analysis_unknown;unresolved_factory_execution_semantics;unsupported_backend_graph:dali |

## Adapter cost (not yet a passed gate)

Two adapters contain 10 structural rules for 10 evaluated units (1.00 rules/unit). Against 16 per-unit EffectV3 fields, the descriptive cell-equivalent reduction is 93.8%.
This is not yet an annotation-time measurement and cannot establish the >=70% amortization claim.

## Interpretation

The assumption reversal worked on the calibration set: unsupported semantics became explicit Unknown outputs, while framework facts recovered the two safe MMDetection opportunities. The next valid test is to freeze these rules and evaluate unseen MONAI/MMDetection projects or versions without editing the adapters.
