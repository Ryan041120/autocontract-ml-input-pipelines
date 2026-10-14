# P5T attempt3-v4 calibration postmortem

日期：2026-08-11

## 结论

P5T attempt3-v4 完成了一次完整、fresh、8-block、CPU-warm、DIV2K validation
calibration-only M0 experiment。该运行闭合了 freeze、launcher、execution closure
和 aggregate 验证链，并确认没有复用旧 partial aggregate 或旧 child performance。

该结果只允许逐点描述。aggregate 标记 `scientific_evidence=false`，不得据此提出
pooling、confidence interval、Go/No-Go、总体加速、统计显著性、泛化、因果、cold
cache、GPU 或正式 test-set 性能主张。

## 授权与前置

正式运行前，runner、contracts、launcher generator、schema、core、protocol、split
和固定 Python hash 均通过预检。首次正式控制面尝试在 freeze 发布前失败，错误为
`Attempt3Error:v14_missing`；未启动 formal launcher，未产生 freeze、launcher、
execution closure 或 aggregate。

随后仅补齐既定 no-data prerequisites，并只运行一次 fresh attempt。五个 no-data
prerequisites 均一次通过：

| Artifact | SHA-256 |
|---|---|
| v14 selftest | `6573e001ef06edb95cd42bdc1e5f7c01c9af675ffc2a1e13a396453dd2218d7f` |
| orchestration smoke-v6 | `b47d2f9820a552497f7ad4d7270c339ed584a8eeef47438d0ea49fa6b05c9bb2` |
| launcher smoke-v6 | `0aab7d2fc18281a2368a3c64c61e86fc0e3809d2f7322b4a2c341e31a28ade87` |
| Cedar smoke-v6 | `2275672baee9b5d6649095d4ba5b31a637ccf42f9164e794e80ac120b9822ae5` |
| independent review-v6 | `e76e602781304b993ed6dca1fc7cb0e3ae460b1ebad4b52383544736d27ca4cd` |

## 冻结链

| Artifact | SHA-256 |
|---|---|
| freeze-v8 | `e2a53d1c57923c21482fa3b5c39d73c8f418b784cd87d68d5cae52d72a5d1e02` |
| launcher-v8 | `c2e226e5ef85f93b3ee81de9e5fb5c3b8ad5802c4fe4dd7f282c7ad77827e910` |
| execution-v8 | `892f9e1090ea60a141c9e012611c17b9b2057b9a78828aa4e40fd56315e2ad7c` |
| aggregate | `8801942b31a08850c83e5694b6c52a3dcf3568754cbb2147543eafbf68cdf7c4` |

Formal launcher invocation count was exactly one. It exited with code 0 after
about 498.7 seconds.

## Calibration Points

| Ordinal | Sequence | Cell | Symmetric point |
|---:|:---:|---|---:|
| 1 | CAAC | mobilenetv3_crop224 | 0.8987305405 |
| 2 | CAAC | resnet18_crop448 | 0.9278660885 |
| 3 | CAAC | mobilenetv3_crop448 | 0.9033743360 |
| 4 | CAAC | resnet18_crop224 | 0.9242525766 |
| 5 | ACCA | resnet18_crop224 | 0.9313954509 |
| 6 | ACCA | mobilenetv3_crop448 | 0.8284326764 |
| 7 | ACCA | resnet18_crop448 | 1.0021457706 |
| 8 | ACCA | mobilenetv3_crop224 | 0.9408559487 |

## Validation

The final aggregate independently passed canonical-byte checks, schema-v4,
runner `validate_aggregate`, all eight `Core.validate_block` checks, child
hash/identity/auth bindings, fixed schedule verification, and split-isolation
checks.

Post-run checks confirmed:

- `fresh_attempt_only=true`
- `old_partial_aggregate=false`
- v4 lock/work/stage state absent
- matching live Python processes absent
- old v11, v12, and v13 failure-scene hashes unchanged
- no v13 partial performance was read, reused, or reported

## Boundary

P5T is useful as a control-plane closure and calibration record. It cannot
overturn the P5S benefit No-Go result, and it is not a replacement for an
independent final-blind run with real selector, oracle custodian, annotators,
sealed prediction, and reveal.
