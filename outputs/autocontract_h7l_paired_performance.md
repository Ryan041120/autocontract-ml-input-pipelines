# H7L randomized paired and component performance

Profiles: 3; paired rounds/profile: 10; calls/within-round median: 10.
Overall median H7L/H7K ratio: 1.235x; H7L faster rounds: 3/30.
Token issuance is measured separately and excluded from consumer-path paired timing.

| Profile | H7L/H7K | Range | Absolute overhead | H7L faster rounds |
|---|---:|---:|---:|---:|
| B1x3x32x32 | 1.384x | 1.301-1.556x | 3.655 ms | 0/10 |
| B4x3x64x64 | 1.127x | 0.879-1.307x | 1.974 ms | 3/10 |
| B8x3x128x128 | 1.092x | 1.025-1.269x | 5.131 ms | 0/10 |

| Profile | Issue+register | Verify claims | Registry consume | Seal input+digest |
|---|---:|---:|---:|---:|
| B1x3x32x32 | 3.909 ms | 0.324 ms | 3.549 ms | 0.036 ms |
| B4x3x64x64 | 3.980 ms | 0.357 ms | 3.477 ms | 0.219 ms |
| B8x3x128x128 | 4.083 ms | 0.374 ms | 3.749 ms | 2.325 ms |

SQLite commits provide a durable cross-process baseline, not a claim of optimal registry design. Randomized order reduces systematic order bias but does not eliminate OS/filesystem noise.
