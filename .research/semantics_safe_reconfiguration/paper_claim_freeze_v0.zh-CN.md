# AutoContract 论文主张冻结 v0

日期：2026-07-29
状态：工作冻结；在 final blind benchmark 解封前只允许修改实现 bug，不允许根据测试结果移动指标或主张边界。

## 1. 当前决策

论文主线冻结为：**AutoContract: Contract-Carrying Rewrites for ML Input Pipelines**。

一句话问题：现有 ML input-pipeline optimizer 需要人工语义提示，或者只用保守 barrier；AutoContract 研究能否从算子源码、配置和少量 framework adapter 中恢复足够精确、可审计的 effect contract，使 optimizer 自动发现有收益的安全 rewrite，同时对未解析行为 fail closed。

本轮明确停止继续扩展 H7N 的 trainer-level exactly-once。H7L/H7M 保留为可选的分布式 provenance/transaction extension；论文核心只要求 EffectV7、contract validator、optimizer integration 与 H7I–H7K 的原子执行边界闭环。

## 2. 可证伪的中心假设

在“源码可见、框架版本固定、配置与执行 phase 已知、算子位于支持的 Python/adapter 边界内”的前提下，configuration/phase/reachability-aware effect contract 比 static-only、dynamic-only 或人工 barrier 更能恢复安全 rewrite 机会；将这些 contract 放在 optimizer 候选验证边界后，可以接近 human oracle 的性能收益，且不接受已知不安全 rewrite。

中心假设如果出现以下任一情况就失败：

- final blind benchmark 出现任何已知 unsafe false accept；
- safe rewrite recall 低于 80%；
- optimizer 获得的收益低于 human oracle 可得收益的 90%，且缺口来自 contract 过度保守而非成本模型；
- accepted plan 在输出、RNG、梯度或 lineage oracle 上出现语义分歧。

## 3. 只保留三个贡献

### C1. Context-sensitive effect IR

EffectV7 以 `(public symbol, configuration, phase, reachable path)` 为判定键，显式表达 construction/execution effect、RNG 来源和状态角色、record scope、cardinality、target coupling、callable/child provenance 与 named-mode obligation。未知分支取保守并集，未解析 effect 产生带理由的 `Unknown` 并拒绝。

### C2. Contract-carrying rewrite and execution

把 effect contract 翻译成 cache、parameter replay 和 adjacent rewrite 的 proof obligations；optimizer 只负责提出候选与估计成本，AutoContract validator 负责 admit/reject。H7I–H7K 的 registered executor 将 source/config/parameter lineage、不可变快照、target lease、apply 与输出释放放在同一原子边界，防止 TOCTOU。

### C3. Versioned cross-framework evaluation

构建同时测安全性、机会恢复、理由可审计性、人工提示量和端到端收益的 benchmark。历史 H6–H7H 只作为版本演进证据；论文 headline 必须来自一个独立、预注册、单一冻结 EffectV7.x 的 final blind benchmark。

## 4. 支持边界与威胁模型

### 支持范围

- 源码可见并可绑定到明确 commit/release 的 Python operator；
- 已注册的 framework adapter 和明确的 active configuration/phase；
- 单样本或显式声明 subject set 的 record transformation；
- 当前主实验中的 cache placement、parameter replay 和相邻候选 rewrite；
- H7I–H7K 中已注册算子的 atomic apply。

### 非主张

- 不声称能分析任意 Python、C++、CUDA 或远程 service 的隐藏行为；
- 不声称所有被 admit 的算子彼此可交换；admit 只表示 effect 足够完整，具体 rewrite 仍须检查两侧 contract；
- 不声称跨 worker 数量、进程生命周期、数据集版本或未注册 framework mode 保持语义；
- 不把 dynamic testing 当形式证明；它只是补充证据和 baseline；
- 不声称 H7L/H7M 已实现 trainer/model-optimizer exactly-once；
- 不把 H6–H7H 的跨版本结果合成一个总体准确率。

## 5. Research questions 与冻结指标

| RQ | 问题 | 主指标与工作 gate |
|---|---|---|
| RQ1 Contract quality | 单一冻结 EffectV7.x 能否在未见 operator/context 上生成安全且足够完整的 contract？ | known-unsafe FA = 0；safe recall ≥80%；coarse reason accuracy ≥90%；classified coverage ≥90% |
| RQ2 Rewrite usefulness | contract 能否替代大量人工 hint，并恢复 human oracle 认可的安全候选？ | safe rewrite recall ≥80%；相对逐算子人工标注减少 ≥70%；所有 accepted rewrites 语义 oracle 通过 |
| RQ3 Optimizer value | 接到 cedar-compatible candidate boundary 后，是否真正改善计划而非只做分类？ | ≥90% human-oracle benefit；报告 compile/validation overhead、吞吐、p50/p95；零语义违规 |
| RQ4 Mechanism attribution | 哪些信息真正必要？ | static-only、dynamic-only、registry-only、hybrid、manual hints、fail-closed、human oracle 在同一 corpus 上对比 |

“human-oracle benefit”定义为：在相同候选空间和成本测量预算下，`(AutoContract plan - raw plan) / (human-oracle plan - raw plan)`；若分母不为正，该 workload 只报告决策一致性和 overhead，不进入收益覆盖均值。

## 6. 证据分层

| 层级 | 能支持的说法 | 当前材料 |
|---|---|---|
| Tier A：final preregistered blind | 论文主准确率与跨框架主张 | **尚未完成** |
| Tier B：one-shot/version holdout | 特定版本、特定框架、特定上下文的局部迁移证据 | H6、H7B–H7H |
| Tier C：calibration/posthoc | 机制发现、错误归因、下一版本设计 | EffectV2–V7 calibration 与 postmortem |
| Tier D：runtime mechanism | 在已注册算子上的 TOCTOU、lineage、atomicity 与开销 | H7I–H7M |

Tier B–D 不能替代 Tier A。尤其 H7H 的 9/9 只说明 phase-aware 机制值得继续，不足以写“跨框架准确率 100%”。

## 7. Final benchmark 最小设计

1. 冻结 `EffectV7.x + adapter API + validator + metric code` 的 hash。
2. 由独立标注者或学长封存 operator/context manifest 与 oracle；unsafe 全量双审，safe 随机子集复审。
3. 使用统一 decision unit：`(framework, release, public symbol, configuration, phase, rewrite kind)`。
4. oracle 同时标注 expected decision、coarse reason、rewrite obligations、subject/cardinality、输出/RNG/梯度/lineage 检查方法。
5. 预测只运行一次；失败保留，修复进入下一版本，不能回填本 benchmark。
6. 所有 baseline 使用同一 manifest、候选空间、成本预算和语义 oracle。

## 8. 当前停止条件与下一工作包

现在不再通过增加新 Effect 版本来寻找新框架漏洞，除非 final benchmark 暴露主张范围内的致命 soundness 问题。接下来的顺序冻结为：

1. 完成统一 evidence/benchmark schema 和审计器；
2. 实现 optimizer candidate 接口以及 manual/static/dynamic/hybrid baseline；
3. 与学长确认 final corpus 和独立 oracle 流程；
4. 一次性运行 final blind benchmark；
5. 再做端到端收益、ablation 和论文图表。

若在完成第 2 步前继续扩展 H7N、更多 lease 协议或 trainer checkpoint，视为偏离本论文主线。
