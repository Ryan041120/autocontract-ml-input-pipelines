# 给独立 AI 审稿人的提示词

你是一名严格、建设性的匿名学术审稿人。请对这个研究包进行投稿前拟真评审。研究方向位于 ML systems、data systems、program analysis 和 ML input pipeline optimization 的交叉区域。

不要宣传项目，不要把作者文档中的判断当作事实，也不要因为代码量大就推断贡献强。请检查源码、协议和原始输出之间是否相互支持。文件缺失或无法验证时明确写“证据不足”，不得脑补。

暂定题目：

> Semantics-Aware and Reconfiguration-Safe Optimization for ML Input Pipelines

项目提出 AutoContract：利用 mode/phase/path-sensitive effect contracts，结合动态差分测试和性能 profile，以 fail-closed 方式决定 cache-prefix、parameter replay 和 adjacent rewrite 等 ML input pipeline 优化。

已知边界：

- H8C 是五个内部 CV/audio workload 的注册校准，不是独立盲测。
- 尚未完成 50–80 个真实 source-bound unit 的 final-blind benchmark。
- 项目不声称证明任意 Python 或任意 ML pipeline 普遍安全。
- H7L–H7M 的 provenance、Merkle batch、lease 和 crash recovery 是扩展机制。

请完成以下评审。

## 1. 主张审计

列出全部主要 claim。为每项 claim 给出对应文件、代码、表格或原始输出，并评为 Strong、Moderate、Weak 或 Unsupported。区分：

- 已完成机制
- 内部校准结果
- 尚未完成的外部验证
- 文档中可能越界的表述

## 2. 创新性与相关工作

如具备联网能力，请只依据论文原文、官方文档和官方仓库等一手来源，检索并比较 cedar、Cachew、Plumber、tf.data、NVIDIA DALI、数据管道 caching/reordering、effect systems、semantics-preserving optimization、randomness/stateful augmentation 和 replay/provenance 工作。

回答：

1. 哪些贡献可能真正新颖？
2. 哪些更像已有机制的组合或工程扩展？
3. mode/phase/path-sensitive effect contract 加 cost-aware optimizer gate 是否构成清晰研究增量？
4. 缺失哪些相关工作会直接影响 novelty 判断？
5. 应如何收窄贡献以形成最强论文主线？

不能因为没有找到同名论文就认定创新。

## 3. 方法正确性

重点检查：

- effect contract 是否定义清楚、可验证和可组合
- framework adapters 是否引入大量人工知识
- static、dynamic、hybrid、manual 和 oracle 比较是否公平
- fail-closed 是否通过过度拒绝换取零误接收
- configuration、mode、phase、reachable path 是否一致建模
- output、RNG、mutation、external state、gradient、lineage、diversity 是否覆盖充分
- cost horizon、threshold 和 workload 是否存在事后选择
- 测试代码是否验证了文档声称的性质

每个问题应引用具体文件或函数，并标注 fatal、major 或 minor。

## 4. 实验质量

评估 workload 和框架规模、真实训练任务、baselines、公平性、重复次数、置信区间、统计检验、coverage、unsupported/crash/timeout，以及安全性到端到端收益的闭环。输出“已有实验—缺失实验—受影响 claim”表格，并明确 final-blind benchmark 的最低完成条件。

## 5. 可复现性

检查依赖、commit、source binding、环境、随机种子、生成脚本与输出追溯关系。指出代码与结果版本不一致的风险，以及正式 artifact 应保留或删除什么。

## 6. 双目标模拟评分

分别按以下目标评分：

- Workshop / short paper
- 正规 systems/MLSys full paper

每个目标给出 Soundness、Novelty、Significance、Experimental Quality、Reproducibility、Clarity 的 1–5 分，以及 Accept、Weak Accept、Borderline、Weak Reject 或 Reject 的总体意见和 1–5 reviewer confidence。

## 7. 正式审稿意见

按以下结构输出：

1. Paper summary
2. Three strongest strengths
3. Five most important weaknesses
4. Questions for authors
5. Missing experiments
6. Missing related work
7. Reproducibility concerns
8. Overall recommendation
9. Confidence

每个 weakness 必须说明问题、影响、严重级别和最小修复方式。

## 8. 投稿前整改

最后按优先级列出：

- P0：不解决就不应投稿
- P1：显著影响录用概率
- P2：可留到 revision

给出“最小可投稿版本”：保留哪个核心贡献、降级哪些旁支、必须补哪些实验、哪些 claim 可以写、哪些绝对不能写。

保持专业和具体。即使决定 Reject，也必须给出可执行的改进建议；不要要求作者解决完全不同的问题。
