# 研究选题决策档案：ML 输入流水线的安全在线重优化

## 1. 决策摘要

| 字段 | 内容 |
|---|---|
| 研究区域 | Cachew / Pecan 后续：非平稳环境中的 ML 输入流水线优化 |
| 编制日期 | 2026-07-26 |
| 结论级别 | 筛选级：汇总证据，供学生与导师决定，不替代最终立项判断 |
| 检索置信度 | 中等：已做多组对抗性检索并核查主要相近系统，但未使用可重复的学术数据库全量导出 |

本档案评估一个经过收窄的候选题目；同时把更宽泛的“动态调 DataLoader worker”明确排除。

| 候选题目 | 带不确定性与切换成本约束的 ML 输入流水线安全在线重优化 |
|---|---|
| **判断** | **只有在开放条件成立时才值得继续** |
| **原因** | 动态 worker 分配已被 A-Dloader、cedar、DART 和 MegaScale-Data 大量覆盖；可能尚未被完整解决的是：对 placement、parallelism、cache、order 等整个计划做带置信度、切换成本、退化上界和回滚预算的安全试探。我们的连续实验中，朴素自适应反而慢 34.2%，说明这个失败模式是真实的，但还不能证明该解法具有论文级新颖性。 |

**关键不确定性。** DART 已经使用状态估计和限速更新，MegaScale-Data 已考虑动态扩缩与 rescaling cost；只有在完整论文核查确认它们没有提供“整个输入计划的置信度约束安全重优化”后，候选题目的边界才算站稳。

## 2. 候选题目定义

**带不确定性与切换成本约束的 ML 输入流水线安全在线重优化。** 当 CPU、I/O、网络、数据混合比例或 transformation 开销发生持续变化时，系统决定是否以及如何从当前执行计划切换到新计划；决策同时考虑性能估计的不确定性、探测和重建成本、剩余阶段长度、语义约束与可回滚性。*为什么它可能是缺口：* **现有方法仍有不足**——已有系统分别覆盖静态全局计划、动态 worker 扩缩、状态感知资源协同和多源 autoscaling，但目前核查到的工作尚未同时给出“全计划、置信度约束、显式失败探测成本、最坏退化上界”这组能力。

本题不把以下内容声称为创新：运行时增加/减少 DataLoader worker、简单阈值检测、只按平均 batch time 选配置、无代价的周期性重搜、把 cache/offloading/reorder/placement 放进同一个静态优化器。

## 3. 三道门评分

| 门槛 | 评分 | 理由 |
|---|---:|---|
| 门槛 1：缺口仍开放 | 3/5，中性偏开放 | 宽泛版本已被占据；只有“整个计划 + 置信度安全 + 显式失败探测成本和回滚预算”的交集可能仍部分开放。 |
| 门槛 2：能形成真实贡献 | 3/5，中性 | 若只做 worker 控制或加一个 change detector，属于重复或小改；若能证明带退化上界的 staged/canary 计划切换解决已有系统未处理的失败模式，才可能形成问题解决型贡献。 |
| 门槛 3：可行 | 4/5，同意 | 本地 RTX 4060 与 Pecan 源码足够做最小原型；已建立可复现实验脚本并观测到失败模式。完整 cedar/Pecan 集成和分布式评估仍需额外工程与集群资源。 |
| **判断** | **只有在开放条件成立时才值得继续** | 三道门均未失败，但新颖性只处在临界状态；先完成升级/终止测试，再决定是否扩成论文题目。 |

## 4. 证据基础

**检索漏斗。** 下列数量来自本轮手工 URL/标题去重日志，不是数据库 API 的精确全量统计。

| 阶段 | 数量 |
|---|---:|
| 对抗性查询返回的去重候选记录 | 41 |
| 打开摘要或正文进行相关性筛选 | 22 |
| 通过 ML 输入流水线相关性门槛 | 11 |
| 纳入相近工作语料库 | 11 |

**11 篇相近工作的分类。**

| 按证据类型 | 与候选题目的关系 |
|---|---|
| 9 篇正式发表的系统研究，2 篇已接收或预印本 | 6 篇直接占据动态调参或计划优化的部分能力，3 篇占据缓存/批处理/多租户相邻能力，2 篇提供静态或离线调优基线 |

**最接近的工作。**

- **DART（正式论文）**：在 epoch 边界联合调整数据分片、batch size、DataLoader worker 和学习率；用 Cubature Kalman filter 估计状态，并采用限速更新。它直接否定“状态感知动态 worker 调节是新问题”。
- **cedar（正式论文）**：静态优化器组合 reordering、fusion、offloading、cache 和 prefetch，运行时 Auto-Tuner 动态 right-size 并行度或执行 variant。它否定“统一多种优化即可构成创新”。
- **MegaScale-Data（EuroSys 2026 正式论文）**：按动态数据混合比例扩缩 Source Loader，支持 live resharding，并在代价模型中分析 rescaling cost。它进一步压缩“动态扩缩 + 切换成本”的空间。
- **A-Dloader（正式论文）**：在并发 DDL 作业之间运行时重分配 DataLoader worker，并建模 CPU/I/O contention。它占据多作业 worker 重分配。
- **Pecan（正式论文）**：自动 transformation 排序和 local/remote placement；本地源码显示 AutoPlacement 进入稳定状态后不再主动重搜，这给“整计划重新打开”留下机制入口，但不等于新颖性已成立。
- **InTune（正式论文）**：用强化学习在线分配 trainer CPU 资源，说明“使用 RL 做自适应”本身也不能作为贡献。

详细逐篇比较见 `literature_matrix.md`。

## 5. 分门评估

### 门槛 1：缺口仍开放

- **评分：** 3/5，中性偏开放。
- **证据：** Plumber、DPT 和 Pecan 覆盖离线或早期调优；cedar 将复杂组合优化与运行时并行度 right-sizing 分开；A-Dloader、InTune、DART 与 MegaScale-Data 已实现不同层次的在线资源适配。当前未检索到一篇同时对整个输入计划进行置信度约束的 staged/canary 切换，并把失败探测造成的实际训练退化作为一等目标。
- **解释：** “动态调 worker”已被占据；“安全地重开整个计划”只可称为部分开放，不能称为无人尝试。
- **风险：** DART 全文和同领域 2025–2026 新作仍可能包含更强的安全策略；当前检索没有学术数据库全量召回保证。
- **所需行动：** 精读 DART 与 MegaScale-Data 的控制器、消融和失败案例；用 Google Scholar/Semantic Scholar 的 cited-by 与 related-work 链补查“safe exploration、canary、regret bound、reconfiguration cost、rollback”。

### 门槛 2：真实贡献

- **评分：** 3/5，中性。
- **证据：** 已有工作已分别实现动态 worker、状态估计、限速更新、autoscaling、live resharding 和 rescaling-cost 分析。因此，本题只能把贡献压在“全计划动作空间 + 不确定性估计 + 失败探测预算 + 最坏退化限制”这一组合上。
- **解释：** 当前属于临界扩展型贡献。若方法只是在 EWMA/CUSUM 后重新创建 DataLoader，则贡献不足；若能给出可验证的安全性质或经验上严格的退化上界，并在已有在线方法容易失败的短阶段和噪声阶段保持收益，才升级为问题解决型贡献。
- **风险：** 本地实验中的巨大重建时间可能主要来自 Windows/PyTorch 进程启动，而非可泛化的系统现象；若如此，当前 construct 只测到实现细节。
- **所需行动：** 在 Linux、真实数据集和至少两个输入系统上复现实验；比较 fixed、周期重搜、DART-like 限速控制、无安全门控的 change-aware 与拟议的 confidence-gated staged controller。

### 门槛 3：可行

- **评分：** 4/5，同意。
- **证据：** 已有本地 RTX 4060、12 线程 CPU、PyTorch CUDA 环境、Pecan 源码，以及 toy、离线 worker sweep 和连续切换实验。离线测试曾预测 6 worker 在 contention 下更优，但连续实验中的 6-worker probe 变差并触发回滚；完整计费后 fixed-8 为 92.49 秒，朴素 change-aware 为 124.12 秒，后者慢 34.2%，其中重配置耗时 38.46 秒。
- **解释：** 失败模式已能在单机重现，适合做最小研究原型；约束项是跨平台与跨流水线外部有效性，而不是能否写出控制器。
- **风险：** 单机 synthetic augmentation、一个 GPU 和 Windows 进程模型不足以支持论文结论；Pecan/cedar 的集成成本高于纯 PyTorch 原型。
- **所需行动：** 先做 Linux + CIFAR/ImageNet 子集的两模型实验，再决定是否修改 Pecan 或 cedar。只有单机原型通过终止测试，才申请多机资源。

## 6. 风险与升级/终止测试

**已命名风险。**

- **构念有效性风险：** 重配置开销可能来自 Windows worker 冷启动，而非 input-plan reoptimization 的普遍代价。
- **工作负载约束风险：** synthetic augmentation 的 per-sample cost 和真实 CV/ASR/LLM 流水线不同，最优 worker 漂移可能不稳定复现。
- **新颖性风险：** DART、cedar 与 MegaScale-Data 已实现候选题目的多个较弱版本；组合已有部件并不自动形成新贡献。
- **可复现性风险：** contention 注入、后台进程调度和 OS page cache 会显著影响测量；必须固定随机种子、预热、扰动强度和完整 trace。

**升级/终止测试：带不确定性与切换成本约束的安全在线重优化。** 只有以下条件全部成立才升级为论文候选：

1. 完整精读 DART、cedar、MegaScale-Data 与它们的引用链后，没有发现系统已经对“整个输入计划”同时实现置信度门控、显式失败探测预算、可回滚切换和退化上界；
2. 在至少两个真实数据集/模型、两类持续扰动上，固定计划相对 phase oracle 的总训练时间或成本差距稳定超过 10%；
3. 计入所有 profiling、probe、shutdown、startup、cache warm-up 和 rollback 成本后，安全控制器优于 fixed 与 DART-like/周期性重调基线，并恢复至少一半 oracle gap；
4. 在无变化、短变化和高噪声情形中，安全控制器相对最佳固定基线的总运行时间退化不超过 2%，错误切换每阶段少于一次；
5. 在 Linux 与另一种输入流水线实现上复现主要结论，证明结果不是 Windows DataLoader 冷启动特例。

任一条件失败，就终止“通用在线重优化系统”叙事。可保留的窄化成果是：系统性测量 ML 输入流水线 reconfiguration/probing 的成本与不稳定性，形成 benchmark、经验研究或给 Pecan/cedar 的设计反馈。

## 7. 建议下一步

不应继续把“动态调 DataLoader worker”或“把 Cachew、Pecan、cedar 的优化统一起来”作为研究题目。这些表述已被 A-Dloader、DART、cedar 和 MegaScale-Data 直接覆盖，继续沿此表述推进很容易变成重复实现。

可以保留一个有条件的窄题目：**安全在线重优化不是追求每次变化都切换，而是限制错误试探给真实训练带来的损失。** 下一阶段只做三个动作：完成 DART/MegaScale-Data 全文查重；把连续实验移到 Linux 和真实数据；实现不破坏主流水线的 staged/canary probe 与置信区间门控。完成第 6 节的升级测试后，再由你和学长决定是否正式立项。

---

## 附录 A：检索与筛选协议

| 字段 | 内容 |
|---|---|
| 检索日期 | 2026-07-26 |
| 检索来源 | arXiv、USENIX、PVLDB、IEEE/NSF Public Access、Elsevier DOI 页面及通用网页检索；research-hub CLI 不可用 |
| 查询族 | ML input pipeline + online reconfiguration；adaptive/dynamic scaling + contention；DataLoader worker allocation；non-stationary input preprocessing；reconfiguration cost；safe online adaptation；operator placement/cache/reordering + runtime；limitations/failure/overhead |
| 去重规则 | 以 DOI、arXiv ID 或规范化标题去重；同一论文的旧标题与新版标题合并，例如 OVERLORD 与 MegaScale-Data |
| 纳入标准 | 直接优化 ML training 输入加载、预处理、缓存、排序、放置、扩缩或其运行时控制 |
| 排除标准 | 通用数据库/Spark 调优只作方法类比，不进入核心语料；模型并行、推理 serving、通用集群调度且未触及输入流水线者排除 |
| 筛选过程 | 手工查看标题/摘要；对最接近工作打开正文相关章节；本档案中的“尚未发现”是证据范围内的推断，不是全领域不存在的断言 |
| 已知限制 | 未获得可重复的数据库批量导出和被引网络全量结果；DART 主要依据出版方摘要和 DOI 元数据，仍需取得全文复核 |
| 召回置信度 | 中等；正式立项前必须补一次数据库和引用链复核 |

## 附录 B：交付文件

| 文件 | 用途 |
|---|---|
| `topic_dossier.md` / `.docx` | 选题判断、三道门证据与升级/终止条件 |
| `topic_dossier.bib` | 含可解析 DOI 或 arXiv ID 的参考文献 |
| `literature_matrix.md` | 逐篇相近工作比较与占位分析 |
| `topic_dossier.gaps.yml` | 机器可读的候选题目、评分和开放问题 |
