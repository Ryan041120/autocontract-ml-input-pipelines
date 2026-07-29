# AutoContract H7F imgaug holdout

Binding integrity: 100.0%.
Decisions correct: 7/8.
Known-unsafe false accepts: 0.
Supported-safe recall: 80.0%.
Coarse-reason accuracy: 87.5%.
Classified coverage: 100.0%.
H7F blind gate: **PASS**.

| Symbol | Expected | Actual | State roles | Mode | Reason |
|---|---|---|---|---|---|
| `imgaug.augmenters.arithmetic.Multiply` | admit | admit | replayable | framework_specific | none |
| `imgaug.augmenters.blur.AverageBlur` | admit | admit | replayable | framework_specific | none |
| `imgaug.augmenters.geometric.Affine` | admit | admit | replayable | framework_specific | none |
| `imgaug.augmenters.size.CropToFixedSize` | admit | admit | replayable | framework_specific | none |
| `imgaug.augmenters.contrast.LinearContrast` | admit | reject | replayable | framework_specific | unresolved_user_callable |
| `imgaug.augmenters.meta.SomeOf` | reject | reject | replayable | framework_specific | unresolved_child_effect |
| `imgaug.augmenters.meta.WithChannels` | reject | reject | none | none | unresolved_child_effect |
| `imgaug.augmenters.meta.AssertLambda` | reject | reject | replayable | framework_specific | unresolved_user_callable |

The formal symbols are disjoint from adapter calibration symbols; protocol, thresholds, adapter, symbol origins, and sources were frozen before formal effect analysis.
