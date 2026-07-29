# H7D EffectV4 与 TorchGeo 零源码 holdout 复盘

更新日期：2026-07-28

## 1. EffectV4 calibration

H7C 完成后，将全部11个 TorchIO 单元转入 calibration。EffectV4 新增：

```text
record_scope = whole_record | typed_subrecord | fixed_fields | unknown
delegation_kind = none | child_operator | user_callable |
                  framework_bridge | backend_graph
```

结构规则不使用 `MonaiAdapter` 类名：framework loader + wrapped transform invocation 归为
`framework_bridge`；stored callable invocation 归为 `user_callable`；child transform traversal 归为
`child_operator`。校准达到决策11/11、reason category 11/11，满足冻结条件。

## 2. H7D 协议

选择此前未使用的 TorchGeo v0.9.0。根据公开 API 文档、而非仓库源码 blob，预先写入五条 adapter 事实：

1. Kornia augmentation base 提供 `forward -> hook` 执行语义；
2. `apply_transform`、`generate_parameters`、`compute_transformation` 是 execution hooks；
3. 内置 TorchGeo transform 使用固定 Tensor record scope；
4. Kornia 参数生成是已解析的 Torch RNG delegation；
5. `repeat_interleave` 或 gamma 扩张 batch 表示 one-to-many output。

EffectV4、V4 manifest、TorchGeo adapter、adapter manifest、protocol、release commit 与五个单元在打开
`color.py`、`indices.py`、`spatial.py` 前全部哈希冻结。

## 3. 一次性正式结果

| 指标 | 门槛 | 结果 | 判定 |
|---|---:|---:|---|
| Known-unsafe false accepts | 0 | 0 | PASS |
| Safe recall | ≥75% | 3/4 (75%) | PASS |
| Reason-category accuracy | ≥90% | 4/5 (80%) | **FAIL** |
| Resolved coverage | ≥80% | 4/5 (80%) | PASS |

因此 **H7D blind gate：FAIL**。

成功部分包括：`RandomGrayscale`、两种 normalized-difference index 正确接受；`SatSlideMix` 的
`repeat_interleave(gamma)` 被识别为 `one -> many` 并拒绝，unsafe false accept 仍为0。

失败单元是 `Rearrange`。protocol 将其错误绑定到 `spatial.py`，实际定义在 `temporal.py` 并由
`torchgeo.transforms.__init__` re-export。正式运行因此返回 `sealed_source_unit_missing:Rearrange`。

## 4. 事后诊断（不计入 gate）

在正式失败后才打开 `temporal.py`。不修改冻结 adapter，只将同一 `Rearrange` 指向真实定义文件的
counterfactual 得到：

```text
status = resolved
record_scope = fixed_fields
cardinality = one -> one
decision = admit
```

这说明唯一错误是 symbol-origin binding，而不是 EffectV4 effect inference；但它仍是协议/系统失败，
不能用 counterfactual 将正式 H7D 改写成 PASS。

## 5. 新方法学要求

blind source seal 不能只固定 repo、commit、类名和猜测路径，还必须固定并验证：

```text
public_symbol
  -> export module
  -> defining module
  -> source hash
```

应在不读取函数/类 body 的 metadata phase 解析 package re-export graph；若无法证明 defining module，
unit 必须在运行前标成 unresolved sample，而不能静默归因给 analyzer。

## 6. 当前判断

- H7B：跨 release 通过；
- H7C：安全决策通过、reason fidelity 失败；
- H7D：unsafe false accept=0、EffectV4 语义诊断有利，但正式协议因 symbol binding 失败；
- adapter-assisted AutoContract 继续 conditional go，尚不足以声称稳定的端到端自动 contract inference。

下一轮优先级不是立刻再找第五个框架，而是实现可审计的 symbol-origin sealer，并把 reason fidelity 拆成
`safety reason` 与 `diagnostic subtype` 两层；随后才能设计不会被样本绑定错误污染的 H7E。
