# AutoContract H5b: real ResNet-18 training-path pilot

Samples: 600; epochs: 4; batch size: 64; workers: 2; paired repeats: 2; device: CUDA.
Each run creates the same ResNet-18 initialization and executes forward, backward, and SGD step.

| Policy | Runtime median [Q1,Q3] | First batch | Data wait | Compute | Samples/s | Median / p95 step | GPU util mean / p95 | Final loss | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| uncached | 18.79 [18.60,18.98]s | 11.42s | 5.80s (30.9%) | 1.25s | 127.8 | 0.136/0.371s | 11.5%/30.5% | 0.09921 | 0.838 |
| cached | 13.61 [13.60,13.61]s | 10.86s | 1.08s (7.9%) | 1.07s | 176.4 | 0.052/0.085s | 11.8%/47.1% | 0.09921 | 0.838 |

## Semantic equivalence

- Batch trace identical: **True**.
- Loss trace allclose: **True**; maximum difference 0.000e+00.
- Final model digest identical: **True**.

## Horizon-aware admission

- Warm-cache training speedup: 1.38×.
- H5a predicted cold break-even: 10.41 epochs; requested horizon: 4.
- Cold cache: rule says REJECT; measured optimum is NO CACHE; correct=True.
- Reusable warm cache: rule says ACCEPT; measured optimum is CACHE; correct=True.
- Naive cold-cache total: 25.11s versus uncached 18.79s.

## Gate verdict

- Semantic trace/model gate: **PASS**.
- Warm training speedup >=1.20×: **PASS**.
- Cold/warm admission decisions both correct: **PASS**.
- H5b pilot: **PASS**.

This is a real training execution but not a model-quality claim: the dataset contains deterministic crops from seven source photographs and is intended only to stress the systems path.
