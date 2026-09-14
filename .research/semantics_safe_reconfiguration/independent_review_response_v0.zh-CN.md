# AutoContract 独立拟真评审回复与整改决定 v0

日期：2026-07-29
评审材料：`pasted-text.txt` 中的《AutoContract 独立学术评审报告》
状态：项目内部 author response；不等同于正式 rebuttal

## 1. 总体决定

接受评审的核心结论：**当前材料可以支撑 research prototype / workshop work-in-progress，但不足以支撑正规的 systems/MLSys full paper。** 主要原因不是机制完全错误，而是中心假设依赖的独立 final-blind corpus、真实端到端 workload 和统一统计报告尚未完成。

项目继续保持已经冻结的主线：EffectV7 + rewrite-specific contract obligations + fail-closed optimizer boundary。H7L–H7M 不再扩展，不用分布式协议工作量掩盖外部有效性缺口。

## 2. 逐项处理结论

| 评审意见 | 处理 | 核对结果与决定 |
|---|---|---|
| final blind benchmark 缺失 | **接受，P0** | 真实 50–80 unit corpus、独立 oracle 和一次性 prediction 尚不存在；这是 full-paper 的硬阻塞。 |
| 缺真实训练端到端收益 | **接受，P0** | H8A 是 proof amortization，H8C 是 CPU micro-calibration，H5b 是 retrospective single workload；均不能替代真实 pipeline。 |
| adapter/registry 人工成本未量化 | **部分已有，仍接受 P1** | H7A 已报告 10 rules/10 units 和 93.8% descriptive cell reduction，Kornia manifest 有 8 条 adapter rules；但没有真实 onboarding 人时、修改轮次和跨框架迁移成本，70% 人工减少仍是 hypothesis。 |
| 无 seed 声明 | **事实修正** | H8C runner 固定 `BASE_SEED=20260729`，并设置 Python/NumPy/Torch seed；protocol 和报告没有把它提升为显式 artifact 字段，final v1 必须补齐。 |
| 无原始测量 | **部分修正，接受 P1** | 仓库存在 H8C measurements/decisions/summary CSV，但 measurements 只保存三次重复后的 median，没有逐次 paired timing、warm-up 和环境快照；final v1 必须写 append-only per-repeat JSONL。 |
| H8C abort 原因未记录 | **部分修正，接受补充** | postmortem 已记录“编排器短 timeout、无正式输出、代码/协议/阈值未修改”；但当时 timeout 精确值和两次环境 diff 未作为 artifact 保存。不能事后猜测，final v1 必须机器记录 launch ledger。 |
| 缺顶层/submodule commit | **评审包范围导致的误判** | 当前仓库的 `.gitmodules` 和 `THIRD_PARTY.md` 列出 6 个 exact submodule commits；单文件 review packet 未嵌入它们。下一版评审包补入。顶层工作树仍需在正式 freeze 时记录 commit。 |
| classified coverage 未报告 | **接受，P1** | H7H 等局部实验有 coverage，final consolidated benchmark 尚无统一 success/unknown/unsupported/crash/timeout denominator。 |
| gradient oracle 缺失 | **接受，需先定 scope** | 当前主 cache-prefix workload 通常位于 autograd 边界之外；不能把 gradient 写成所有 unit 的已验证性质。对 differentiable Kornia replay/rewrite unit 必须加入 forward + input-gradient oracle；其他 unit 标为 preregistered `not_applicable` 并说明原因。 |
| 所有分类指标使用 95% CI / t-test | **修正方法后接受** | recall/false-accept/coverage 使用 exact binomial 或 Wilson interval；零 false accept 同时报告单侧上界。paired latency/benefit 使用 workload-level bootstrap 或预注册的非参数 paired test，不对二项指标使用 t-test。 |
| 独立 oracle 必须来自不同研究组 | **不作为绝对门槛** | 必须独立于 analyzer/threshold 开发并在 prediction 前隔离；同组但未参与开发、存在访问控制和双人复核可以作为最低实现。不同研究组是更强配置，应优先争取并披露。 |
| 至少 CV/audio/NLP 三领域 GPU | **作为 full-paper 强目标，不改写已注册最低线** | final-v1 最低线仍是 ≥3 frameworks、≥2 domains、50–80 units。端到端部分至少做 3 个真实 workloads；第三领域和 GPU 是强外部有效性目标，资源不足时不能假装是原协议硬门槛。 |
| 继续 H7M 批处理与 CI | **降级 P2/不进入当前主线** | H7M 是扩展机制。除非论文明确纳入它，否则不再消耗主线预算。 |

## 3. 认可的主张边界

当前可以写：

1. AutoContract 已实现 context/configuration/phase/reachability-sensitive effect IR 的原型；
2. 已实现从 effect facts 到 cache/replay/adjacent rewrite obligations 的 optimizer gate；
3. H8A–H8C 提供 integration、retrospective pilot 和 registered internal calibration 证据；
4. dynamic-only 在内部对抗 workload 上会接受输出相同但具有未来 RNG/external-state/diversity 风险的候选；
5. final-blind protocol 已具备 schema、commitment、tamper check 和 sealing guardrails。

当前不能写：

- 跨框架泛化准确率；
- 100% 安全或任意 Python soundness；
- 已减少 70% 人工标注；
- 已达到 ≥90% human-oracle benefit 的外部结论；
- H8C 是 final evaluation；
- gradient 已在所有优化类型中验证。

## 4. 版本化整改工作包

### WP0：主张与冻结完整性（已完成）

- 保持 EffectV7/H8C 冻结 hash 不变；
- H8C 永久标为 internal calibration；
- 不用后续分析回写历史 headline。

### WP1：final runner 的统计与复现输出（项目内部可完成）

正式 runner 在接触 final unit 前必须支持：

- append-only `run_events.jsonl`：unit、repeat、开始/结束时间、raw/candidate latency、退出状态；
- `environment.json`：OS、CPU/GPU、Python、依赖、线程/worker、seed、git/submodule hashes；
- outcome taxonomy：classified、unknown、unsupported、crash、timeout；
- exact/Wilson interval、zero-FA 单侧上界、paired bootstrap CI；
- prediction artifact hash 和 immutable launch ledger；
- gradient oracle 的适用性字段与 differentiable-unit 检查。

### WP2：adapter burden（项目内部 + 新框架策展者）

- 自动统计 adapter LOC、rule count、registry entries 和 framework-generic analyzer LOC；
- 对下一未见框架前瞻记录 onboarding 开始/结束时间、查阅文件数、规则修改轮次；
- manual baseline 记录每个 hint 的字段数和标注分钟数；
- 不用历史回忆估算 Kornia 人时。

### WP3：独立 corpus 与 oracle（外部依赖）

- 50–80 real source-bound units；
- ≥3 frameworks、≥2 domains，至少一个开发期未接触框架；
- primary/reviewer 独立于 analyzer 开发；
- private oracle commitment 在 prediction 之前发布；
- prediction 冻结后才解封 oracle。

### WP4：真实端到端 workloads（full-paper 必需）

- 至少 3 个真实 pipeline workloads，覆盖 cache-prefix 与 replay/rewrite；
- 统一 raw/manual/static/dynamic/hybrid/oracle candidate space；
- 报告 input throughput、训练 wall time、overhead 和语义 oracle；
- 在资源允许时加入 GPU、多 worker 和第三领域；资源不允许则缩小投稿目标。

## 5. Go / no-go

- **Workshop/WIP：conditional go。** 只能以 mechanism + pilot calibration + open evaluation protocol 投稿，摘要明确 final blind 尚未完成。
- **Full paper：当前 no-go。** 只有 WP1–WP4 完成且 final gates 未失败，才重新评估投稿。
- 若 final benchmark 出现已知 unsafe false accept，本版本中心假设失败；保留失败结果，不能回填规则后继续使用同一 benchmark ID。

## 6. 评审过程本身的教训

单文件 review packet 有意控制上下文，但省略了代码、`THIRD_PARTY.md`、`.gitmodules` 和部分 CSV，导致评审将“packet 中不可见”推断成“repository 中不存在”。后续评审必须显式区分：

1. repository evidence absent；
2. review packet omitted；
3. artifact exists but insufficient（例如只有 median、没有 per-repeat log）。

这不削弱评审对核心实验缺口的判断，但会提高事实核对质量。
