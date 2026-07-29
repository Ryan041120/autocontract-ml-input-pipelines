# AutoContract stateless-RNG H4 benchmark

Images: 48; epochs: 6; timing repeats: 5.
Warm-up is excluded; timings include output hashing and first-epoch cache construction.

| Policy | Runtime median [Q1, Q3] (s) | Images/s | Runtime vs native | Speedup vs stateless/no-cache | Post-epoch-0 trace match | Mean epoch diversity |
|---|---:|---:|---:|---:|---:|---:|
| native:none | 1.0131 [0.9459, 1.0289] | 284.3 | 1.000x | 0.87x | not_comparable | 6.00 |
| stateless:none | 0.8786 [0.8758, 0.9534] | 327.8 | 0.867x | 1.00x | 1.000 | 6.00 |
| stateless:prefix | 0.5837 [0.5547, 0.5853] | 493.4 | 0.576x | 1.51x | 1.000 | 6.00 |
| stateless:full | 0.2087 [0.1991, 0.2108] | 1380.2 | 0.206x | 4.21x | 0.000 | 1.00 |

## Isolated random-suffix timing

This removes Gaussian blur and resize so deterministic work cannot hide RNG-control overhead.

| Policy | Runtime median [Q1, Q3] (s) | Images/s | Runtime vs native suffix |
|---|---:|---:|---:|
| native:random_suffix | 0.5197 [0.4982, 0.5529] | 554.2 | 1.000x |
| stateless:random_suffix | 0.4600 [0.4453, 0.4682] | 626.0 | 0.885x |

## Stable-ID reorder validation

| Pair | Pass rate | Maximum absolute error |
|---|---:|---:|
| fixed_gaussian_blur<->random_hflip | 1.000 | 2.980e-07 |
| random_hflip<->random_vflip | 1.000 | 0.000e+00 |
| color_jitter<->random_hflip | 1.000 | 7.153e-07 |

## Native/stateless output-distribution diagnostic

- RBF-MMD²: 0.0032986
- Permutation p-value (199 permutations): 0.4850
- Difference detected at α=0.05: False

This finite-sample test can detect a discrepancy but cannot prove equal distributions.

## Gate verdicts

- H4, stateless overhead <= 5% in both tests: **PASS** (end-to-end -13.28%; random suffix -11.48%).
- Prefix-cache post-epoch-0 trace = 100%: **PASS**.
- Three stable-ID reorder tests = 100%: **PASS**.
- Full-cache diversity guard detects frozen augmentation: **PASS**.

Interpretation: a successful result supports replacing RNG-state mutation with operator-addressed functional draws. It does not yet establish end-to-end training equivalence, cross-version reproducibility, or cryptographic PRNG quality.
