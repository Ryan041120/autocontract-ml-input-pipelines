# AutoContract EffectV5 calibration

Decisions: 18/18; reason categories: 18/18.
audiomentations state roles: 7/7.
Complete super resolution: 18/18.
Freeze ready: **YES**.

| Corpus | Unit | State roles | Required modes | Decision | Reason |
|---|---|---|---|---|---|
| TorchIO | `Compose` | none | none | reject | unresolved_child_effect |
| TorchIO | `OneOf` | none | none | reject | unresolved_child_effect |
| TorchIO | `RandomFlip` | none | none | admit | none |
| TorchIO | `RandomNoise` | none | none | admit | none |
| TorchIO | `RandomAffine` | none | none | admit | none |
| TorchIO | `RandomBlur` | none | none | admit | none |
| TorchIO | `RandomGamma` | none | none | admit | none |
| TorchIO | `RandomMotion` | none | none | admit | none |
| TorchIO | `RandomSwap` | none | none | admit | none |
| TorchIO | `Lambda` | none | none | reject | unresolved_user_callable |
| TorchIO | `MonaiAdapter` | none | none | reject | external_framework_delegation |
| audiomentations | `audiomentations.Normalize` | replayable | parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.PolarityInversion` | replayable | parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.AddGaussianNoise` | replayable | parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.Clip` | replayable | parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.Lambda` | replayable | parameters_unfrozen | reject | unresolved_user_callable |
| audiomentations | `audiomentations.Compose` | none | none | reject | unresolved_child_effect |
| audiomentations | `audiomentations.AddBackgroundNoise` | cache;replayable | parameters_unfrozen | reject | unresolved_user_callable;execution_external_effect;execution_cache_state |
