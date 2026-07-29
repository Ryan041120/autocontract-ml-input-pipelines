# AutoContract H7C frozen TorchIO operator holdout

Generic Unknown coverage: 7/7 (100.0%).
Generic safe recall: 0.0%.
Adapter unsafe false accepts: 0.
Adapter safe recall: 5/5 (100.0%).
Decision accuracy: 7/7.
Reason-category accuracy: 6/7 (85.7%).
H7C transfer gate: **FAIL**.

| Unit | Generic | Adapter | Correct | Reason match | Adapter reason |
|---|---|---|---:|---:|---|
| `RandomAffine` | reject | admit | yes | yes | none |
| `RandomBlur` | reject | admit | yes | yes | none |
| `RandomGamma` | reject | admit | yes | yes | none |
| `RandomMotion` | reject | admit | yes | yes | none |
| `RandomSwap` | reject | admit | yes | yes | none |
| `Lambda` | reject | reject | yes | yes | analysis_unknown;unresolved_user_callable |
| `MonaiAdapter` | reject | reject | yes | no | analysis_unknown;unresolved_user_callable |

A failed reason-category gate is retained as a holdout failure; the frozen adapter is not repaired here.
