# H7G posthoc mode-conditioned reachability (non-gating)

This audit was designed after the frozen H7G run and does not change H7G=FAIL.

| Mode | read_fn origin | Reachable? | Counterfactual | Reachable methods |
|---|---|---|---|---|
| replay | user_input | False | admit | __call__;apply;apply_with_params |
| record | user_input | True | reject | __call__;_get_reference_image;apply;apply_with_params;get_params;get_params_dependent_on_data;should_apply;update_transform_params |

In replay mode, BasicTransform.__call__ returns through stored params before sampling helpers. In record mode, get_params_dependent_on_data reaches _get_reference_image and the public-input read_fn.
