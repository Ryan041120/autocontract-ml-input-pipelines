# R3-P3d：ReplayCapabilityV1 分层合成复盘

日期：2026-07-30
证据等级：11 个已知 P3b admits 上的 posthoc capability-composition calibration；不是 blind holdout

## 1. 为什么不叫 EffectV8

P3b 的 `HistogramMatching` 反例没有推翻 EffectV7 的分支可达性结论：给定一个有效 stored-params
record，replay apply 确实不会到达 `read_fn` sampling helper。失败发生在更早的公开 record serialization。

因此 P3d 不修改 Effect IR，而是在 EffectV7 后增加独立的 `ReplayCapabilityV1`：

```text
final eligibility
  = semantic effect
  ∧ framework replay capability
  ∧ SourceIndexV1 deployment binding
```

这样可以区分 semantic Reject、capability Unsupported 和 unresolved Unknown，避免把不同失败原因混成
一个保守拒绝标签。

## 2. 冻结材料

- protocol：`263c1a09a663623780a697160cc71dec1a6270c0ad4fafb71bd2b10bba6378c6`
- runner：`932d8acbaa3e062ccae202e9644cce9a32d39e93d25ad2b6298359344d9efc42`
- result JSON：`8e694749a50b59efc74e722aacfaf40d126e1956da47c502e0dff82986cef949`
- frozen P3a semantic result：`b9986a154a653e7242e09554e9527af1571d2690b9fccbe702cae51ecee0f74c`
- frozen P3c source result：`d66a3ef26bf9e9874c023dbbceb5e4ed197587217c038c1f73f3ff2bf63232ca`

## 3. 结果：7/7 gates，PASS

| Layer | Admit/Supported | Unsupported | Unknown | Reject |
|---|---:|---:|---:|---:|
| EffectV7 semantic | 11 | 0 | 0 | 0 |
| ReplayCapabilityV1 | 10 | 1 | 0 | — |
| SourceIndexV1 | 11 | 0 | 0 | — |
| Final eligibility | 10 | 1 | 0 | 0 |

五个 imgaug units 通过 deterministic flag、公开调用、三次 exact batch replay、caller RNG 和两个输入
image digest binding；五个普通 Albumentations units 通过 public replay record、non-null leaf params、公开
restore/replay、三次 exact output、caller RNG 和 input digest binding。

`HistogramMatching` 的 EffectV7 status 仍为 Admit，SourceIndexV1 仍为 Supported；其
`targets_as_params=['hm_metadata']`，image 与 metadata 都已经 lineage-bound，但公开 record generation
在 serialization 阶段抛出框架 `NotImplementedError`。所以 capability/final status 是：

```text
Unsupported(framework_public_replay_serialization_not_supported)
```

不是 semantic Reject，也不是 Unknown，更不是 Admit。

8/8 composition truth-table cases 通过，确认 semantic Reject 优先；capability Unsupported、capability
Unknown、source Unknown 和 target-dependent-unbound 都不会被提升为 Admit。

## 4. 运行成本与边界

本轮 capability probe 中位约 4.793 ms，receipt 中位 826 bytes。这个时间包含真实 replay 调用，只是
单次 calibration 测量，不是稳定性能 benchmark，也不应放在每样本热路径。receipt 绑定本轮 image/
metadata content、framework mechanism 和检查结果；它没有证明所有未来输入都可 replay。

仍然不覆盖：

- 未见框架或未见输入 schema；
- Python/framework/ABI 跨版本兼容；
- 自动发现完整 callable slot 或 metadata target；
- native internals 和 concurrent TOCTOU；
- 独立 final oracle；
- 真实 end-to-end optimizer benefit。

## 5. R3-P3 总结与下一里程碑

P3a 证明已知两种 replay family 上 EffectV7 zero-change transfer；P3b 用真实 runtime 否证了
`HistogramMatching` capability 和 SourceIndexV0 portability；P3c 修复 portable constants；P3d 用独立
capability layer 修复最终 eligibility。现在内部机制在这 11 个 known admits 上形成了可审计闭环，但它仍是
posthoc calibration。

下一步不应继续为 known units 增加规则，而应进入 final-blind 前置工作：冻结 ReplayCapabilityV1 schema、
自动统计 adapter/slot/target burden，并把新框架/新语料与 oracle 交给独立人员。只有 one-shot final-blind
和真实 workload 能回答论文是否成立。
