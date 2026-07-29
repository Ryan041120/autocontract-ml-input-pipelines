# AutoContract EffectV4 calibration

Decisions: 11/11; reason categories: 11/11.
Freeze ready: **YES**.

| Unit | Scope | Delegation | Decision | Reason |
|---|---|---|---|---|
| `Compose` | typed_subrecord | child_operator | reject | unresolved_child_effect |
| `OneOf` | typed_subrecord | child_operator | reject | unresolved_child_effect |
| `RandomFlip` | typed_subrecord | none | admit | none |
| `RandomNoise` | typed_subrecord | none | admit | none |
| `RandomAffine` | typed_subrecord | none | admit | none |
| `RandomBlur` | typed_subrecord | none | admit | none |
| `RandomGamma` | typed_subrecord | none | admit | none |
| `RandomMotion` | typed_subrecord | none | admit | none |
| `RandomSwap` | typed_subrecord | none | admit | none |
| `Lambda` | typed_subrecord | user_callable | reject | unresolved_user_callable |
| `MonaiAdapter` | typed_subrecord | framework_bridge | reject | external_framework_delegation |
