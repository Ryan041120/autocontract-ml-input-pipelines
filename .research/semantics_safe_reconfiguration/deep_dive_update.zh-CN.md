# 深挖更新：把宽题目收窄为 AutoContract

更新日期：2026-07-26

## 1. 更新后的决策

原题 `Semantics-Aware and Reconfiguration-Safe Optimization for ML Input Pipelines` 不宜直接立项。它把多个已有贡献并列在一个宽标题里：cedar/Pecan 已做语义约束下的优化；cedar、CheckFreq、Streaming Batch Model、MegaScale-Data 与 BatchWeave 已覆盖样本去重、checkpoint、弹性、重分片或 exactly-once；DART 已做 noisy-state-aware 在线联合调参。

建议主线改为：

> **AutoContract: Automatic Semantic-Effect Inference for Safe ML Input Pipeline Optimization**

核心问题不是“怎样再做一个快的 dataloader”，而是：

> 给定包含确定性算子、随机增强、跨样本算子和任意 Python UDF 的输入流水线，系统能否自动推断足够保守的语义效应，并只允许可以被契约证明或被反例测试支持的 reorder/cache/fusion/parallelization？

当前判断是 **conditional go，中等置信度**。最强开放证据来自 cedar 明确把 dependency/randomness 自动推断列为未来工作，以及 Pecan 明确承认重排后的数据分布与训练保证仍缺理论框架。

## 2. 为什么原来的重配置叙事需要降级

| 相近工作 | 已经做掉的部分 | 仍未做的部分 |
|---|---|---|
| [cedar](https://www.vldb.org/pvldb/vol18/p488-zhao.pdf) | 用户声明依赖/随机性；静态组合 reorder/cache/offload/fusion/prefetch；UUID 去重与精确 checkpoint；排空后动态 Pipe variant 切换 | 自动推断依赖/随机性；在环境漂移时重新选择整个 logical plan；训练分布级契约 |
| [Pecan](https://www.usenix.org/system/files/atc24-graur.pdf) | 自动重排和 placement；允许 relaxed commutativity；用户用 `keep_position` 设 barrier | 自动发现 barrier；对重排前后数据分布和收敛的普遍保证 |
| [MegaScale-Data](https://arxiv.org/html/2504.09844) | 动态 mixture、source autoscaling、live resharding、fault tolerance | 自动重写/融合 orchestration strategy 被列为 future work；不分析 Python transformation effect |
| [Streaming Batch Model](https://arxiv.org/abs/2501.12407) | partition 级弹性、异构执行和 lineage recovery | 不处理随机增强与可交换性 |
| [Seneca](https://www.usenix.org/system/files/fast26-desai.pdf) | cache 分区与机会式采样；每 epoch exactly once | 语义成立依赖人工假设，不自动证明 transformation 改写 |
| [BatchWeave](https://arxiv.org/abs/2605.09994) | Transactional Global Batch、全 rank 原子可见、step 顺序、端到端 exactly-once | 不分析 operator 语义或安全重排 |

因此，“事务式、exactly-once、可回滚”可以是实现要求，却不能再单独充当论文主贡献。若以后再做动态部分，真正仍可能有区分度的是：**环境变化后重新选择 reorder/cache/fusion/placement 的 whole plan，同时保持自动推断的 ML-specific contract**。

## 3. AutoContract 应该推断什么

给每个 transformation `T` 推断一个 effect signature：

```text
Effect(T) = <reads, writes, shape, dtype, cardinality,
             randomness, statefulness, sample_scope, order_sensitivity>
```

建议第一版只覆盖以下维度：

| 维度 | 典型取值 | 为什么影响优化 |
|---|---|---|
| 随机性 | deterministic / stateless-random / stateful-random | 决定 cache 是否会冻结增强、并行或重排是否改变 RNG 消耗 |
| 样本范围 | per-sample / cross-sample / per-batch / per-epoch | MixUp、CutMix、shuffle、filter 不能按普通 map 算子处理 |
| 读写集合 | image、label、bbox、mask、metadata | 两算子写读冲突时不能仅凭性能交换 |
| 形状与类型 | preserves / changes / input-dependent | Decode、Resize、ToTensor、Normalize 的合法顺序受 dtype/shape 前置条件限制 |
| 基数 | one-to-one / filter / expand | 影响 exactly-once 的定义和 batch 边界 |
| 隐式状态 | none / RNG / counter / external I/O | 决定能否重试、并行、融合或迁移 |

对未知 UDF 的策略必须是 **unknown means fixed**：不能证明时保持原位置、禁止跨越 cache 边界，并给用户一个最小 annotation 接口补充信息。这比声称“理解任意 Python”更可信。

## 4. 四层语义契约

不要把“最终 accuracy 接近”直接叫语义安全。建议把契约分层：

1. **Trace equivalence**：固定 sample ID、epoch 和 RNG key 后，逐元素输出相同。
2. **Distribution equivalence**：允许随机样本不同，但单样本或联合输出分布在预定义统计检验下等价。
3. **Visitation equivalence**：每个 epoch 的样本集合/次数相同，顺序可按训练假设放松。
4. **Task tolerance**：最终准确率、WER 或 loss 在容忍区间内；它只能作为经验结果，不能代替前三层的系统契约。

一个优化计划 `P'` 只有在满足用户选择的契约 `C` 时才可替代原计划 `P`：

```text
P  ≡_C  P'
```

不同优化需要不同证明义务。例如，cache 一个确定性 per-sample 前缀通常要求 trace equivalence；改变 shuffle 顺序可能只要求 visitation equivalence；随机增强重排往往至少需要 distribution-level 检验。

## 5. 最小可行原型

第一阶段不直接改 cedar，也不做完整在线控制器。先用 PyTorch/torchvision 做一个可证伪的小原型：

1. 为 20–30 个 `torchvision.transforms.v2` 算子建立 effect registry。
2. 用 Python AST/bytecode 与运行时 hook 检测常见 RNG 调用、字段访问、输出 shape/dtype 和隐式状态。
3. 用 property-based differential testing 对候选交换、cache placement 和 parallel execution 主动找反例。
4. 写一个小型 plan enumerator，只枚举相邻交换与 cache 点；不确定的改写直接拒绝。
5. 输出两样东西：优化计划，以及每个改写被接受/拒绝的可解释证据。

不建议第一步集成完整 cedar，因为它的依赖和分布式后端会把时间花在工程适配上。先证明 inference/verification 本身有价值，再把约束导出成 cedar 的 `depends_on()`、`fix()` 和 `is_random` 配置。

## 6. 必须包含的反例集

原型不能只在“好用例”上跑通，至少要主动覆盖：

- `RandomCrop → Resize` 与 `Resize → RandomCrop`：输出分布和可见区域会变。
- `ToImage/ToDtype → Normalize`：dtype/range 前置条件不满足时交换非法。
- random transform 后 cache：若 cache key 不含 epoch/operator RNG，会冻结增强。
- 两个共享全局 RNG 的随机算子交换：即使边际分布相似，也会改变联合 RNG trace。
- `Filter`、重复采样与 `Batch`：基数和 batch 边界改变。
- `MixUp/CutMix`：跨样本语义，不能视为普通 per-sample map。
- 带 counter、文件读取或可变全局变量的 UDF：重试/并行可能重复副作用。

## 7. 实验问题与通过线

| 研究问题 | 指标 | 建议通过线 |
|---|---|---|
| RQ1：effect 能否自动推断准确？ | 每个 effect 维度的 precision/recall | unsafe 类 precision 优先；已知不安全案例误接收为 0 |
| RQ2：能否找到人工标注优化器的大部分机会？ | safe rewrite recall、annotation reduction | recall ≥80%；人工 annotation 减少 ≥70% |
| RQ3：安全约束是否仍能带来性能收益？ | samples/s、P95 input wait、GPU stall | 达到人工 oracle 收益的 ≥90%，且无契约违例 |
| RQ4：混合分析是否必要？ | static-only、dynamic-only、registry-only、hybrid ablation | hybrid 明显减少误接收，同时保持可用 recall |

建议基线：原始 PyTorch 顺序、cedar 风格纯人工 annotation、Pecan 风格人工 barrier、static-only、dynamic-test-only，以及人工 oracle。

## 8. 下一轮最值得做的实验

先做一个两周可完成的 feasibility study：

- 选 12 个常见视觉算子和 4 条真实 pipeline。
- 人工建立 ground-truth effect 表。
- 自动检测 RNG、shape/dtype、读写字段和 per-sample/cross-sample。
- 生成所有相邻交换候选，跑差分反例测试。
- 报告 confusion matrix、被拒绝原因、找到的安全改写数量与吞吐变化。

如果连 12 个算子都无法同时做到“零已知 unsafe 误接收 + 有意义的 safe recall”，就应尽早停止 AutoContract。若通过，再扩展到 30 个算子、10 条 pipeline 和视觉之外的一类 workload。

## 9. 可以直接对学长说的版本

> 我继续查了 cedar 的实现、Pecan 的讨论部分以及 2025–2026 的被引工作。原来的宽题目需要再收窄：cedar 已经有语义约束优化、样本 UUID 去重、精确 checkpoint 和运行时 Pipe 切换；MegaScale-Data、Ray Data、BatchWeave 又分别覆盖弹性、重分片和 transactional exactly-once，所以这些不能单独作为创新。现在最清楚的缺口是，cedar 和 Pecan 都依赖用户标注随机性或顺序约束，Pecan 还明确承认缺少重排前后数据分布与训练保证。我建议先做 AutoContract：自动推断 transformation 的随机性、读写、状态和样本范围，用保守契约判断 reorder/cache/fusion 是否安全；未知 UDF 不证明就不改写。第一阶段用 torchvision 20–30 个算子验证推断精度、安全改写 recall 和性能收益，通过后才把 whole-plan 在线重优化作为第二阶段。
