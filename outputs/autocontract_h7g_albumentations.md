# AutoContract H7G Albumentations holdout

Binding integrity: 100.0%.
Decisions correct: 7/8.
Known-unsafe false accepts: 1.
Supported-safe recall: 100.0%.
Coarse-reason accuracy: 87.5%.
Classified coverage: 100.0%.
H7G blind gate: **FAIL**.

| Symbol | Expected | Actual | State | Callable | Mode | Reason |
|---|---|---|---|---|---|---|
| `albumentations.augmentations.geometric.flip.VerticalFlip` | admit | admit | attribute:self.params;delegated_mutation:self.py_random | ensure_contiguous_output=module_bound | albumentations.replay | none |
| `albumentations.augmentations.pixel.transforms.RandomGamma` | admit | admit | attribute:self.params;delegated_mutation:self.py_random | ensure_contiguous_output=module_bound | albumentations.replay | none |
| `albumentations.augmentations.blur.transforms.GaussianBlur` | admit | admit | attribute:self.params;delegated_mutation:self.py_random | ensure_contiguous_output=module_bound | albumentations.replay | none |
| `albumentations.augmentations.geometric.transforms.Affine` | admit | admit | attribute:self.params;delegated_mutation:self.py_random | ensure_contiguous_output=module_bound | albumentations.replay | none |
| `albumentations.augmentations.crops.transforms.CenterCrop` | admit | admit | attribute:self.params;delegated_mutation:self.py_random | denormalize_bboxes=module_bound;ensure_contiguous_output=module_bound;normalize_bboxes=module_bound | albumentations.replay | none |
| `albumentations.core.composition.OneOf` | reject | reject | delegated_mutation:self.py_random;delegated_mutation:self.random_generator | none | albumentations.replay | unresolved_child_effect |
| `albumentations.core.composition.Sequential` | reject | reject | delegated_mutation:self.py_random | none | albumentations.replay | unresolved_child_effect |
| `albumentations.augmentations.mixing.domain_adaptation.HistogramMatching` | reject | admit | attribute:self.params;delegated_mutation:self.py_random | apply_histogram=module_bound;ensure_contiguous_output=module_bound | albumentations.replay | none |

The replay context is a per-sample stored-parameter context, not merely Compose(seed).
Formal symbols are disjoint from calibration and were effect-analyzed only after freeze.
