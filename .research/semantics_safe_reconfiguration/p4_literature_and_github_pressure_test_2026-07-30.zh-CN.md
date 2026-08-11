# P4 后文献与 GitHub 创新性压力测试

日期：2026-07-30
方法：只读取论文原文、官方项目页、论文声明的仓库与 GitHub 元数据；没有打开潜在 final-blind 新框架的源码。

## 1. 新增最强近邻：HyCache

[HyCache（USENIX ATC 2025）](https://www.usenix.org/conference/atc25/presentation/jha) 已经实现内存+存储的多层部分缓存、多个 stage 的联合选择、working-memory 估计和 profile-guided ILP。它明确区分 offline deterministic/idempotent steps 与 online stochastic steps，并只缓存前者；其论文也说明缓存随机增强会消除随机性、损害增强质量。

关键边界在接口而非成本模型：用户可以把 step 标为 `online-only`；`cache_steps` 未提供时，系统假定所有步骤都是 offline、都可纳入缓存。HyCache 的自动分析主要根据隔离执行后的 tensor size 过滤候选，不是从 Python/framework execution semantics 推断 RNG、hidden state、external I/O、lineage 或 phase-dependent reachability。

因此 HyCache 压缩了 AutoContract 的主张空间，但也给出一个非常具体的集成目标：AutoContract 不应重复 HyCache 的 ILP，而应从 EffectV7/source binding 生成并验证 `online-only`、安全 cache boundary 与 invalidation key。最有辨识度的实验是比较：用户标注、output-only probe、stateful dynamic、EffectV7 在判断 HyCache cacheable steps 上的 unsafe false accepts、coverage 与接入负担。

## 2. cedar 与 Pecan 再核对

[cedar（PVLDB 2024/2025 卷）](https://www.vldb.org/pvldb/vol18/p488-zhao.pdf) 已经联合枚举 reorder、cache、fusion、offload，并提供 `depends_on`、`fix` 和 random-Pipe 标注。它保证遵守这些 constraints；如果用户没有给 dependency/randomness，就分别关闭 reorder/cache。论文明确把自动推断 dependency/randomness 留为 future work。因此 AutoContract 可作为 cedar 的 constraint compiler/gate，但不能声称 optimizer、动态 Pipe mutation 或 exactly-once 是原创。

[Pecan（USENIX ATC 2024）](https://www.usenix.org/conference/atc24/presentation/graur) 自动重排 inflationary/deflationary transformations，但对不能自动检测的严格顺序约束使用 `keep_position` barrier，并用最终模型精度支持 relaxed commutativity。它与 AutoContract 的差别不是“考虑/不考虑正确性”，而是经验训练质量容忍与候选级显式 effect obligation 两种 correctness 定义。最终论文需直接承认并比较这两种定义。

## 3. 相邻的属性推断、lineage 与 reuse

[LAMBDA（ICSE 2024）](https://conf.researchr.org/details/icse-2024/icse-2024-research-track/147/A-Framework-For-Inferring-Properties-of-User-Defined-Functions) 用 abstract interpretation 推断 DBMS UDF 的四类属性，包括可用于缓存的 purity，并在 20 个 production UDF 中发现 5 个错误人工标注。它强烈占据“自动属性推断减少错误 hint”这一一般贡献。AutoContract 只能主张 ML-specific operation context、augmentation diversity、多个 RNG/target/lineage 与 framework replay capability 的增量。

[SystemDS](https://www.vldb.org/cidrdb/papers/2020/p22-boehm-cidr20.pdf) 用包括系统生成 seed 在内的细粒度 lineage DAG 哈希支持中间结果复用；[HELIX](https://arxiv.org/abs/1812.05762) 用 declarative ML workflow、program analysis 和 materialization/reuse 优化迭代开发。它们占据 lineage-keyed reuse 和跨迭代 materialization；AutoContract 的 SourceIndex 不能泛称“首个版本化复用”，只能定位为动态 Python framework callable、exact operation context 与 fail-closed deployment invalidation 的窄机制。

[mlinspect](https://vldb.org/cidrdb/2021/lightweight-inspection-of-data-preprocessing-in-native-machine-learning-pipelines.html) 已能从常用 Python ML preprocessing abstractions 抽取 DAG、做 lineage annotation propagation 与合规检查。它提醒我们：DAG extraction/lineage 本身也不是创新；评估必须证明与 cache/replay/reorder admission 直接相关的 effect dimensions 和版本失效。

## 4. GitHub 核查

GitHub stars 只表示项目可见度，不能证明论文缺口，但能帮助选择需要认真对比的可复现实物。2026-07-30 通过 GitHub REST 元数据读取：

| 仓库 | stars | 与本研究关系 |
|---|---:|---|
| [ray-project/ray](https://github.com/ray-project/ray) | 43,387 | 大规模数据执行/调度底座；不等于自动 ML transform effect contract |
| [mlflow/mlflow](https://github.com/mlflow/mlflow) | 27,271 | 生命周期、实验与 artifact 管理；不是 input rewrite safety gate |
| [treeverse/dvc](https://github.com/treeverse/dvc) | 15,781 | 数据/流水线版本与依赖；强 adjacent invalidation baseline，但不建模 augmentation/replay semantics |
| [NVIDIA/DALI](https://github.com/NVIDIA/DALI) | 5,732 | 高性能 input pipeline；本项目已登记为开发期污染且不支持，不能用于 final novel evidence |
| [meta-pytorch/data](https://github.com/meta-pytorch/data) | 1,259 | PyTorch data primitives；可作为生态背景，不代表本题已解决 |
| [apache/systemds](https://github.com/apache/systemds) | 1,097 | declarative ML、lineage 与 reuse；重要 adjacent baseline |
| [tensorflow/data-validation](https://github.com/tensorflow/data-validation) | 783 | 数据 schema/statistics validation；不是 transform execution effects |
| [stefan-grafberger/mlinspect](https://github.com/stefan-grafberger/mlinspect) | 70 | Python ML preprocessing DAG/lineage inspection；概念近邻 |
| [eth-easl/cachew](https://github.com/eth-easl/cachew) | 41 | Cachew/Pecan 实现；直接成本/placement/reorder baseline |
| [stanford-mast/cedar](https://github.com/stanford-mast/cedar) | 19 | 最直接 optimizer integration target，stars 低但学术相关性最高 |
| [eth-easl/pecan-experiments](https://github.com/eth-easl/pecan-experiments) | 2 | Pecan artifact evaluation scripts |

这里最重要的反直觉结论是：不能按 stars 选择 related work。cedar/Cachew/Pecan 的 stars 不高，却比 DVC、Ray、MLflow 更直接决定 AutoContract 是否有论文创新。

## 5. 更新后的原创性 verdict

不存在一篇在本次检索中发现的工作同时完成以下四件事：

1. 从真实 ML input framework/UDF 的 configuration、operation、phase 和 reachable execution path 推断 ML-specific effects；
2. 把语义判断、parameter-replay capability 与实际 executable-source binding 分层；
3. 为 cache/replay/reorder 候选生成 fail-closed、可版本失效的证据；
4. 在独立新框架上以 zero unsafe false accepts、coverage、人工负担和 end-to-end benefit 共同评估。

这是基于当前来源的“组合缺口”判断，不是原创性证明。前三项在相邻领域都有强先例，真正能否成为论文取决于第 4 项。若 final-blind 失败或 adapter burden 过高，项目只能定位为机制/经验研究，不能靠组合已有概念获得强原创性。

## 6. 立即影响研究设计的三项改变

1. related work 新增 HyCache，并把“offline/online annotation 自动化”列为具体问题，不再笼统写 safe caching。
2. integration experiment 以 constraint compiler 为主：EffectV7 输出映射到 cedar random/dependency constraints、HyCache online-only/cache boundary、Cachew autocache boundary；不实现新的 cost optimizer。
3. source/version claim 必须与 DVC/SystemDS/HELIX 区分，强调 callable-level exact-operation binding 和 fail-closed runtime invalidation，同时报告 native/TOCTOU/跨 ABI 的 Unknown 边界。
