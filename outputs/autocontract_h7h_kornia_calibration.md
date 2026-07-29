# H7H Kornia adapter calibration

Decisions: 9/9; reasons: 9/9; phase contrast: 100.0%.
Freeze ready: **YES**.

| Symbol | Configuration | Expected | Actual | Sampling | Delegation | Reason |
|---|---|---|---|---|---|---|
| `kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.geometric.horizontal_flip.RandomHorizontalFlip` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.intensity.gaussian_blur.RandomGaussianBlur` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.intensity.gaussian_blur.RandomGaussianBlur` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.intensity.color_jiggle.ColorJiggle` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation._2d.geometric.affine.RandomAffine` | kornia.params_provided | admit | admit | False | none | none |
| `kornia.augmentation._2d.geometric.affine.RandomAffine` | kornia.params_absent | reject | reject | True | none | reachable_sampling_rng |
| `kornia.augmentation.container.image.ImageSequential` | kornia.params_provided | reject | reject | False | child_operator | unresolved_child_effect |
