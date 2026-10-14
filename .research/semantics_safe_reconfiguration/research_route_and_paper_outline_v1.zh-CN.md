# AutoContract 研究路线与论文大纲 v1

日期：2026-07-30
依据：当前仓库证据、两份独立 AI 拟真评审、Gemini 评审与评审后事实核查
状态：主线重构；不修改 H8A–H8C 历史协议和输出

## 1. 新的中心问题

现有 ML input-pipeline optimizer 可以搜索 cache、placement、reorder 等高收益计划，但通常要求用户先指出哪里可缓存、哪些 transformation 不能移动，或者用经验性的模型精度结果代替逐 rewrite 的语义保证。AutoContract 研究的问题收窄为：

> 在源码可见、版本与运行 phase 已知、并位于 adapter-supported Python 边界内时，能否自动恢复足够精确且可审计的 effect contract，把它作为 cost optimizer 的 rewrite gate，从而减少逐算子人工 safety hint，同时保留大部分安全优化机会？

这一定义明确不覆盖任意 Python、隐藏 C++/CUDA effect、未声明远程状态或 trainer-level exactly-once。

## 2. 论文只保留两个技术贡献

### C1：Adapter-assisted、context-sensitive effect contracts

EffectV7 以 `(symbol, framework version, configuration, phase, reachable path)` 为分析键，表达 RNG、state、external read/write、cardinality、sample identity、target coupling 和 callable/child provenance。无法解析的路径返回带理由的 `Unknown`，不把“没观察到”当成“没有 effect”。

### C2：Contract-carrying rewrite gate

将 effect facts 翻译为 cache-prefix、parameter replay 和 adjacent rewrite 的候选级 proof obligation。成本模型可以提出高收益候选，但不能覆盖 semantic reject；admitted contract、source/configuration digest、profiler 和 workload horizon 一起进入可审计的 plan decision。

版本化 final-blind 协议、统计与 artifact sealing 是保证证据可信的方法，不再单列为原创 C3。端到端吞吐和 human-oracle benefit 是 C1/C2 是否有用的验证结果，也不伪装成独立机制贡献。

## 3. 可证伪假设与研究问题

| RQ | 可证伪问题 | 主指标 | 失败含义 |
|---|---|---|---|
| RQ1 Safety | 未见 unit 上，hybrid contract gate 是否拒绝已知不安全 rewrite？ | unsafe false accepts；单侧上界；语义 oracle | 出现 FA 即当前冻结版本中心安全假设失败 |
| RQ2 Coverage | fail-closed 是否仍能恢复足够多的安全机会？ | safe recall、classified coverage、unknown taxonomy | recall <80% 或 coverage <90% 表示 adapter/analysis 过窄 |
| RQ3 Hint displacement | 自动 contract 相比 manual hints 到底省多少人力？ | adapter LOC/工时、hint 字段/分钟、修改轮次 | 自动化成本不低于逐算子标注则实践贡献弱 |
| RQ4 Optimizer value | 语义 gate 是否把安全性转化为真实性能收益？ | human-oracle benefit、wall time、throughput、p95、overhead | benefit <90% 且由保守拒绝导致，则核心效用假设失败 |
| RQ5 Attribution | 提升来自静态、动态、adapter 还是组合？ | 同 corpus 的 registry/static/output-dynamic/stateful-dynamic/hybrid/manual/oracle ablation | 若公平 dynamic baseline 已等价，则 EffectV7 增量贡献弱 |

`90% benefit`、`80% recall` 和 `0 FA` 是预注册 gate，不是当前项目已经达到的结论。

## 4. 证据链

```text
源码/配置/phase
      ↓
EffectV7 contract ──RQ1/RQ2──> safety + coverage
      ↓
rewrite-specific obligations
      ↓
contract gate ─────RQ3/RQ5──> less manual hint + mechanism attribution
      ↓
measured cost + manifest-derived horizon
      ↓
selected plan ─────RQ4──────> end-to-end benefit without semantic violation
```

任何一层失败都应报告失败位置，不能用下游性能掩盖上游语义错误，也不能用零误报掩盖全部拒绝。

## 5. 分阶段研究路线

### Phase A：评估工具硬化（现在进行）

目标：在接触 final corpus 前消除“弱动态基线”和“手调 horizon”两个方法学漏洞。

- 将历史 `dynamic_only` 明确重命名为 `dynamic_output_only`；
- 实现固定预算、标签无关的 `dynamic_stateful`；
- 从 workload manifest 推导 horizon，并报告 low/planned/high 决策稳定性；
- 增加 append-only repeat log、environment snapshot、launch ledger；
- 统一 classified/unknown/unsupported/crash/timeout taxonomy。

退出条件：synthetic self-test 全部通过；缺字段/冲突/溢出 fail closed；probe plan、schema、runner 和统计 hash 可封存。

### Phase B：现有材料上的公平消融与 adapter accounting

目标：在不接触 final oracle 的前提下验证新 runner 和测量流程。

- H8C 只作为 calibration，新增 `dynamic_stateful` 结果但不改写历史 headline；
- 对现有 Kornia、Albumentations、imgaug、TorchIO 等 adapter 自动统计 LOC/rules/registry entries；
- 做 no-adapter 退化实验并报告 Unknown 分母；
- 建立 prospective onboarding 表，未来新 adapter 从第一次打开文档开始计时。

退出条件：所有 baseline 使用相同候选、预算和 cost profile；adapter accounting 可由文件自动重算。

### Phase C：独立 final-blind

目标：回答 RQ1、RQ2 和一部分 RQ3/RQ5。

- 50–80 个 real source-bound units；
- 至少 3 frameworks、2 domains，至少一个开发期未接触框架；
- analyzer/threshold 开发者与 corpus/oracle 人员隔离；
- prediction artifact 先冻结，之后才解封 oracle；
- 失败结果保留；修复必须进入新 benchmark ID。

退出条件：按预注册 gate 给出 go/no-go，不能因结果不理想移动阈值。

### Phase D：真实端到端 workloads

目标：回答 RQ4，并验证成本决策不是 microbenchmark 假象。

- 至少 3 个真实 pipeline workload，覆盖 cache-prefix 与 replay/rewrite；
- raw/manual/static/dynamic/hybrid/oracle 共用候选空间；
- 优先多 worker，资源允许时加入 GPU 和第三领域；
- 报告 wall time、input wait、throughput、p50/p95、GPU utilization（若适用）与 optimizer overhead；
- 对 accepted plan 执行 output/RNG/diversity/gradient/lineage 中适用的 oracle。

退出条件：语义违规为零且 benefit gate 经置信区间后仍成立；否则收缩 claim 或 no-go。

### Phase E：论文与外部复核

- 冻结图表与 evidence table；
- 用 reviewer-facing claim ledger 将每句话绑定到 artifact；
- 再进行一次不知道作者实验意图的拟真评审；
- workshop 与 full-paper 两个版本分别裁剪，不混用成熟度主张。

## 6. 资源与优先级

| 优先级 | 工作 | 可否内部完成 | 是否阻塞 final-blind |
|---|---|---:|---:|
| P0 | stateful dynamic baseline、horizon derivation、runner telemetry | 是 | 是 |
| P0 | final corpus/oracle independence | 需学长/独立人员 | 是 |
| P0 | 真实 end-to-end workload | 需要算力，部分可先 CPU/多 worker | 阻塞 full paper，不阻塞 contract blind |
| P1 | adapter/no-adapter accounting | 是，prospective 工时需新参与者 | 是 |
| P1 | 公平 manual-hint proxy；兼容时复现 Cedar/Cachew/Pecan | 部分 | 不作为最小硬门槛 |
| P2 | H7L–H7M 分布式扩展 | 是 | 否，停止扩展 |

## 7. Go / no-go 决策树

1. Phase A 自测失败：修 runner，不接触 final corpus。
2. Phase B 中 stateful dynamic 已达到 hybrid 的安全性、coverage 和人工成本：AutoContract 新颖性风险升高，先重新定位，不急于 blind。
3. final-blind 出现 unsafe FA：当前版本 no-go，完整报告失败，另起版本修复。
4. FA=0 但 recall/coverage 低：转为“high-confidence narrow boundary” short paper，或补 adapter 后用新 benchmark ID。
5. contract 指标通过但 end-to-end benefit 低：保留 program-analysis/workshop 方向，不投 full systems paper。
6. 两层均通过：进入 full-paper 写作和真实外部复核。

## 8. 论文大纲

### 1. Introduction

- cost optimizer 会提出高收益 rewrite，但 ML preprocessing 的 RNG、phase、state 和 diversity 使“快”不等于“安全”；
- Cachew/Pecan/cedar 等系统证明优化机会很大，但 safety boundary 仍依赖用户位置/hint、保守约束或训练质量经验验证；
- AutoContract 的核心是 adapter-supported semantic gate，不是新的 cost optimizer；
- 列出 C1、C2 和一套预注册验证。

### 2. Motivation and Failure Cases

- same-context output equality 看不到未来 invalidation；
- full-cache 冻结 augmentation diversity；
- mode/phase 改变 reachable RNG；
- 高 optimizer score 不能覆盖 semantic reject。

### 3. Problem Formulation

- decision unit、rewrite kind、context 与 threat model；
- semantic safety、opportunity recall、human-oracle benefit 定义；
- adapter-supported scope 与非主张。

### 4. EffectV7 Contracts

- IR、reachable slice、configuration/phase/mode；
- RNG/state/external/cardinality/lineage；
- adapter API、Unknown 与 fail-closed；
- MRO/dynamic-dispatch 限制。

### 5. Contract-Carrying Rewrite Gate

- cache/replay/reorder obligations；
- contract/source/configuration digest；
- optimizer candidate boundary；
- workload-derived horizon 与 decision stability；
- registered execution/TOCTOU 边界只保留必要内容。

### 6. Evaluation Methodology

- final-blind 隔离与 commitment；
- baselines：fail-closed、registry、static、dynamic-output、dynamic-stateful、hybrid、manual、oracle；
- adapter accounting、统计方法与 failure taxonomy；
- real workloads 与语义 oracle。

### 7. Results

- RQ1 safety；RQ2 coverage；RQ3人工成本；RQ4 benefit；RQ5 ablation；
- 先报告失败与 Unknown，再报告 aggregate；
- 不汇总跨 Effect 版本准确率。

### 8. Related Work

- ML input pipeline optimization/caching：cedar、Cachew、Pecan、Seneca；
- effect/static analysis for dynamic Python；
- differential/property-based/stateful testing；
- cache invalidation、lineage 与 reproducible randomness。

### 9. Limitations and Threats

- adapter dependence、动态 Python/native code、oracle independence、GPU/领域覆盖、成本漂移；
- 0 observed FA 不等于形式 soundness；
- 模拟 AI 评审不等于真实同行评审。

### 10. Conclusion

只总结已由 final artifact 支持的范围内结论。

## 9. 本轮立即启动的工作

实现一个与 H8C 历史脚本分离的 internal calibration runner：

1. 固定 stateful probe schedule；
2. 合成 pure、hidden RNG、hidden state、environment drift 与 epoch-sensitive 单元；
3. manifest-derived low/planned/high horizon；
4. 输出 machine-readable self-test 与 protocol digest；
5. 通过后再把接口接到 H8C calibration，绝不回写 H8C freeze。

## 10. 2026-07-30 进度更新

Phase A Round 1 已完成 12/12 synthetic checks；H8C-R1 已在与历史 freeze 一致的 Python 3.12.4 / PyTorch 2.4.0 CPU 环境运行。公平 `dynamic_stateful` 在五个已知 H8C workload 上取得 TP=2、FP=0，与 hybrid 完全相同，而 `dynamic_output_only` 仍为 TP=2、FP=3。

因此 RQ5 已提前暴露 novelty risk：旧 dynamic baseline 不能继续承担核心对比。下一主线改为 H8C-R2 novelty falsification，比较有限动态探针对未执行分支、长周期状态、外部依赖和未来 drift 的 detection-budget frontier；若 hybrid 仍无增量，则收缩到 contract/invalidation 可审计性的系统贡献。

H8C-R2 随后完成：在 18 个预注册 synthetic cases 上，EffectV7-style contract 保留 4/4 safe controls 并发现 14/14 unsafe；stateful dynamic 的 unsafe detection 随预算从 14.3% 提升到 92.9%，7-call 时为 50%，63-call 后仍漏掉未绑定 external-file dependency。该结果只支持 source discovery/invalidation 的窄假设，不是跨框架准确率证据。

下一阶段升级为 R3 real-source calibration：在现有 H7 frameworks 上加入 source-guided greybox dynamic 强基线，并以相同 wall-clock budget、Unknown/timeout、adapter/source-guidance burden 比较。R3 是 final corpus 前最后一个 novelty gate；通过后才值得冻结最终 baseline。

R3-P1 已在 H7H 的 9 个真实 Kornia 单元上完成：黑盒 dynamic 在 25/100/500 ms 三档均为 TP=4、FP=1、FN=0、TN=4；加入一条预声明的公开 MRO/container heuristic 后，source-guided greybox 三档均达到 TP=4、FP=0、FN=0、TN=5，与冻结 EffectV7 和 manual upper bound 持平。因此“EffectV7 相对强 greybox 具有检测准确率优势”的宽 C1 在该范围内 no-go，不能再以旧弱动态基线支撑 headline novelty。

主线据此收缩为 contract-carrying reconfiguration safety：R3-P2 比较 decision-equivalent 策略在 version/configuration/operator graph/child/parameter/schema/sample drift 下的 required-invalidation recall、benign-change preservation、reason completeness 与验证/重探测成本；R3-P3 再冻结通用 greybox 规则做跨框架 transfer calibration。只有跨框架材料显示稳定检测增量，final-blind 才保留 analyzer-accuracy RQ；否则论文以可版本化、可失效、可审计的 rewrite gate 为核心贡献。

R3-P2 已完成 13-case 真实 Kornia replay 校准。dynamic reprobe、fixed-witness output snapshot、lineage v1、measured-source v2 candidate 的 required-invalidation recall 分别为 9.1%、45.5%、90.9%、100%，2 个 benign controls 均保留。关键负结果是 v1 放过 same-commit callable replacement：当前证书只绑定调用方声明的 commit 与 operator representation，不能再称为 measured-executable-source-bound。候选 v2 通过实际 HEAD 与 resolved callable canonical-AST digest 修复该 case，但最终复跑 cold median 约 252.8 ms，尚未冻结。

因此 R3 下一优先级改为 P2b：把 measured source index 移到 registration/deployment boundary，测量 cold index、deployment revalidation 与 hot check，并攻击 dirty worktree、import shadow、monkeypatch、decorator/descriptor/native callable 和 cache staleness。完成后再进入 P3 跨框架迁移；在 P2b 以前不得恢复 source-bound 强主张。

R3-P2b 已完成。只缓存 source digest 的策略在 2 个 benign controls 上保持接纳，但放过 3/3 supported post-deployment mutations，并错误接纳 native override；lineage v1 + process-local hot callable sentinel 保留 2/2 benign、拒绝 3/3 supported mutations，并对 native override 返回 Unknown，与每次 cold reindex 的决策一致。sentinel-only hot check 中位 0.669 ms，lineage-v1 为 1.439 ms，组合的真实 per-case 中位为 2.591 ms；cold reindex 中位 407.357 ms。9/9 source fixtures 覆盖 formatting/docstring、AST、defaults、closure、globals、wrapper、origin 与 native Unknown。

该结果把 source-bound 主张恢复为一个更窄且可验证的版本：只针对 phase-reachable、受支持的 Python callable slice；portable measurement 在 registration/deployment 完成，进程内 sentinel 维护检查时有效性。它不覆盖并发 TOCTOU、native internals 或跨进程 identity。下一主线进入 R3-P3 cross-framework transfer；P2c 的 definition 去重与 parse memoization 仅作为次要工程优化。

R3-P3a 已完成 context-compatible transfer。TorchIO H7C 的 7 个 legacy `sample_apply` 单元因没有冻结 replay evidence 而全部退出 replay 分母；imgaug deterministic 与 Albumentations stored-parameter replay 构成两个 eligible families、16 个 formal units。冻结 EffectV7 zero-change 得到 TP=11、FP=0、FN=0、TN=5，safe recall 与 reason accuracy 均为 100%，新增 analyzer/adapter rule=0。该结果是已知语料 posthoc calibration，不是新泛化证据。

11/11 admitted units 均能生成 partial reachable-method AST slice，共 63 methods、11,029 bytes；但 frozen runtime environment 对 imgaug/Albumentations 的 full P2b measured-index readiness 为 0/2，分别缺 cv2，以及 pydantic+cv2。因此下一轮 P3b 必须建立隔离 dependency-locked runtime，验证真实 import/instantiate/replay、module origin、portable index 和 sentinel；静态 slice 不得代替 runtime evidence。

R3-P3b 已在隔离、dependency-locked Python 3.9.19 runtime 完成，预注册结果为 6/8 gates、FAIL。11/11 units 构造成功，10/11 exact replay；`HistogramMatching` 被 Albumentations 公开 replay serialization 明确拒绝，说明 EffectV7 的 reachable-effect contract 缺少 recordability/serializability/target-dependency capability layer。11/11 SourceIndexV0 与 hot sentinel 虽为 Supported，portable digest 跨进程仅 3/11 稳定，根因是 `repr(code.co_consts)` 中的 code-object 地址和 frozenset 非确定顺序。22/22 Python wrapper attacks Reject、11/11 native overrides Unknown、0 Admit。

路线因此重新排序：先做 P3c canonical constant SourceIndexV1，要求保持 11/11 coverage、跨进程 11/11 stable 和已有 mutation fixture；再做 EffectV8 candidate，把 semantic effect 与 framework execution capability 分层合成。两项完成前不进入 final-blind，也不恢复“跨框架 portable executable-source binding 已闭环”的强表述。

P3c 已完成 7/7 gates。递归 typed constants 令 SourceIndexV1 在 parent 与两个不同 `PYTHONHASHSEED` 的 fresh processes 中 11/11 stable，同时保持 11/11 Supported、无 entry drop、22 wrapper Reject、11 native Unknown 和 0 Admit。artifact bytes 增至 V0 的 1.064×，cold median-of-medians 增至约 1.042×，所以仍只适合 registration/deployment boundary。

下一步只剩 P3d capability composition：把 EffectV7 的条件化 semantic decision 与 recordability、serialization/restoration、target-dependent replay compatibility、SourceIndexV1 binding 分开表示再合成。目标不是把 `HistogramMatching` 改判为 semantic unsafe，而是让最终 rewrite eligibility 返回明确的 `Unsupported(capability)`，并验证其余 10 个 runtime replay units 不回归。P3d 通过后才能评估是否具备进入独立 final-blind 的最低实现条件。

P3d ReplayCapabilityV1 已完成 7/7 gates。EffectV7 semantic 11/11 Admit 与 SourceIndexV1 11/11 Supported 保持不变；capability/final 为 10 Supported/Admit、1 Unsupported，唯一 Unsupported 是公开 serialization 明确禁止的 `HistogramMatching`。8/8 composition truth table、10/10 exact replay/RNG/lineage checks 通过。

这意味着已知语料上的内部机制最低闭环完成，但还没有论文最终证据。现在路线从“继续修 analyzer”切换到 final-blind 准备：冻结 capability schema；自动量化每个框架的 adapter LOC、slot policy、target metadata 和人工时间；由独立人员选择至少一个开发期未见框架并制作 oracle；再执行 one-shot prediction。若无法获得独立语料/标注，项目只能停留在 mechanism/workshop calibration，不能把 R3-P3 的 PASS 写成泛化结论。

## 11. P4 后的重新规划：从内部闭环到可证伪交接

P4A 已否决“adapter 普遍轻量/节省人工”的强主张：仅 4/8 adapter 通过轻量诊断，且无前瞻工时。RQ3 不应从论文删除，但必须改成负担测量问题，并在独立接入阶段记录成功与失败的 wall-clock、规则数、SLOC、source slots 和人工复核次数。

P4B/P4C 已完成 ReplayCapability 公共 schema 与 final-blind v2 管理器。重要范围边界是：ReplayCapability 只用于注册参数重放；缓存和相邻交换没有通用 capability receipt，只能分别依靠语义/source/验证计划。最终论文的系统图和指标表都必须保持这一分层。

后续主线按不可逆性排序：

1. 冻结候选论文主张、EffectV7、ReplayCapabilityV1、SourceIndexV1、metric gates 和 final-v2 admin；除发现协议级安全 bug 外不再调整 known-unit 规则。
2. 由独立人员选择真实 final units，并在接触 analyzer 输出前填写 public manifest；项目开发者不得用新框架源码调规则。
3. 独立双人制作 private oracle、完成 adjudication、生成 salted commitment。
4. 只根据 public manifest 实现最小 final adapters/runner，同时前瞻记录负担；若读取新框架代码用于实现，必须明确其角色是“公开接入信息”还是会污染 blind analyzer evaluation，并相应拆分 RQ。
5. 完整 seal 后 one-shot prediction；揭示 oracle 后先报告 unsafe false accepts、Unknown/Unsupported 和分母，再报告 recall/benefit。
6. 根据 gate 决定论文形态：unsafe FA>0 则当前系统版本 no-go；FA=0 但 coverage/benefit 低则收缩为 auditable narrow boundary/workshop；语义、source、replay 与 benefit 均过门槛才进入 full systems paper。

当前不应继续在已知 11 个 replay units 上追加规则，也不应扩展 exactly-once trainer。研究的下一项真正新证据只能来自独立、版本固定、operation-context 明确的 final corpus。

## 12. P5 后的主线修正：rewrite-specific capability 而非通用 purity

P5B–P5E 已经证明固定 cedar commit 的公共 API、runtime 数据路径和真实 cache/reorder optimizer 都能消费 AutoContract-shaped constraints。但 P5F 证明 P5A 的初始安全政策不成立：deterministic/pure/one-to-one 只足以参与某些 cache 判断，不足以证明函数可交换。

因此论文系统模型必须改为三条互不替代的 obligation：

1. cache：randomness/state/external/cardinality 与祖先 effect closure；
2. registered parameter replay：ReplayCapabilityV1；
3. adjacent/general reorder：ReorderCapabilityV0，绑定 exact operator pair/order/context/source/config/input schema，并要求目标 optimizer 可能产生的每个排列都有足够证明。

P5G 的 fail-closed 修复在 synthetic cedar calibration 20/20 PASS：无 receipt 全 fix；完整 pairwise receipts 才开放连续 region；missing/duplicate/Unsupported/stale receipt 均缩小候选空间。该机制现在只是 supplied-proof composition，不能写成自动 commutativity inference。

P5H 随后证明“supplied-proof”还必须带信任根：任意 caller 可以伪造 exact-bound Supported receipt，因为 V0 只检查 schema/digest binding，不重放 `proof_sha256` 对应的证明。伪造三张 receipt 后 P5F 错误输出重新出现。故 V0 只能在 trusted issuer 假设下使用；当前严格模式对外部 receipt 一律 Unknown/full fix。

新的不可逆关键路径为：

1. 冻结 P5F 负结果和 P5G schema，不改写历史 P5A/P5D/P5E artifact；
2. 先实现 V1 proof trust：verifier identity/version/source digest、proof artifact、可重放验证或受信签发/allowlist、assurance tier、revocation；
3. 从真实框架收集 20–40 个候选 operator pairs，明确 input domain、exception/error behavior、random/state effects 和 order context；
4. 双人 oracle 判断 commutes / non-commutes / Unknown，并绑定 SourceIndexV1；
5. 比较 restricted-static/formal、manual-reviewed、bounded differential 三类 producer；严格 Supported 不得仅由有限差分测试产生；
6. 将通过受信 receipt 的 regions 交给 cedar one-shot optimizer，执行 plan 并比较 output/trace/RNG/model metric；
7. 与 cache/replay final 指标分开报告，绝不再用一个通用“safe rewrite”分母混合三类变换。

论文大纲中第 6 节应改为 “Rewrite-Specific Capabilities”，分别列 ReplayCapability、ReorderCapability 和 cache-specific obligations；第 7 节 compiler 只负责保守合成和 backend translation。Pecan 已有 relaxed commutativity/keep-position 思路，因此新颖性不能来自“重排需要交换性”本身，而只能来自 versioned/source-bound/fail-closed receipt、自动 proof producer 的效果，以及独立新语料证据。

## 13. P5I/P5J 后的主线：从 trust closure 转向真实 proof coverage

ReorderCapabilityV1 已完成受限 trust closure。它本地重放精确整数仿射证明，绑定 SourceIndexV1 callable record 与 verifier dependency closure，并支持 revocation。P5I 固定 cedar 23/23 PASS。P5J attempt 0 又发现 V0 贪心 region partition 的 evidence non-monotonicity；V1 改用 full-base-segment complete-cover policy 后，attempt 1 的 55/55 mutations、19/19 subset comparisons 和 callable replacement attack 全部通过。

这使第 12 节关键路径的第 2 项在“restricted affine + local verifier”范围内完成，但第 3–6 项尚未开始。下一阶段不得继续把 synthetic PASS 累积成泛化主张，工作包固定为：

1. 公开冻结 20–40 个真实 pair 候选与 inclusion/exclusion 原因；
2. 对 dtype/overflow、shape/channel、error/exception、RNG/state/I/O、order context 制作 pair statement；
3. 独立双人 oracle 标记 Commutes / Non-commutes / Unknown；
4. 比较 restricted-static、manual-reviewed、bounded differential 的 coverage、错误与人工成本；
5. strict Supported 只来自本地可重放或受信且可撤销 verifier，bounded differential 只作反例搜索/辅助；
6. 在 cedar one-shot plan 上分别报告 candidate space、实际路径、output/trace/RNG/model metric 和收益。

若 restricted-static 在真实 pair 上 coverage 接近零，则论文仍可保留“proof-carrying fail-closed gate”的机制贡献，但自动 proof producer 只能作为可行性原型；若 independent oracle 或真实 plan benefit 缺失，论文等级仍停留在 technical report/workshop，而不是 full systems paper。

## 14. P5K 后的 coverage 决策

restricted-static V1 在 28 个真实 torchvision pair 上 strict coverage=0，P5K 已实际触发第 13 节的低覆盖分支。bounded differential 在 global RNG 下给出 14 个可复现 Noncommutes witnesses，但另外 14 个只能保持 Unknown；operator-keyed RNG 改变三对结论。故下一贡献问题从“receipt 能否被信任”转为“局部可验证 relation lemma 能覆盖多少真实 pair，且需要多少 framework-specific adapter”。

P5L 第一版只允许三类可审计 algebra：identity；pointwise channel affine/linear；spatial index map/selection。每个 lemma application 必须绑定 exact framework tree、operator type/config、required callable slots、SourceIndexV1 与 RNG context。明确排除 resize、blur 和 dtype conversion，直到存在 interpolation-weight/boundary/rounding proof。

预期 coverage 假设为：P5K 的 14 个 Unknown 中至多 10 个可由该最小 algebra 签发；任何已找到 counterexample 的 pair 必须保持 Noncommutes；未匹配 lemma 的 pair 保持 Unknown。若实际 verified coverage 低于 30% 或 adapter/proof LOC 过高，则停止自动 producer 扩展，把 V1 定位为外部 proof-carrying gate；若达到约 50% 且零反例冲突，再进入真实 cedar region/plan 执行。

## 15. P5L 后的主线：先证伪 lemma boundary，再扩 proof family

P5L 达到继续条件：14 个 P5K Unknown 中 10 个获得本地可重放 Supported（71.43%），28-pair 总覆盖 35.71%，并且与 14 个已知 counterexamples 零冲突。固定 cedar 的 deterministic torchvision chain 也从 1 个候选恢复到 6 个，实际换序后输出完全一致。由此可保留一个窄可行性结论：version/source/config/domain-bound local relation algebra 能为部分真实算子对生成严格 receipt。

该 PASS 尚不能触发更多规则扩张。新风险已经从 receipt trust 转到 handwritten semantic bridge 是否准确描述 upstream implementation。P5M 固定为 adversarial boundary work package：

1. 枚举 admitted operator 的 shape/channel/dtype/config 边界；任何不满足 lemma 前提的实例必须在签发前 Unknown；
2. 对域内边界值和多 seed 做 metamorphic execution，专门寻找 adapter 与真实 torchvision 实现的偏差；
3. 在含随机 crop 的 cedar chain 比较 output、exception、RNG post-state 和 optimizer path；
4. 量化 producer/verifier latency、receipt size、relation-specific SLOC 和 marginal coverage；
5. 保留 `normalize-resize`、`resize-random_hflip`、blur 与 dtype pairs 为 Unknown，除非另有独立、可重放的 interpolation/boundary/rounding proof。

P5M 若出现任何域内 unsafe accept，应先撤销相应 lemma/version，不能靠放宽 tolerance 修补；若域外拒绝和域内执行均通过，下一不可替代证据仍是独立 pair selection/oracle 与 prospective adapter burden，而不是继续在 P5K 已知 corpus 上调 coverage。

## 16. P5M 后的主线：停止内部 coverage tuning，进入 reorder-final handoff

P5M 11/11 PASS，没有触发 lemma revocation：28 个 domain/config 域外攻击全部 fail closed，864 个域内边界 trial 的 exact output、exception 和三套 RNG post-state 全部一致。随机 cedar chain 实际换序后也保持 8/8 exact output 和 RNG post-state。因此 V2 可称 mutation-hardened known-version prototype，但仍不能称为 upstream formal proof。

本轮同时量化出不可忽略的 burden：两条 relation lemma 已需要 208 semantic-adapter SLOC；单张 receipt 约 2.9 KB，固定环境本地生成/验证中位数约 80.5/101.8 ms。下一阶段不能用继续扩 P5K coverage 回避独立性与人工成本问题。

主线切换到 P5N reorder-final handoff：

1. 复用 final-blind v2 的 seal/reveal 管理，不另造弱化版 blind 定义；
2. 冻结 pair-selection guide、operation/RNG context、input domain、exception semantics 和三分类 oracle schema；
3. 独立人员选择 20–40 个新 pair，两名标注者在 analyzer 输出前完成 adjudication 与 salted commitment；
4. analyzer 侧 reveal 前只生成 V1/V2 predictions，并前瞻记录 adapter wall-clock、SLOC、proof latency 和 Unsupported reason；
5. reveal 后首先报告 unsafe Supported、Unknown/Unsupported 与分母，再报告 coverage 和 cedar benefit；unsafe Supported>0 则当前 verifier version no-go；
6. 若无法获得真正独立人员，只能把工具包自测称为 administrative readiness，内部 AI 拟真评审不能升级为 independent evidence。

Interpolation、blur boundary 和 dtype rounding relation 在 P5N reveal 前保持冻结 Unknown。只有独立 corpus 显示它们构成主要、可行且不会泄漏 oracle 的 coverage bottleneck，才启动新的 verifier version。

## 17. P5N 后的路线：行政工具完成，真实角色独立性成为硬 blocker

P5N reorder-final handoff synthetic self-test 为 30/30 PASS。Public pair selection、private three-way oracle、oracle commitment、public artifact freeze、sealed prediction、prediction commitment 和 reveal score 已形成一条机器可验证链。第一次 receipt-key false positive 被保留，修复没有改变任何科学 gate。

因此下一轮不能再由项目开发者“自行选一些没见过的 pair”并称为 final。正式执行需要四类外部角色：独立 selector；primary/reviewer（有分歧时 adjudicator）；private oracle custodian；reveal evaluator。Analyzer operator 只能在 oracle commitment 后、prediction seal 前读取 public manifest 与公开源码。

可并行但不能替代独立语料的内部工作只剩：

1. 向独立人员交付 guide、三套 templates 和 CLI 命令，并只回答 schema/流程问题；
2. 准备隔离环境与 prospective time log，但不预先读取他们将选择的 framework/pair；
3. 等 public manifest sealed 后才实现必要 adapter，并把所有 source inspection 计入 burden；
4. prediction seal 后停止 analyzer 修改，等待 custodian reveal；
5. 首先根据 unsafe Supported gate 决定当前 verifier version go/no-go。

如果短期无法找到独立人员，研究可以另开“第二 backend benefit”工程支线，但该支线不能填补 RQ1 独立 safety/coverage 证据，也不能把 P5N synthetic 24-pair score 写入论文 Results。

## 18. 外部三评审后的路线修订：P5O domain/native assurance 先于正式 handoff

三份唯一外部 AI 评审均认为 independent final、end-to-end benefit、adapter burden、input-domain membership 和 RNG context 是 full-paper blocker；第三份还强调 Python SourceIndex 不能覆盖 Native/ABI/hardware state，以及异常、浮点与 RNG post-state 必须进入观测语义。主线据此在真实 selector 入场前增加一个不得接触未来 final corpus 的 P5O：

1. 对 identity 与 pointwise/spatial lemma 做 premise-use audit，删除未参与证明的 value bounds；
2. 比较 registration attestation、batch structural sentinel、per-sample guard 的 detection/overhead，冻结实际需要强制的 domain 前提；
3. 盘点 pure-Python、known-native 与 opaque-native boundary；未绑定 native implementation 的 strict statement 默认 Unknown；
4. 将 global-sequential/operator-keyed RNG strata、pair-family、definedness/exception、observational relation、Wilson interval、manual/external-proof baseline 加入 public/private/prediction schema；
5. 生成 worksheet/CLI，先用 6–8 个 synthetic/已污染 pair 做流程与工时 dry-run，所有数字明确排除出 final Results；
6. schema/tool freeze 后交给真实独立 selector，正式 20–40 pair evaluation 不再针对结果改 gate。

正式 final 的 viability 不再只看 overall coverage≥30%；还需 Supported 不集中于 identity/简单仿射、至少跨两个 framework，并报告 family-stratified coverage 与区间。当前 exact lemma 继续要求 exact output、相同 exception/definedness 与 RNG post-state；近似浮点 family 在定义新 relation 前保持 Unknown。任何 unsafe Supported 仍为当前 verifier version 的绝对 no-go。真实 cedar workload 在 prediction seal 后执行，安全、coverage、burden、benefit 分表报告。第二 backend 为 P1，不抢在 independent safety evidence 前扩张。

## 19. P5O 后的执行决策：冻结前提策略，停止无差别热扫描

P5O 21/21 PASS，旧 P5N 30/30 回归 hash 不变。当前两个 V2 lemma 并不使用 value range、spatial maximum 或 finite-only premise；它们只需要固定 representation/runtime slice，并在 selection operator 上使用最小高度/宽度保证 totality。因此 final-v3 不做逐元素 value/nonfinite scan：uniform dense NCHW batch 在 boundary 检查共享 dtype/channel/device/min-shape，ragged/list 输入则逐 sample 检查；registration 只绑定声明，不能单独授权 Supported。

Native 边界冻结为四类：pure Python 可本地证明；known-versioned native 只能在 pinned runtime identity 和 relation-specific lemma 下授权；opaque native 无 external attestation 时 Unknown；external proof 必须有独立可撤销 verifier。SourceIndex 贡献必须写成 Python dispatch/source binding，不能写成 native kernel attestation。

final-v3 已加入 pair family、RNG strata、output/definedness/exception/RNG observation、premise profile、guard mode、native policy、Wilson interval 和 prospective burden。其 8-pair contaminated dry-run 只证明行政与 fail-closed 路径。下一主线分两条但证据不可互换：外部角色执行独立 20–40 pair final；内部在 prediction seal 后运行真实 cedar workload harness。若外部角色尚未到位，优先准备 workload harness，不能继续扩已知 torchvision coverage 冒充 final。

## 20. P5P–P5Q 后的主线：行政与 workload harness 就绪，停止内部追分

P5P 25/25 PASS，final-v3 已有 role-separated validate/commit/freeze/seal/reveal CLI；P5Q 19/19 PASS，真实 cedar plan 已贯通到 exact ResNet18 loss/logit/gradient/model-state。由此，“不会交接”和“只比较 tensor 不看训练”两个工程 blocker 已移除。

P5Q 同时给出关键负结果：严格预热/交替复跑后，receipt-guarded preprocessing 比 fail-closed baseline 慢约 5.7%；端到端约 3% 表面差异因两臂模型计算完全相同，只能视为 timing noise。当前不能写“已证明 practical acceleration”。也不能事后放大 crop/input size 直到出现 speedup，再把该数字当成预注册证据。

后续只保留两项 P0：

1. 外部 selector/annotators 用 final-v3 产生真正 independent 20–40 pair safety/coverage/burden；
2. public manifest/prediction seal 后，按真实 task 冻结 workload manifest，再运行 no-constraint、manual constraint、receipt-guarded cedar，报告 output/RNG/sample trace/model metric 与冷/热 performance。

若安全通过但真实 workload 无 benefit，则论文收缩为 proof-carrying audit gate/负结果 systems study；若出现 unsafe Supported，当前 verifier version 直接 no-go。第二 backend 仍在这两项之后。
