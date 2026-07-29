# H7F posthoc callable-origin audit (non-gating)

This audit was designed after the frozen one-shot H7F run and does not alter H7F=PASS.

| Symbol | Invoked callable | Origin | User callable? | Counterfactual |
|---|---|---|---|---|
| `imgaug.augmenters.contrast.LinearContrast` | func | module_symbol | False | admit |
| `imgaug.augmenters.meta.Lambda` | func_bounding_boxes;func_heatmaps;func_images;func_keypoints;func_line_strings;func_polygons;func_segmentation_maps | user_input | True | reject |
| `imgaug.augmenters.meta.AssertLambda` | func_bounding_boxes;func_heatmaps;func_images;func_keypoints;func_line_strings;func_polygons;func_segmentation_maps | user_derived | True | reject |

`LinearContrast.func` is a module-owned function forwarded through `super().__init__`; the Lambda-family callbacks derive from public constructor inputs.
