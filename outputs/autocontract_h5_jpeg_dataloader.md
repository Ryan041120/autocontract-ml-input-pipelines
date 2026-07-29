# AutoContract H5a: JPEG/DataLoader prefix-cache benchmark

Dataset: 600 deterministic crops from 7 bundled real photographs (astronaut, camera, chelsea, coffee, rocket, hubble_deep_field, immunohistochemistry), exported as 224×224 JPEG (quality 92) in an ImageFolder-compatible tree.
Epochs: 4; batch size: 64; paired repeats: 2; consumer: CUDA.
JPEG export performed in this run: False (0.00s). Prefix cache rebuilt in this run: False (11.51s).

| Workers | Total uncached→cached (s) | First batch uncached→cached (s) | Post-first-batch samples/s | End-to-end speedup | Steady speedup | Steady input-wait | Trace | Break-even | Offline amortized speedup | H5a |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 12.68→3.72 | 0.35→0.10 | 189.5→646.4 | 3.41× | 3.41× | 99.7%→99.1% | 1.000 | 5.14 epochs | 0.83× | PASS |
| 2 | 17.38→12.68 | 10.60→10.20 | 344.3→941.5 | 1.37× | 2.73× | 90.9%→75.1% | 1.000 | 10.41 epochs | 0.72× | PASS |
| 4 | 25.92→22.21 | 21.48→20.44 | 526.6→1324.8 | 1.17× | 2.52× | 83.0%→57.5% | 1.000 | 16.76 epochs | 0.77× | PASS |

## Verdict

- H5a steady-state gate (>=1.20× and exact trace): **PASS**.
- Steady-state metrics exclude the first batch, which contains DataLoader worker spawn and initial prefetch.
- Cache construction is treated as an extra offline pass; the amortized figure is deliberately conservative.
- H5b is not yet a training result: the CUDA consumer only transfers, normalizes, and reduces each batch.
- This is a systems-path pilot over seven real source photographs; content diversity is insufficient for a training-quality dataset claim.
