# AutoContract EffectV7 calibration

Decisions: 36/36; reason categories: 36/36.
H7G phase contrast: replay=admit, record=reject.
Freeze ready: **YES**.

| Corpus | Unit | Configuration | Phase | Expected | Actual |
|---|---|---|---|---|---|
| TorchIO | `Compose` | legacy | sample_apply | reject | reject |
| TorchIO | `OneOf` | legacy | sample_apply | reject | reject |
| TorchIO | `RandomFlip` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomNoise` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomAffine` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomBlur` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomGamma` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomMotion` | legacy | sample_apply | admit | admit |
| TorchIO | `RandomSwap` | legacy | sample_apply | admit | admit |
| TorchIO | `Lambda` | legacy | sample_apply | reject | reject |
| TorchIO | `MonaiAdapter` | legacy | sample_apply | reject | reject |
| audiomentations | `audiomentations.Normalize` | legacy | sample_apply | admit | admit |
| audiomentations | `audiomentations.PolarityInversion` | legacy | sample_apply | admit | admit |
| audiomentations | `audiomentations.AddGaussianNoise` | legacy | sample_apply | admit | admit |
| audiomentations | `audiomentations.Clip` | legacy | sample_apply | admit | admit |
| audiomentations | `audiomentations.Lambda` | legacy | sample_apply | reject | reject |
| audiomentations | `audiomentations.Compose` | legacy | sample_apply | reject | reject |
| audiomentations | `audiomentations.AddBackgroundNoise` | legacy | sample_apply | reject | reject |
| imgaug | `imgaug.augmenters.meta.Identity` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.flip.Fliplr` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.arithmetic.Add` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.blur.GaussianBlur` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.meta.Sequential` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.meta.Sometimes` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.meta.Lambda` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.debug.SaveDebugImageEveryNBatches` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.arithmetic.Multiply` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.blur.AverageBlur` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.geometric.Affine` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.size.CropToFixedSize` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.contrast.LinearContrast` | legacy | replay_apply | admit | admit |
| imgaug | `imgaug.augmenters.meta.SomeOf` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.meta.WithChannels` | legacy | replay_apply | reject | reject |
| imgaug | `imgaug.augmenters.meta.AssertLambda` | legacy | replay_apply | reject | reject |
| Albumentations-H7G-posthoc | `albumentations.augmentations.mixing.domain_adaptation.HistogramMatching` | albumentations.replay | replay_apply | admit | admit |
| Albumentations-H7G-posthoc | `albumentations.augmentations.mixing.domain_adaptation.HistogramMatching` | albumentations.record | sample_apply | reject | reject |
