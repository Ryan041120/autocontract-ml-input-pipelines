# AutoContract H7C adapter-cost sensitivity

Adapter setup proxy: 178.2 s (2.97 min).
Frozen analyzer run/review proxy: 0.104 s per operator.

| Manual estimator | Manual s/op | Break-even operators | Reduction at 50 |
|---|---:|---:|---:|
| mean | 13.322 | 13.48 | 72.5% |
| median | 11.626 | 15.47 | 68.4% |

Break-even <=20 is **ROBUST PASS** across mean/median.
Projected reduction >=70% at 50 operators is **SENSITIVE / INCONCLUSIVE**.

This is not a human annotation-time result. The manual denominator is only source-confirmation time, and the adapter marginal value is automated execution latency, not a blinded human review. It is useful as an engineering lower-bound pilot only.

The frozen transfer gate remained **FAIL** and is not overridden by the cost calculation.
