# 相近工作矩阵：Semantics-Aware and Reconfiguration-Safe ML Input Pipelines

更新日期：2026-07-28

| 工作 | 类型 | 已完成的能力 | 与候选题目的重叠 | 本轮确认的边界 |
|---|---|---|---|---|
| [tf.data, PVLDB 2021](https://doi.org/10.14778/3476311.3476374) | ML 输入框架 | parallelism、cache、静态优化、非确定执行 | 提供优化与执行底座 | 不自动理解任意 UDF 的训练语义，也不做 whole-plan 事务切换 |
| [Plumber, MLSys 2022](https://arxiv.org/abs/2111.04131) | ML 输入调优器 | 性能诊断，自动调 parallelism、prefetch、cache | 占据自动性能调优 | 重点不是 transformation 语义推断或在线计划切换 |
| [Cachew, USENIX ATC 2022](https://www.usenix.org/conference/atc22/presentation/graur) | ML 输入处理服务 | 作业内/跨作业 autocaching、pipeline fingerprint、cache hit、worker autoscaling，按 batch time 和存储成本选执行模式 | 已占据性能/成本驱动的自动缓存与跨作业复用 | 安全 cache 点由用户插入 `autocache`，论文要求放在随机变换之前；评估明确假设用户已选择可接受位置，不自动推断 transformation effect 或证明 trace/distribution contract |
| [HyCache, USENIX ATC 2025](https://www.usenix.org/conference/atc25/presentation/jha) | 混合 input cache runtime | memory+storage 部分缓存、多 stage 联合选择、working-memory 估计、profile-guided ILP | 已占据自动 cache stage/tier/数量优化 | 用户标注 `online-only`；若 `cache_steps` 未给则假定所有步骤 offline。自动 step filter 依据运行时 tensor size，不推断 RNG/hidden state/external I/O/phase；可作为 AutoContract constraint compiler 的直接后端 |
| [Pecan, ATC 2024](https://www.usenix.org/conference/atc24/presentation/graur) | ML 输入系统 | transformation reorder、local/remote placement | 已做语义约束下的重排 | 主动放松严格语义等价；严格依赖由用户 `keep_position` 标记 |
| [cedar, PVLDB 2025](https://doi.org/10.14778/3705829.3705861) | ML 输入优化器 | reorder、cache、offload、fusion、prefetch、样本 UUID 去重、精确 checkpoint、runtime Pipe mutation/right-sizing | 最接近语义感知优化，也已占据一部分安全切换 | dependency/randomness 由用户提供；自动推断明确留作 future work；活跃 controller 主要调 parallelism/variant，不在 drift 时重跑 whole logical-plan optimizer |
| [Opening the Black Boxes, PVLDB 2012](https://doi.org/10.14778/2350229.2350244) | 数据流优化方法 | 静态分析 UDF 属性，建立安全重排条件 | 直接启发自动依赖分析 | 不处理 ML random augmentation、训练分布或运行时切换 |
| [LAMBDA, ICSE 2024](https://doi.org/10.1145/3597503.3639147) | DBMS UDF 静态分析 | 基于 abstract interpretation 自动推断 4 类 UDF 属性，包括支持缓存的 purity；在 20 个生产 UDF 中发现 5 个错误人工标注 | 强烈占据“自动 effect/property inference 减少人工 hint”的一般贡献 | 面向 DBMS UDF 与传统缓存/优化；未建模 ML augmentation 的多 RNG 来源、operator-keyed replay、trace/distribution/visitation contract 或 cache 命中后的 RNG lineage |
| [HELIX, VLDB 2019](https://arxiv.org/abs/1812.05762) | 迭代 ML workflow 优化 | declarative DSL、程序分析、跨 iteration 中间结果 reuse/materialization、cost optimization | 占据 ML pipeline 版本迭代中的缓存复用 | 目标是开发迭代和 declarative workflow，不是任意 input framework 的 phase-sensitive effect 推断或 runtime callable invalidation |
| [SystemDS lineage reuse, CIDR 2020](https://www.vldb.org/cidrdb/papers/2020/p22-boehm-cidr20.pdf) | declarative ML compiler/runtime | operation-level lineage DAG（含 system-generated seeds）、hash-keyed full/partial intermediate reuse | 占据 lineage-keyed ML intermediate caching | DSL 内部 lineage 已知；不从第三方 Python transform 恢复 effects，也不提供 framework-specific replay capability receipt |
| [mlinspect, CIDR 2021](https://vldb.org/cidrdb/2021/lightweight-inspection-of-data-preprocessing-in-native-machine-learning-pipelines.html) | Python ML preprocessing 检查 | 从流行库抽取 DAG、annotation propagation、lineage-based inspections | 占据 native Python ML pipeline DAG/lineage inspection | 面向数据质量/公平/合规检查，不对 cache/replay/reorder candidate 生成版本化安全判定 |
| [Lara, PVLDB 2019](https://doi.org/10.14778/3342263.3342633) | ML pipeline IR | 表达 UDF、控制流与领域语义，做 pushdown/fusion | 占据 IR + 语义优化的一般思路 | 面向传统训练/验证 pipeline，不是高吞吐 input loader 的在线重配置 |
| [Reproducible Randomness, ETH 2022](https://doi.org/10.3929/ethz-b-000563990) | 学位论文/相邻工作 | per-element seed、stateless random op、顺序 seed splitting、并行可复现、分布式 record/replay；报告 minimal overhead | 占据低开销可复现 RNG 机制 | 不是 plan optimizer；顺序 split 的 seed 与 operator 位置绑定，未研究 reorder/cache hit 后的 stable operator identity 或自动 effect inference |
| [CheckFreq, FAST 2021](https://www.usenix.org/conference/fast21/presentation/mohan) | 训练 checkpoint 系统 | resumable iterator，保证每 epoch 样本 exactly once | 占据 loader 状态恢复 | 面向失败恢复，不是性能驱动的在线计划切换 |
| [DART, FGCS 2026](https://doi.org/10.1016/j.future.2025.108303) | 在线训练控制器 | 联合调 shard、batch、worker、LR；CKF；限速更新 | 占据 noisy-state-aware 在线调参 | 没有 transformation reorder/cache 的自动语义契约 |
| [MegaScale-Data, EuroSys 2026](https://doi.org/10.1145/3767295.3803568) | 大规模多源 dataloader | 动态 mixture、auto-scaling、live resharding、fault tolerance | 占据 loader 重配置与成本分析 | 聚焦多源/混合并行；自动重写/融合 orchestration strategy 被列为 future work，未推断 transformation 语义效应 |
| [Streaming Batch Model / Ray Data, 2025](https://arxiv.org/abs/2501.12407) | 异构数据执行模型 | partition 级流水执行、弹性资源分配、lineage recovery | 占据低开销弹性与容错 | 不推断 ML transformation 的随机性、依赖或可交换关系 |
| [Seneca, FAST 2026](https://www.usenix.org/system/files/fast26-desai.pdf) | 多作业 ML dataloader | cache 分区、机会式采样、每 epoch exactly-once | 占据放松采样顺序与 cache 联合优化 | 以“看似随机且每 epoch 一次”为人工语义假设，不自动证明 transformation 改写 |
| [BatchWeave, 2026](https://arxiv.org/abs/2605.09994) | LFM 训练数据平面 | Transactional Global Batch、全 rank 原子可见、全局 step 顺序、端到端 exactly-once recovery | 强烈占据事务 batch 与 exactly-once | 关注 batch 发布/恢复，不做 transformation effect inference 或安全重排 |
| [Progressive Optimization, SIGMOD 2004](https://doi.org/10.1145/1007568.1007642) | 数据库方法类比 | 检测估计错误并触发 mid-query reoptimization | 占据运行时重优化触发思想 | 不处理 ML 样本、RNG 与增强语义 |
| [Incremental Query Re-Optimization, SIGMOD 2016](https://doi.org/10.1145/2882903.2915212) | 数据库方法类比 | 增量维护 optimizer state，降低频繁重优化成本 | 占据增量计划搜索 | 不提供 ML-specific safety contract 或 loader state protocol |
| [CANS semantic segments, USITS 2001](https://www.usenix.org/legacy/publications/library/proceedings/usits01/full_papers/fu/fu_html/node13.html) | 流系统方法类比 | 在线 data-path reconfiguration、semantic continuity、exactly-once | 占据事务式流切换的核心思想 | 很早的一般系统机制，没有 ML transformation 与训练分布语义 |

## 直接含义

1. `semantics-aware optimization` 不是空白，不能作为唯一贡献。
2. `reconfiguration-safe` 在一般系统和最新 ML 数据系统中都不是空白；仅实现 exactly-once 或 elastic resharding 不足以构成贡献。
3. `autocaching` 与跨作业 cache reuse 也不是空白；Cachew 已实现性能/成本策略。AutoContract 不应重新发明 cost policy，而应给 Cachew/cedar 提供自动推断的安全候选点、契约、RNG virtualization 与 cache-key/invalidation 条件。
4. “自动推断 UDF 属性”也不是空白；Opening the Black Boxes/Hueske 等已用代码分析支持安全重排，LAMBDA 已用 abstract interpretation 减少错误人工标注。
5. 最有证据支持的窄缺口必须改写为：针对 ML input transformation 推断 cedar/Cachew 要求用户提供的 randomness、hidden/external state 与 safe-cache hints，并为具体 rewrite 生成 trace/distribution/visitation 层级、stable operator RNG 和 cache-key/invalidation 义务。
6. 动态 whole-plan 重优化只能作为第二阶段：它必须改变 reorder/cache/fusion/placement，而非只调 worker；还需保存 sample cursor、sampler state、operator-keyed RNG lineage、in-flight IDs 和 cache namespace。
7. HyCache 使“自动 cache optimization”主张进一步 no-go，但提供了最具体的应用接口：自动产生或审计 `online-only`/cache boundary。该接口应成为 final integration RQ，而非另写 ILP。
8. HELIX/SystemDS/DVC 等说明 lineage、版本和缓存失效不是空白；SourceIndex 的可防守增量只能是第三方动态 Python callable 的 exact-operation measured binding 与 fail-closed runtime invalidation。
9. P5F 进一步说明 effect purity/cache eligibility 不能推出 commutativity。Pecan 的 relaxed commutativity 与 cedar 的人工 `fix/depends_on` 已占据“重排需要顺序约束”这一基本思想；ReorderCapability 的候选增量只能是 source/version/context-bound receipt、fail-closed composition 和自动 proof producer 的实证效果。
10. cache、registered replay 与 reorder 必须使用不同 capability/obligation 和不同评估分母；任何把三者合并成通用 `safe rewrite` 的表述都应视为范围错误。
