# AutoContract H8C-R2 novelty falsification

Status: **pass** (9/9)

> Synthetic parameterized threats with known source/oracle; not final benchmark evidence.

## Detection-budget frontier

| Policy | Budget | TP | FP | FN | TN | Safe recall | Unsafe detection | Median ms/case | Calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| effect_v7_style_contract | 0 | 4 | 0 | 0 | 14 | 100.0% | 100.0% | 6.477 | 0 |
| dynamic_stateful_bound | 1 | 4 | 12 | 0 | 2 | 100.0% | 14.3% | 4.728 | 18 |
| dynamic_stateful_bound | 3 | 4 | 11 | 0 | 3 | 100.0% | 21.4% | 7.601 | 54 |
| dynamic_stateful_bound | 7 | 4 | 7 | 0 | 7 | 100.0% | 50.0% | 13.823 | 126 |
| dynamic_stateful_bound | 15 | 4 | 5 | 0 | 9 | 100.0% | 64.3% | 21.734 | 270 |
| dynamic_stateful_bound | 31 | 4 | 3 | 0 | 11 | 100.0% | 78.6% | 45.012 | 558 |
| dynamic_stateful_bound | 63 | 4 | 1 | 0 | 13 | 100.0% | 92.9% | 88.511 | 1134 |

## Family detection by dynamic budget

| Budget | Rare input RNG | Periodic global | Worker/mode RNG | External | Gradient | Source drift |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |
| 3 | 0.0% | 0.0% | 33.3% | 0.0% | 100.0% | 100.0% |
| 7 | 25.0% | 25.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| 15 | 50.0% | 50.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| 31 | 75.0% | 75.0% | 100.0% | 0.0% | 100.0% | 100.0% |
| 63 | 100.0% | 100.0% | 100.0% | 0.0% | 100.0% | 100.0% |

## Interpretation

The contract pilot detects all preregistered unsafe families while preserving four safe controls. Dynamic detection improves monotonically with budget, but finite budgets trade calls for coverage and do not discover an unbound external-file dependency. This supports a narrower hypothesis: source contracts may add value through path/dependency discovery and auditability, not because stateful dynamic testing is intrinsically weak.
