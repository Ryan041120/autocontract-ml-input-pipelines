# H7J randomized paired performance

Profiles: 3; paired rounds per profile: 10; iterations per within-round median: 10.
Overall median atomic/direct ratio: 1.250x; atomic faster rounds: 0/30.

| Profile | Median atomic/direct | Range | Atomic faster rounds |
|---|---:|---:|---:|
| B1x3x32x32 | 1.408x | 1.231–1.527x | 0/10 |
| B4x3x64x64 | 1.259x | 1.100–1.323x | 0/10 |
| B8x3x128x128 | 1.100x | 1.063–1.149x | 0/10 |

Randomized order reduces systematic warmup/order bias but does not remove OS scheduling and CPU-frequency noise. Security/correctness remains the primary H7J endpoint.
