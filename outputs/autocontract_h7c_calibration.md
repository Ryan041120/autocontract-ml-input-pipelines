# AutoContract H7C TorchIO adapter calibration

Generic unknown-reject safe recall: 0.0%.
Adapter calibration decisions: 4/4 correct.

| Unit | Generic | Adapter | Adapter reason |
|---|---|---|---|
| `Compose` | reject | reject | analysis_unknown;unresolved_child_effect |
| `OneOf` | reject | reject | analysis_unknown;unresolved_child_effect |
| `RandomFlip` | reject | admit | none |
| `RandomNoise` | reject | admit | none |

Framework rules are structural and are listed in the frozen adapter manifest.
