# H7C TorchIO 独立框架 transfer 与 adapter 成本复盘

更新日期：2026-07-28

## 1. 协议

选择此前未进入 AutoContract corpus 的 TorchIO v1.0.2。下载源码 blob 前固定 release commit、四个
adapter calibration 单元、七个 sealed operator holdout、决策/理由门槛和成本公式。

只打开 `Transform`、`RandomTransform`、`SpatialTransform`、`IntensityTransform` 与四个 calibration
算子开发 adapter。adapter 冻结后，才逐个打开 holdout 文件并记录源码确认时间。冻结后的 analyzer、
manifest 和 protocol 未修改。

## 2. Calibration

generic analyzer 对四个单元全部返回 Unknown，因此 unsafe false accept 为 0，但 safe recall 为 0。
TorchIO adapter 使用六条结构规则：

1. `Transform.__call__ -> apply_transform` 框架调用约定；
2. `Transform`/`RandomTransform` 的 Torch RNG lifecycle；
3. `Subject` 是一个逻辑样本并保持 lineage；
4. `SpatialTransform` 修改耦合的 `subject.spatial_images` typed subrecord；
5. `IntensityTransform` 修改 `subject.intensity_images` typed subrecord；
6. child container、用户 callable 与外部框架 wrapper 继续输出 Unknown。

校准结果为 4/4：`RandomFlip`/`RandomNoise` 恢复接受，`Compose`/`OneOf` 因 child effect 未解析拒绝。
adapter setup 的单 AI 研究者 wall-clock proxy 为 178.2 秒。

## 3. 冻结 holdout

| 指标 | 门槛 | 结果 | 判定 |
|---|---:|---:|---|
| Generic Unknown reason coverage | 100% | 7/7 | PASS |
| Adapter unsafe false accepts | 0 | 0 | PASS |
| Adapter safe recall | ≥70% | 5/5 | PASS |
| Decision accuracy | 描述性 | 7/7 | PASS |
| Reason-category accuracy | ≥90% | 6/7 (85.7%) | **FAIL** |

失败来自 `MonaiAdapter`。冻结规则将其归入 `unresolved_user_callable`；人工 oracle 要求更具体的
`external_framework_delegation`。最终拒绝决定是安全且正确的，但解释类别未达到预注册门槛。按协议，
不在该 holdout 上修规则重跑。

## 4. 成本敏感性

七个算子的源码确认总计 93.26 秒，均值 13.322 秒/算子，中位数 11.626 秒/算子。冻结 analyzer
执行/审查代理为 0.104 秒/算子。

| 人工成本估计 | break-even 算子数 | 50 算子预计节省 |
|---|---:|---:|
| mean | 13.48 | 72.5% |
| median | 15.47 | 68.4% |

break-even ≤20 在两个口径下都通过；50 算子节省 ≥70% 对均值/中位数敏感，因此为 INCONCLUSIVE。
而且该计时是单 AI 研究者的 source-confirmation proxy，不是完整 EffectV3 人工标注，也不是人类
多评审者实验，不能用于最终论文成本声明。

## 5. 新的 schema 结论

H7C 表明 `target_signature = parametric` 过于粗糙。TorchIO 的 key 数量虽然随 Subject 变化，但
空间变换仍对一个 typed subrecord 保持闭合耦合，可以安全视为单样本 effect。下一版需要：

```text
EffectV4 = EffectV3 + {
  record_scope: whole_record | typed_subrecord | fixed_fields | unknown,
  delegation_kind: none | child_operator | user_callable |
                   framework_bridge | backend_graph
}
```

`record_scope` 用于恢复 parametric-record 上的安全机会；`delegation_kind` 用于区分都应拒绝、但证明义务
不同的 child composition、UDF、跨框架 wrapper 和 backend graph。

## 6. 判断

- 安全/召回机制：通过；
- 预注册的 reason-fidelity transfer gate：失败；
- 成本 break-even 数量级：有利，但 70% reduction 不稳健且缺人类计时；
- 总体：继续 conditional go，不修补本 holdout。

下一步应将 TorchIO holdout 转为 calibration，加入 `delegation_kind`，然后在另一个完全独立框架上冻结
H7D；同时把人工成本实验设计成至少两名参与者、交叉顺序的 per-operator 与 per-adapter 标注任务。
