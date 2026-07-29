# AutoContract H6A pinned GitHub effect-schema pilot

Pinned sources: 6; evaluated units: 20; runtime: 0.67s.

| Split | Units | Effect-cell accuracy | Coupling FN | Many-to-one FN |
|---|---:|---:|---:|---:|
| debug | 3 | 100.0% | 0 | 0 |
| holdout | 17 | 71.6% | 0 | 0 |

## H6A schema gate

- Holdout effect-cell accuracy >=80%: **FAIL**.
- Multi-target coupling false negatives = 0: **PASS**.
- Many-to-one cardinality false negatives = 0: **PASS**.
- Overall H6A schema pilot: **FAIL**.

This gate only decides whether the expanded schema is worth implementing in the rewrite validator. It is not the full H6 external-validity result.

## Holdout mismatches

- `timm_factory::transforms_imagenet_train`: targets, target_coupled
- `timm_factory::transforms_imagenet_eval`: targets, target_coupled
- `ultralytics_augment::Mosaic`: targets
- `ultralytics_augment::MixUp`: targets
- `ultralytics_augment::CutMix`: targets
- `ultralytics_augment::CopyPaste`: targets
- `ultralytics_augment::RandomHSV`: targets, target_coupled
- `ultralytics_augment::RandomFlip`: rng_sources
- `ultralytics_augment::Albumentations`: rng_sources, targets, external_dependencies
- `ultralytics_augment::v8_transforms`: rng_sources, targets, external_dependencies
- `detectron2_mapper::DatasetMapper`: targets
- `albumentations_compose::Compose`: rng_sources, targets
- `albumentations_compose::OneOf`: rng_sources, targets, target_coupled
- `albumentations_compose::SomeOf`: rng_sources, targets, target_coupled
- `albumentations_compose::ReplayCompose`: rng_sources, targets
- `kornia_augment::AugmentationSequential`: rng_sources
