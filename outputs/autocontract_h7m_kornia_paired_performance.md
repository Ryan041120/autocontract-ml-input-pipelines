# H7M randomized end-to-end Kornia batch performance

Batch size: 4; rounds: 10; calls per within-round median: 10.
Issuer work (signing and registry registration) is precomputed and excluded from all three consumer paths.
Median H7L/H7K: 1.538x.
Median H7M/H7K: 1.285x.
Median H7M/H7L: 0.835x; H7M faster rounds: 10/10.
Minimum tensor buffering for this batch: 196608 input bytes + 196608 output bytes (excluding framework/intermediate overhead).

| Round | Order | H7K ms | H7L ms | H7M ms | H7M/H7L |
|---:|---|---:|---:|---:|---:|
| 0 | h7k->h7m->h7l | 31.248 | 48.073 | 43.894 | 0.913x |
| 1 | h7k->h7m->h7l | 26.901 | 49.499 | 41.020 | 0.829x |
| 2 | h7l->h7m->h7k | 33.139 | 47.848 | 41.119 | 0.859x |
| 3 | h7k->h7l->h7m | 33.683 | 49.028 | 41.214 | 0.841x |
| 4 | h7k->h7m->h7l | 31.771 | 49.946 | 41.435 | 0.830x |
| 5 | h7k->h7m->h7l | 31.184 | 48.568 | 42.491 | 0.875x |
| 6 | h7l->h7m->h7k | 31.727 | 48.865 | 37.417 | 0.766x |
| 7 | h7m->h7k->h7l | 30.527 | 46.700 | 38.671 | 0.828x |
| 8 | h7m->h7k->h7l | 29.935 | 44.484 | 40.818 | 0.918x |
| 9 | h7l->h7k->h7m | 30.480 | 46.868 | 38.541 | 0.822x |

H7M buffers the full batch until commit, trading additional latency/memory for stale-worker fencing and a single release boundary.
