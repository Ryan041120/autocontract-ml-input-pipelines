# AutoContract R3-P2b cached measured-source index

Status: **pass** (11/11 harness checks).

> Posthoc mechanism calibration on known Kornia plus synthetic source fixtures; not blind evidence.

## Real Kornia policy comparison

| Policy | Benign preservation | Required rejection recall | Unknown accuracy | False accepts | Median ms/case |
|---|---:|---:|---:|---:|---:|
| cached_digest_only | 100.0% | 0.0% | 0.0% | 4 | 2.049 |
| hot_callable_sentinel | 100.0% | 100.0% | 100.0% | 0 | 2.591 |
| cold_reindex | 100.0% | 100.0% | 100.0% | 0 | 401.077 |

## Cost boundaries

- Registration index: 363.062 ms.
- Deployment revalidation: 481.822 ms.
- Process-local sentinel creation: 0.938 ms (27 entries).
- Sentinel-only hot check: 0.6690 ms median over 200 repetitions.
- Existing lineage-v1 hot validation: 1.4392 ms median over 100 repetitions.
- Cold reindex reference: 407.357 ms median over 5 repetitions.
- Serialized portable index: 130493 bytes.

## Interpretation

A cached portable digest alone is not a runtime source binding: it admits post-deployment class, code-object, and instance mutations. The process-local sentinel closes those pre-check mutations on this supported replay slice and returns Unknown for a native override, while keeping Git/source/AST work outside the hot path. It still does not solve mutation concurrent with execution or native internals.
