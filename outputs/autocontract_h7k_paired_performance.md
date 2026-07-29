# H7K randomized paired performance

Profiles: 3; paired rounds per profile: 10; iterations per within-round median: 10.
Overall median H7K-minimal/H7J ratio: 0.860x; H7K-minimal faster rounds: 29/30.
Overall median H7K-audit/H7J ratio: 0.852x.
Overall median H7K-minimal/direct+copy ratio: 1.053x.
Output auditing multiplier over minimal receipt: 1.020x.

| Profile | Minimal/H7J | Audit/H7J | Minimal/direct | Minimal faster rounds | Registration | Break-even vs H7J |
|---|---:|---:|---:|---:|---:|---:|
| B1x3x32x32 | 0.819x | 0.834x | 1.139x | 10/10 | 8.337 ms | 2.7 calls |
| B4x3x64x64 | 0.819x | 0.825x | 1.053x | 9/10 | 10.194 ms | 4.1 calls |
| B8x3x128x128 | 0.905x | 0.913x | 1.026x | 10/10 | 8.181 ms | 1.4 calls |

Break-even conservatively charges the full H7K registration cost but does not charge H7J sealing cost. Randomized within-round order reduces warmup/order bias; it does not eliminate OS scheduling or CPU-frequency noise.
