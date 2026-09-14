# AutoContract R3-P3d ReplayCapabilityV1

Preregistered status: **pass** (7/7 gates).

- Semantic: Admit=11/11 (unchanged EffectV7).
- Capability: Supported=10, Unsupported=1, Unknown=0.
- Final: Admit=10, Unsupported=1, Unknown=0, Reject=0.
- Capability probe median=4.793 ms; receipt median=826 bytes.

## Layered result

| Unit | Semantic | Capability | Source | Final |
|---|---|---|---|---|
| `imgaug.augmenters.arithmetic.Multiply` | admit | supported | supported | admit |
| `imgaug.augmenters.blur.AverageBlur` | admit | supported | supported | admit |
| `imgaug.augmenters.geometric.Affine` | admit | supported | supported | admit |
| `imgaug.augmenters.size.CropToFixedSize` | admit | supported | supported | admit |
| `imgaug.augmenters.contrast.LinearContrast` | admit | supported | supported | admit |
| `albumentations.augmentations.geometric.flip.VerticalFlip` | admit | supported | supported | admit |
| `albumentations.augmentations.pixel.transforms.RandomGamma` | admit | supported | supported | admit |
| `albumentations.augmentations.blur.transforms.GaussianBlur` | admit | supported | supported | admit |
| `albumentations.augmentations.geometric.transforms.Affine` | admit | supported | supported | admit |
| `albumentations.augmentations.crops.transforms.CenterCrop` | admit | supported | supported | admit |
| `albumentations.augmentations.mixing.domain_adaptation.HistogramMatching` | admit | unsupported | supported | unsupported |

## Gates

- PASS `all_11_semantic_admit_unchanged`
- PASS `all_11_source_supported_and_stable`
- PASS `capability_exactly_10_supported_1_histogram_unsupported`
- PASS `final_exactly_10_admit_1_unsupported`
- PASS `all_10_admits_exact_rng_and_lineage`
- PASS `composition_truth_table_8_of_8`
- PASS `frozen_inputs_unchanged`

## Interpretation

HistogramMatching remains conditionally semantic-Admit under EffectV7, but the public framework operation is Unsupported because replay record serialization is explicitly prohibited. This separation prevents a feasibility failure from being mislabeled as a semantic effect and prevents semantic Admit from becoming deployment Admit by itself.
