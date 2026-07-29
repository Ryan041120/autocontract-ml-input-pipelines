# AutoContract H7B sealed release-version holdout

Analyzer, adapter manifest, oracle, releases, units, and thresholds were hashed before source fetch.

Decision accuracy: 14/14 (100.0%).
Known-unsafe false accepts: 0.
Supported safe recall: 3/3 (100.0%).
Unsupported reason coverage: 2/2 (100.0%).
Reason-category accuracy: 14/14 (100.0%).
H7B blind gate: **PASS**.
H7 overall gate: **INCOMPLETE** until adapter annotation-time amortization is measured.

## Decisions

| Unit | Status | Adapter | Expected | Actual | Reason match | Validator reason |
|---|---|---|---|---|---:|---|
| `monai_compose_h7b::Compose` | resolved | monai | reject | reject | yes | parametric_target_signature |
| `monai_compose_h7b::OneOf` | resolved | monai | reject | reject | yes | parametric_target_signature |
| `monai_compose_h7b::RandomOrder` | resolved | monai | reject | reject | yes | parametric_target_signature |
| `monai_compose_h7b::SomeOf` | resolved | monai | reject | reject | yes | parametric_target_signature |
| `mmdet_transforms_h7b::RandomFlip` | resolved | mmdetection | admit | admit | yes | none |
| `mmdet_transforms_h7b::RandomCrop` | resolved | mmdetection | admit | admit | yes | none |
| `mmdet_transforms_h7b::RandomShift` | resolved | mmdetection | admit | admit | yes | none |
| `mmdet_transforms_h7b::Mosaic` | resolved | mmdetection | reject | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms_h7b::MixUp` | resolved | mmdetection | reject | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms_h7b::CopyPaste` | resolved | mmdetection | reject | reject | yes | unsupported_cardinality:many->one;combined_sample_identity |
| `mmdet_transforms_h7b::CachedMosaic` | resolved | mmdetection | reject | reject | yes | unsupported_cardinality:many->one;combined_sample_identity;execution_state_write |
| `mmdet_transforms_h7b::CachedMixUp` | resolved | mmdetection | reject | reject | yes | unsupported_cardinality:many->one;combined_sample_identity;execution_state_write |
| `dali_pipeline_h7b::Pipeline` | unknown | generic | reject | reject | yes | analysis_unknown;missing_execution_entrypoint;unsupported_backend_graph:dali |
| `dali_pipeline_h7b::pipeline_def` | unknown | generic | reject | reject | yes | analysis_unknown;unresolved_factory_execution_semantics;unsupported_backend_graph:dali |

## Protocol boundary

This is a release-version holdout, not a new-framework holdout. Two operators (RandomShift and CachedMixUp) were absent from H7A's evaluated units, but their older source file had already been opened during the H6 postmortem. The result therefore tests frozen-rule version/operator transfer, not fully independent project transfer.
