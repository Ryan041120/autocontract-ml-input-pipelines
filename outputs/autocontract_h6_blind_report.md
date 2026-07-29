# AutoContract EffectV2 one-shot blind evaluation

Repositories: 3; units: 12; effect cells: 180.
Effect-cell accuracy: 76.1%.
Critical false negatives: 9.
Known-unsafe false accepts: 2.
Blind H6 effect gate: **FAIL**.

## Mismatches

- `monai_compose::Compose`: rng_direct_sources
- `monai_compose::OneOf`: rng_direct_sources
- `monai_compose::RandomOrder`: rng_direct_sources
- `monai_compose::SomeOf`: rng_direct_sources
- `mmdet_transforms::RandomFlip`: construction_state_writes, execution_reads, execution_writes, rng_delegated, target_coupled
- `mmdet_transforms::RandomCrop`: execution_reads, execution_writes, rng_direct_sources, target_coupled
- `mmdet_transforms::Mosaic`: execution_reads, execution_writes, rng_direct_sources
- `mmdet_transforms::MixUp`: execution_reads, execution_writes, rng_direct_sources
- `mmdet_transforms::CopyPaste`: execution_reads, execution_writes, rng_direct_sources
- `mmdet_transforms::CachedMosaic`: execution_reads, execution_writes, rng_direct_sources, target_coupled, input_cardinality, sample_identity
- `dali_pipeline::Pipeline`: execution_reads, execution_writes, execution_external_reads, execution_external_writes, rng_delegated, target_signature, input_cardinality, output_cardinality
- `dali_pipeline::pipeline_def`: execution_reads, execution_writes, execution_external_reads, execution_external_writes, target_signature, input_cardinality, output_cardinality

## False accepts

- `mmdet_transforms::CachedMosaic`
- `dali_pipeline::Pipeline`

The frozen analyzer and pre-run oracle hashes were verified before evaluation.
