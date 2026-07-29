# H7K target-pool scaling on CPU

Workload: B4x3x64x64, 4 client threads, 25 calls/thread, 5 randomized rounds.

| Pool size | Median calls/s | Range | Speedup vs pool=1 | Correct rounds |
|---:|---:|---:|---:|---:|
| 1 | 69.3 | 56.5-72.7 | 1.000x | 5/5 |
| 2 | 78.2 | 73.2-80.7 | 1.129x | 5/5 |
| 4 | 72.1 | 71.7-76.1 | 1.041x | 5/5 |

The pool is required for owned-target isolation under concurrent callers. Throughput scaling is an empirical property, not a safety guarantee.
