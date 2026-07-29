# AutoContract H7E audiomentations holdout

Binding integrity: 100.0%.
Decisions correct: 7/7.
Known-unsafe false accepts: 0.
Supported-safe recall: 100.0%.
Coarse-reason accuracy: 100.0%.
Classified coverage: 100.0%.
H7E blind gate: **PASS**.

| Symbol | Status | Expected | Actual | State | Reason |
|---|---|---|---|---|---|
| `audiomentations.Normalize` | resolved | admit | admit | none | none |
| `audiomentations.PolarityInversion` | resolved | admit | admit | none | none |
| `audiomentations.AddGaussianNoise` | resolved | admit | admit | none | none |
| `audiomentations.Clip` | resolved | admit | admit | none | none |
| `audiomentations.Lambda` | unknown | reject | reject | none | unresolved_user_callable |
| `audiomentations.Compose` | unknown | reject | reject | none | unresolved_child_effect |
| `audiomentations.AddBackgroundNoise` | unknown | reject | reject | none | unresolved_user_callable;execution_external_effect |

The protocol, symbol bindings, adapter, and thresholds were frozen before operator bodies were inspected by the adapter author.
