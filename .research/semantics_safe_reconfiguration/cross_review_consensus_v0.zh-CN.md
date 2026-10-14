# AutoContract 双评审共识与主线修订 v0

日期：2026-07-30
材料：第一份独立 AI 拟真评审、Gemini 拟真评审、当前仓库证据包
用途：内部研究决策，不等同于真实同行评审或外部复现

## 1. 结论

两份评审对当前成熟度的判断高度一致：**AutoContract 已达到可组织为 workshop/short-paper research prototype 的程度，但还不能支撑 systems/MLSys full paper。** 这不是因为主机制已经被证伪，而是因为三条 headline claim 仍缺最终证据：独立 final-blind、真实端到端 workload、跨框架 adapter/unknown 成本。

两位评审的共同意见只作为高优先级排查信号，不作为“独立学术验证”。它们读取了同一份作者组织的材料，也可能共享相似的模型先验。最终结论仍必须由预注册实验、不可回填的 blind prediction 和可审计原始数据决定。

## 2. 共识与分歧

| 议题 | 第一份评审 | Gemini | 项目决定 |
|---|---|---|---|
| Full paper readiness | Reject / 证据不足 | Reject / Weak Reject | **当前 no-go** |
| Workshop readiness | Borderline / Weak Accept | Accept / Weak Accept | **conditional go，不把模型打分当录用概率** |
| final-blind benchmark | P0 | P0 | 保持最高优先级，但先冻结公平基线与 runner |
| 真实端到端 workload | P0 | P0，强调 GPU/多 worker | full paper 必需；GPU/第三领域是强目标，不改写已注册最低线 |
| adapter burden | P1 | Major | 纳入 final-v1 前置测量：LOC、规则、工时、修改轮次、no-adapter 退化 |
| H7L–H7M | 降级 | 从主线剥离 | 不再扩展；只作为可选附录背景 |
| dynamic baseline | 未重点质疑 | 认为 output-only 是 strawman | **接受并修订**：保留旧消融，新增公平的 stateful dynamic baseline |
| cost horizon | 未重点质疑 | 认为手工输入可能被调参 | **接受并修订**：由 workload manifest 推导，另报敏感性区间 |
| MRO/动态分派 | 作为适用边界 | Major limitation | 明确 adapter-supported boundary；对 unresolved 路径报 `unknown`，不声称任意 Python soundness |
| 直接对比 Cedar/Cachew | 要求定位清楚 | 倾向真实运行对比 | 优先同候选空间的 manual-hint baseline；只有接口/环境兼容时才做直接系统复现 |

## 3. Gemini 新增意见的裁决

### 3.1 Dynamic-only：接受，但修正表述

H3/H8C 的 `dynamic_only` 只观察有限、同上下文输出一致性。它能够作为 **output-only differential testing ablation**，用来展示有限输出检查看不到未来 RNG、环境和失效语义；但它不能代表现代动态分析的最佳能力。

final-v1 同时报告：

1. `dynamic_output_only`：复现历史消融，名称与能力边界写清；
2. `dynamic_stateful`：使用预注册、与标签无关的固定探针预算，检查重复调用、跨 epoch、RNG 消耗、对象状态变化、声明环境变化和输出多样性；
3. `hybrid`：静态/registry/dynamic 证据冲突时 fail closed。

不能依据某个 final unit 的私有 oracle 临时选择探针，否则会把动态基线变成标签泄漏或 oracle surrogate。两种 dynamic policy 接收相同候选、相同公开上下文和相同预算。

### 3.2 Cost horizon：接受，但不否定历史结果

H8A 的 H=1/H=10 是 break-even 敏感性 profile，H8B 的 4 epochs 来自实际 workload；它们不是无效结果，但尚未证明可部署 optimizer 会自动获得正确 horizon。

final-v1 的主分析中，horizon 必须从预测前冻结的 workload manifest 推导：dataset cardinality、epochs/full scans、batch size、`drop_last`、worker/replica 数、cache validity scope、计划复用次数。手工 H 只能进入预注册的敏感性分析，不能用于选择 headline 配置。若 horizon 本身不确定，则报告保守下界、计划值和上界三档及 decision stability。

### 3.3 MRO、dynamic dispatch 与 adapter：接受为适用边界

AutoContract 不证明任意动态 Python。复杂 C3 MRO、descriptor、运行时 monkey patch、自定义 C++/CUDA extension 无法解析时，应进入 `unknown/unsupported`，而不是被静默当作 safe。论文必须报告：

- `classified / unknown / unsupported / crash / timeout` 的统一分母；
- 有 adapter 与无 adapter 的 recall、false accept 和拒绝原因；
- 新框架 adapter 的 LOC、规则数、工程工时和修改轮次。

### 3.4 GPU、三个领域、Cedar/Cachew：部分接受

真实多 worker/GPU workload 会显著增强 full-paper 外部有效性，应作为资源允许时的强目标；但不能把评审举出的 ResNet、ViT、Wav2Vec 或三个具体框架事后写成原协议的硬门槛。直接运行 Cedar/Cachew 只有在候选空间、依赖和执行边界可公平对齐时才有解释力。最低公平比较是同一候选、同一 profiler 下的 `manual_full/registry_only`，并清楚说明它是 manual-hint proxy 而非 Cedar 本体。

### 3.5 不采纳的建议

- 不删除或“清理”失败/中止运行痕迹；应保存并标注 launch ledger，避免不可审计的选择性报告。
- 不把两个 AI 的 workshop 分数平均成录用概率。
- 不承诺 final-blind 一定达到 0 unsafe false accept 或 90% oracle benefit；这些是待检验门槛，不是既成结论。

## 4. 修订后的研究主线

### P0-A：先冻结评估工具，而不是立刻碰 final corpus

- append-only per-repeat log、environment snapshot、launch ledger；
- exact/Wilson 分类区间、zero-FA 单侧上界、workload-level paired bootstrap；
- 统一 outcome taxonomy 与 gradient applicability；
- `dynamic_output_only` / `dynamic_stateful` 双动态基线；
- manifest-derived horizon 与不确定性报告。

### P0-B：独立 final-blind

- 50–80 real source-bound units；
- 至少 3 个 frameworks、2 个 domains；
- corpus/oracle 人员不参与 analyzer/threshold 开发；
- prediction 冻结后才解封 oracle；
- 失败后保留结果，不在同一 benchmark ID 上修规则重跑。

### P0-C：真实端到端 workload

- 至少 3 个真实 pipeline workload，覆盖 cache-prefix 与 replay/rewrite；
- raw/manual/static/dynamic/hybrid/oracle 使用同一候选空间；
- 报告吞吐、训练 wall time、p95/input wait、optimizer overhead 和语义 oracle；
- 优先加入多 worker；GPU 与第三数据域作为 full-paper 强目标。

### P1：adapter 与退化成本

- 自动统计 adapter LOC、rule count、registry entries；
- 对未见框架前瞻记录 onboarding 工时；
- no-adapter/general-Python 退化实验；
- manual-full 每个 hint 的字段数和标注分钟数。

### P2：论文收口

- 工作题目收窄为 **Adapter-Assisted Effect Contracts for Guarding ML Input Pipeline Rewrites in Cost Optimizers**；
- C1 聚焦 mode/phase/path-sensitive EffectV7；
- C2 聚焦 contract-carrying rewrite gate；
- C3 只写评估协议和待验证假设，不写已经达到 90%；
- H7L–H7M 移出核心贡献。

## 5. 当前最近一步

下一项内部实现不应直接运行 final-blind。先完成 `dynamic_stateful` 和 manifest-derived horizon 的冻结规范与 runner telemetry；否则 final-blind 即使跑完，也会留下“基线过弱”和“成本参数可调”两个无法通过补写文字消除的审稿缺口。
