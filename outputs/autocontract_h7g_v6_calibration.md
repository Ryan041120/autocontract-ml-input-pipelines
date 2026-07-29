# AutoContract EffectV6 calibration

Decisions: 34/34; reason categories: 34/34.
Delegated-mutation units: 13; named-mode units: 19.
LinearContrast origin: `func=module_bound`; decision: admit.
Freeze ready: **YES**.

| Corpus | Unit | State | Callable | Mode | Decision | Reason |
|---|---|---|---|---|---|---|
| TorchIO | `Compose` | none | none | none | reject | unresolved_child_effect |
| TorchIO | `OneOf` | none | none | none | reject | unresolved_child_effect |
| TorchIO | `RandomFlip` | none | none | none | admit | none |
| TorchIO | `RandomNoise` | none | none | none | admit | none |
| TorchIO | `RandomAffine` | none | none | none | admit | none |
| TorchIO | `RandomBlur` | none | none | none | admit | none |
| TorchIO | `RandomGamma` | none | none | none | admit | none |
| TorchIO | `RandomMotion` | none | none | none | admit | none |
| TorchIO | `RandomSwap` | none | none | none | admit | none |
| TorchIO | `Lambda` | none | none | none | reject | unresolved_user_callable |
| TorchIO | `MonaiAdapter` | none | none | none | reject | external_framework_delegation |
| audiomentations | `audiomentations.Normalize` | subscript:self.parameters | none | audiomentations.parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.PolarityInversion` | subscript:self.parameters | none | audiomentations.parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.AddGaussianNoise` | subscript:self.parameters | none | audiomentations.parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.Clip` | subscript:self.parameters | none | audiomentations.parameters_unfrozen | admit | none |
| audiomentations | `audiomentations.Lambda` | subscript:self.parameters | none | audiomentations.parameters_unfrozen | reject | unresolved_user_callable |
| audiomentations | `audiomentations.Compose` | none | none | none | reject | unresolved_child_effect |
| audiomentations | `audiomentations.AddBackgroundNoise` | subscript:self.parameters;subscript:self.time_info_arr | none | audiomentations.parameters_unfrozen | reject | unresolved_user_callable;execution_external_effect;execution_cache_state |
| imgaug | `imgaug.augmenters.meta.Identity` | none | none | none | admit | none |
| imgaug | `imgaug.augmenters.flip.Fliplr` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.arithmetic.Add` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.blur.GaussianBlur` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.meta.Sequential` | delegated_mutation:self.random_state | none | imgaug.deterministic | reject | unresolved_child_effect |
| imgaug | `imgaug.augmenters.meta.Sometimes` | delegated_mutation:self.random_state | none | imgaug.deterministic | reject | unresolved_child_effect |
| imgaug | `imgaug.augmenters.meta.Lambda` | delegated_mutation:self.random_state | func_bounding_boxes=public_input;func_heatmaps=public_input;func_images=public_input;func_keypoints=public_input;func_line_strings=public_input;func_polygons=public_input;func_segmentation_maps=public_input | imgaug.deterministic | reject | unresolved_user_callable;unresolved_callable_origin:public_input |
| imgaug | `imgaug.augmenters.debug.SaveDebugImageEveryNBatches` | none | none | none | reject | execution_external_effect |
| imgaug | `imgaug.augmenters.arithmetic.Multiply` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.blur.AverageBlur` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.geometric.Affine` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.size.CropToFixedSize` | delegated_mutation:self.random_state | none | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.contrast.LinearContrast` | delegated_mutation:self.random_state | func=module_bound | imgaug.deterministic | admit | none |
| imgaug | `imgaug.augmenters.meta.SomeOf` | delegated_mutation:self.random_state | none | imgaug.deterministic | reject | unresolved_child_effect |
| imgaug | `imgaug.augmenters.meta.WithChannels` | none | none | none | reject | unresolved_child_effect |
| imgaug | `imgaug.augmenters.meta.AssertLambda` | delegated_mutation:self.random_state | func_bounding_boxes=public_input_derived;func_heatmaps=public_input_derived;func_images=public_input_derived;func_keypoints=public_input_derived;func_line_strings=public_input_derived;func_polygons=public_input_derived;func_segmentation_maps=public_input_derived | imgaug.deterministic | reject | unresolved_user_callable;unresolved_callable_origin:public_input_derived |
