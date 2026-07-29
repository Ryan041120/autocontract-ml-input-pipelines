# H7I Kornia scaling robustness

Profiles: 3; seeds per profile: 5; trials: 15; iterations per timing median: 15.
Replay faster trials: 10/15; overall median speedup: 1.074x.

| Profile | Median speedup | Range | Faster trials | Median validation/replay |
|---|---:|---:|---:|---:|
| B1x3x32x32 | 1.166x | 0.978–1.351x | 4/5 | 14.1% |
| B4x3x64x64 | 1.096x | 1.001–1.221x | 5/5 | 7.2% |
| B8x3x128x128 | 0.961x | 0.907–1.009x | 1/5 | 1.6% |

Performance is a secondary pilot outcome. Correctness and rejection of mismatched lineage remain the primary H7I outcomes.
