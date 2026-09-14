# 评审驱动的相关工作增量核查

日期：2026-07-30
范围：用于确认新路线的研究空白，不替代正式 systematic literature review

## 1. 与核心主张最相关的系统

### cedar（PVLDB 2024）

cedar 已经实现跨框架 input pipeline 的 reorder、cache、fusion、offload 与 cost-based plan search，因此 AutoContract 不能声称发明 optimizer boundary 或自动 cache placement。真正相关的空白在 cedar 自己写出的边界：optimizer 遵守用户指定的 dependency/randomness constraints；用户不指定时，系统为保证正确性会禁用相应 reorder/cache，而自动推断 dependency/randomness 被列为 future work。AutoContract 应定位为向这类 optimizer 提供可审计 semantic constraints 的前端，而不是替代 cedar 的成本模型和执行引擎。

来源：[cedar 论文](https://www.vldb.org/pvldb/vol18/p488-zhao.pdf)

### Cachew（USENIX ATC 2022）

Cachew 的 cost/throughput policy 很强，但 `autocache` 的语义安全位置由用户插入，并建议放在随机 transformation 之前；系统假设用户给出的 cache 位置对训练 dynamics 可接受。AutoContract 最直接的增量是自动验证/建议这些允许位置，并将 dataset/configuration/content binding 纳入 invalidation contract。成本模型不应重复 Cachew，而应复用或兼容它的 profile 结果。

来源：[Cachew 论文与项目页](https://www.usenix.org/conference/atc22/presentation/graur)

### Pecan（USENIX ATC 2024）

Pecan 自动 transformation ordering，并在若干 CV/audio workload 上发现放松 commutativity 对最终模型质量影响很小；当约束无法自动检测时仍支持 user hints。它的研究问题偏向“经验上训练质量是否保持”，AutoContract 则试图回答更窄但更强的“某个 rewrite 是否满足显式 output/RNG/state/cardinality/lineage obligation”。论文必须正面比较两种 correctness 定义，不能暗示 Pecan 没考虑正确性。

来源：[Pecan 论文与项目页](https://www.usenix.org/conference/atc24/presentation/graur)

### Seneca（FAST 2026）

Seneca 是当前需要补入 related work 的新系统：它优化 encoded/decoded/augmented 三类 cache 的分区和随机采样，在并发训练中提高吞吐。它进一步说明 cache cost model 与真实系统收益仍是活跃问题，但公开摘要没有表明其目标是从 Python operator 自动推断 rewrite safety。AutoContract 与它的关系仍是 semantic admission 与 performance/cache allocation 的互补，正式写作前需完整阅读全文核对。

来源：[Seneca 论文页](https://www.usenix.org/conference/fast26/presentation/desai)

## 2. 对公平动态基线的启示

Stateful testing 和 property-based testing 的文献说明，只做一次同上下文输出比较明显不足；现代测试会生成调用序列、状态变化和反例。因此 final-v1 必须同时保留历史 `dynamic_output_only` 消融和更强的固定预算 `dynamic_stateful`。但动态测试的未发现反例仍不能升级为 soundness proof，hybrid 的增量应体现在静态/adapter evidence 能否覆盖有限探针无法穷尽的未来 context。

来源：[Stateful Testing](https://arxiv.org/abs/1108.1068)、[Agentic Property-Based Testing](https://arxiv.org/abs/2510.09907)

## 3. 对 Python 分析边界的启示

动态 Python 的 sound 静态分析本身仍很困难。Serenity 等工作依赖 library abstraction 与动态分派建模来获得对特定任务“足够好”的分析，而不是证明完整 Python。这个文献定位支持 AutoContract 使用 adapter-assisted/soundy/fail-closed 的说法，但要求我们报告无 adapter 时的退化、Unknown 分母和 MRO/descriptor/native extension 边界。

来源：[Serenity](https://arxiv.org/abs/2301.05108)

## 4. 本次核查后的创新判断

最有希望且可防守的创新不是“新的 input pipeline optimizer”，而是：

1. 从 framework operator 源码、配置和 phase 中恢复 ML-specific effect contract；
2. 把该 contract 变成 cache/replay/reorder 的候选级、可携带、可失效的 proof obligation；
3. 在同一候选与 cost budget 下证明它相对 user constraint、static-only 和公平 stateful dynamic baseline 的安全/coverage/人工成本权衡。

如果公平 `dynamic_stateful` 在 final corpus 上已经达到 hybrid 的安全性和 coverage，C1 的增量会明显减弱；这因此被提升为正式的 novelty falsification test，而不只是普通 ablation。
