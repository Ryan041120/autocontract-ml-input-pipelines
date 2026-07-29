# AutoContract cache-placement benchmark

Synthetic images: 24; epochs: 5; repeats: 3.
Timings include first-epoch cache construction and output hashing.

| Policy | Runtime (s) | Same-RNG speedup | Vs global baseline | Trace match after epoch 0 | Mean unique outputs |
|---|---:|---:|---:|---:|---:|
| global:none | 0.4030 | 1.00x | 1.00x | 1.000 | 5.00 |
| global:prefix | 0.2373 | 1.70x | 0.59x | 0.000 | 5.00 |
| global:full | 0.0984 | 4.09x | 0.24x | 0.000 | 1.00 |
| operator_keyed:none | 1.3471 | 1.00x | 3.34x | 1.000 | 5.00 |
| operator_keyed:prefix | 0.7612 | 1.77x | 1.89x | 1.000 | 5.00 |
| operator_keyed:full | 0.2629 | 5.12x | 0.65x | 0.000 | 1.00 |
| torch_keyed:none | 1.1156 | 1.00x | 2.77x | 1.000 | 5.00 |
| torch_keyed:prefix | 0.8269 | 1.35x | 2.05x | 1.000 | 5.00 |
| torch_keyed:full | 0.2429 | 4.59x | 0.60x | 0.000 | 1.00 |

## Interpretation

- Global-RNG prefix caching trace match after epoch 0: 0.000.
- Operator-keyed prefix caching trace match after epoch 0: 1.000.
- Torch-source-keyed prefix caching trace match after epoch 0: 1.000.
- Operator-keyed full caching leaves only 1.00 unique outputs per sample across 5 epochs.

Prefix caching is therefore trace-preserving only under an RNG contract that decouples stochastic operators from skipped deterministic RNG consumers. Full caching remains semantically unsafe for augmentation diversity.
