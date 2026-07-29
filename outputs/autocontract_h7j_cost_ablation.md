# H7J sealed atomic replay cost ablation

Iterations per median: 50; direct replay baseline: 18.990 ms; sealed atomic: 16.911 ms (0.891x).

| Operation | Median ms | Relative to direct replay |
|---|---:|---:|
| deepcopy_params | 1.893 | 0.100x |
| full_certificate_validate | 1.152 | 0.061x |
| child_contract_compose | 0.641 | 0.034x |
| params_digest | 0.508 | 0.027x |
| output_digest | 0.195 | 0.010x |
| direct_replay_no_copy | 18.990 | 1.000x |
| direct_replay_with_copy | 18.869 | 0.994x |
| sealed_atomic_replay | 16.911 | 0.891x |

Standalone bookkeeping sum (copy + validate + compose + two params hashes + output hash): 4.898 ms.
The sum is diagnostic rather than additive ground truth because full validation repeats several hashes.
