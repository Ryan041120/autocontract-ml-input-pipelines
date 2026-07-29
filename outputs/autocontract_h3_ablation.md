# AutoContract H3 effect-inference ablation

Operators: 30; pipelines: 10; adjacent rewrite occurrences: 37 (15 empirically safe, 22 unsafe).
Effect seeds: 8; validator trials: 8; oracle trials: 48; runtime: 15.78s.

| Mode | Effect coverage | Effect accuracy (resolved) | TP | FP | FN | TN | Safe recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| registry | 20.0% | 100.0% | 6 | 0 | 9 | 22 | 40.0% |
| static | 66.1% | 99.2% | 15 | 0 | 0 | 22 | 100.0% |
| runtime | 100.0% | 98.9% | 15 | 1 | 0 | 21 | 100.0% |
| hybrid | 99.4% | 100.0% | 15 | 0 | 0 | 22 | 100.0% |

## Annotation accounting

- Unique operator signatures: 30.
- Trusted registry signatures: 6 (color_jitter, hflip, identity, normalize, random_crop, resize).
- Hybrid unresolved operators requiring annotation: 1 (external_env).
- Manual signatures remaining: 7/30.
- Annotation reduction: 76.7%.

## H3 gate

- Known unsafe false accepts = 0: **PASS**.
- Safe rewrite recall >=80%: **PASS** (100.0%).
- Annotation reduction >=70%: **PASS** (76.7%).
- Overall H3 pilot: **PASS**.

The rewrite oracle is a higher-budget differential oracle, not a formal proof. Hidden/external-state pairs are manually labeled unsafe to prevent finite-test optimism.
