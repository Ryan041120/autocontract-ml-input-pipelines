# AutoContract feasibility experiment

This pilot uses synthetic asymmetric tensors and real torchvision v2 operators. Dynamic validation is a counterexample search, not a proof.

## Summary

- Effect cells correct: 52/52.
- Trace-safe pairs accepted: 6/6.
- Trace-unsafe pairs incorrectly accepted: 0/10.
- Trace validator precision: 1.000; recall: 1.000.
- Operator-keyed RNG precision: 1.000; recall: 1.000.

## Trace-level pair results

| Pair | Global truth | Global validator | Keyed truth | Keyed validator | First evidence |
|---|---:|---:|---:|---:|---|
| identity <-> resize | True | True | True | True | no_counterexample_found |
| normalize <-> center_crop | True | True | True | True | no_counterexample_found |
| normalize <-> random_hflip | True | True | True | True | no_counterexample_found |
| normalize <-> random_vflip | True | True | True | True | no_counterexample_found |
| normalize <-> random_crop | True | True | True | True | no_counterexample_found |
| grayscale3 <-> random_hflip | True | True | True | True | no_counterexample_found |
| gaussian_blur <-> random_hflip | False | False | True | True | max_abs_delta=0.92500013 |
| resize <-> center_crop | False | False | False | False | shape:(3, 23, 25)!=(3, 29, 31) |
| random_crop <-> resize | False | False | False | False | shape:(3, 29, 31)!=(3, 23, 25) |
| random_crop <-> center_crop | False | False | False | False | max_abs_delta=0.22060001 |
| random_hflip <-> random_vflip | False | False | True | True | max_abs_delta=0.98000002 |
| color_jitter <-> random_hflip | False | False | True | True | max_abs_delta=0.94210953 |
| color_jitter <-> normalize | False | False | False | False | max_abs_delta=1.8 |
| random_erasing <-> normalize | False | False | False | False | max_abs_delta=1.8 |
| to_uint8 <-> normalize | False | False | False | False | exception:TypeError:Input tensor should be a float tensor. Got torch.uint8. |
| stateful_udf <-> normalize | False | False | False | False | max_abs_delta=1.76 |

## Distribution-level diagnostics

| Pair | Truth | MMD decision | p-value |
|---|---:|---:|---:|
| identity <-> resize | True | True | 1.0000 |
| normalize <-> center_crop | True | True | 1.0000 |
| normalize <-> random_hflip | True | True | 1.0000 |
| normalize <-> random_vflip | True | True | 0.5900 |
| normalize <-> random_crop | True | True | 0.3700 |
| grayscale3 <-> random_hflip | True | True | 1.0000 |
| gaussian_blur <-> random_hflip | True | True | 1.0000 |
| resize <-> center_crop | False | False | 0.0050 |
| random_crop <-> resize | False | False | 0.0050 |
| random_crop <-> center_crop | False | False | 0.0050 |
| random_hflip <-> random_vflip | True | True | 1.0000 |
| color_jitter <-> random_hflip | True | True | 0.1400 |
| color_jitter <-> normalize | False | False | 0.0050 |
| random_erasing <-> normalize | False | False | 0.0050 |
| to_uint8 <-> normalize | False | False | 0.0000 |

## Interpretation

A zero false-accept count in this curated set is only the entry criterion. The next study must expand the adversarial operator set, separate operator-keyed from global RNG semantics, and compare against manual cedar/Pecan annotations.
