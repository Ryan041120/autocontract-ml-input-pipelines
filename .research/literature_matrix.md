# ML 输入流水线在线优化：相近工作矩阵

更新日期：2026-07-26

本矩阵只记录与“输入流水线计划是否应在运行时安全重优化”直接相关的工作。所有“未见”均表示在本轮读取范围内未找到，不等价于论文绝对没有相关实现。

| 工作 | 证据类型 | 已解决的问题 | 动态性与动作空间 | 与候选题目的重叠 | 本轮核查到的边界 |
|---|---|---|---|---|---|
| [Cachew, ATC 2022](https://www.usenix.org/conference/atc22/presentation/graur) | 正式系统论文 | 服务化预处理、按吞吐扩缩、自动选择重算或缓存 | 运行时 worker 扩缩；cache 决策以 profiling 为主 | 占据 autoscaling 与 cache choice | 未形成 whole-plan 的置信度安全重优化 |
| [Pecan, ATC 2024](https://www.usenix.org/conference/atc24/presentation/graur) | 正式系统论文 | transformation reordering 与 local/remote hybrid placement | 训练早期搜索 worker placement；排序基于 pipeline 特征 | 占据 order 与 placement；提供可修改源码 | 本地源码的稳定状态不主动重开搜索；论文未系统评估 drift 后的全计划重选 |
| [Plumber, MLSys 2022](https://doi.org/10.48550/arXiv.2111.04131) | 正式系统论文 | 诊断瓶颈并调 parallelism、prefetch、cache | 分析模型驱动调优 | 占据可解释性能模型和多 knob 调优 | 重点是诊断/优化，不是非平稳阶段中的安全切换 |
| [A-Dloader, IEEE CLOUD 2022](https://doi.org/10.1109/CLOUD55607.2022.00068) | 正式系统论文 | 并发 DDL 作业间动态分配 CPU/I/O 和 loader worker | 作业到达/结束时运行时重分配 worker | 直接占据 contention-aware worker 调节 | 动作空间主要是 worker allocation，未覆盖整个 operator plan |
| [Dataloader Parameter Tuner, 2022](https://doi.org/10.48550/arXiv.2210.05244) | 预印本 | 网格搜索 worker 数和 prefetch factor | 参数搜索 | 占据基础调参基线 | 未针对环境漂移、安全性或切换代价 |
| [InTune, RecSys 2023](https://doi.org/10.48550/arXiv.2308.08500) | 正式系统论文 | 用 RL 分配 trainer CPU 资源，提高在线 ingestion | RL 驱动的在线资源配置 | 否定“用 RL 做在线适配”本身的新颖性 | 特定于 DLRM CPU 资源；未见全计划安全切换保证 |
| [cedar, PVLDB 2025](https://doi.org/10.14778/3705829.3705861) | 正式系统论文 | 统一组合 offload、cache、prefetch、fusion、reorder | 静态 optimizer 选复杂计划；Auto-Tuner 动态 right-size parallelism/variant | 最强的全局优化基线，并覆盖 runtime scaling | 论文评估把静态 plan optimization 与运行时 right-sizing 分开；未系统评估 drift 后重搜 whole plan 的失败探测成本 |
| [DART, FGCS 2026](https://doi.org/10.1016/j.future.2025.108303) | 正式系统论文 | 状态感知的数据并行训练在线协同调度 | CKF 状态估计；epoch 边界联合调 shard、batch、loader worker、LR；限速更新 | 最危险的相近工作；占据 noisy-state-aware 在线控制 | 仍需全文确认是否有显式 probe regret、rollback budget 和 whole input-plan 动作 |
| [MegaScale-Data, EuroSys 2026](https://doi.org/10.1145/3767295.3803568) | 正式系统论文 | 多源 LFM 数据编排、source autoscaling、弹性 resharding 与容错 | 随混合比例动态扩缩 Source Loader；阈值和连续区间触发 | 占据 evolving-cost autoscaling、live reconfiguration 和 rescaling-cost 分析 | 动作集中在 source partition/scale 和多源编排；未来工作才计划 strategy optimizer；未见不确定性约束的 whole-plan safe exploration |
| [MinatoLoader, EuroSys 2026](https://doi.org/10.48550/arXiv.2509.10712) | 已接收论文/预印本 | 针对 per-sample preprocessing variability，后台准备并优先组成快样本 batch | 持续后台处理、fast-sample-first batching | 占据 variability-aware batching | 优化 batch construction，不是计划切换控制器 |
| [Seneca, FAST 2026](https://www.usenix.org/conference/fast26/presentation/desai) | 正式系统论文 | 并发多媒体训练中的多形态 cache partition 与 opportunistic sampling | 多作业共享缓存与采样优化 | 占据多租户 cache 方向 | 未覆盖 whole-plan 在线重配置，但限制了以 cache sharing 为主的新题空间 |

## 对候选题目的直接含义

1. “动态 worker scaling”是已占据问题，不能作为论文标题或第一贡献。
2. “统一 cache、placement、reorder、offload”已被 cedar 覆盖；新工作必须解释为什么运行时 drift 需要重新打开静态计划。
3. “考虑 reconfiguration cost”也不能单独成立，因为 MegaScale-Data 已分析 rescaling cost；要研究的是错误 probe 的累计损失、置信度和回滚预算。
4. DART 是立项前必须全文逐节对比的最近工作。若 DART 已提供安全边界或与整个 input plan 等价的动作空间，本候选题目应终止或进一步缩成经验测量研究。

## 本地实验作为证据

| 实验 | 结果 | 能说明什么 | 不能说明什么 |
|---|---|---|---|
| 离线 6/8-worker sweep | contention 下 6 worker 曾比 8 worker 快约 18.7%；估算切换 break-even 约 2,071 batch | 最优并行度可能随 contention 漂移；切换成本必须计入 | 离线 profile 能否转移到连续训练 |
| 连续 fixed vs change-aware | fixed-8 计费总时 92.49 s；朴素 change-aware 124.12 s，慢 34.2%；重配置 38.46 s | 破坏式 probe 和重建可吞掉潜在收益；负结果具有研究价值 | 安全控制器一定能解决，或该失败在 Linux/真实数据上普遍存在 |
