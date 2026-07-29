# AutoContract H7H Kornia holdout

Binding integrity: 100.0%.
Decisions correct: 9/9.
Known-unsafe false accepts: 0.
Supported-safe recall: 100.0%.
Coarse-reason accuracy: 100.0%.
Classified coverage: 100.0%.
Phase-contrast accuracy: 100.0%.
H7H blind gate: **PASS**.

| Symbol | Configuration | Expected | Actual | Sampling | Delegation | Reason |
|---|---|---|---|---|---|---|
| `kornia.augmentation._2d.geometric.vertical_flip.RandomVerticalFlip` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.geometric.vertical_flip.RandomVerticalFlip` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.intensity.posterize.RandomPosterize` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.intensity.posterize.RandomPosterize` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.intensity.solarize.RandomSolarize` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.intensity.solarize.RandomSolarize` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.intensity.motion_blur.RandomMotionBlur` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.intensity.motion_blur.RandomMotionBlur` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation.container.augment.AugmentationSequential` | kornia.params_provided | reject | reject | False | child_operator | unresolved_child_effect |

Formal symbols are disjoint from calibration. Their method-body effect analysis ran once after the adapter, protocol, symbol bindings, source hashes, and thresholds were frozen.
