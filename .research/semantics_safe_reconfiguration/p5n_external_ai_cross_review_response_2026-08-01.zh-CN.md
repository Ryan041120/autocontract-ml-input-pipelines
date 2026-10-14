# AutoContract P5N 外部 AI 三评审共识、裁决与路线修订

日期：2026-08-01
对象：P5N 单文件评审包的三份唯一评审文本（另有一份重复附件）

## 1. 输入去重与证据边界

第一轮三份附件中只有两份唯一文本；本轮用户又直接粘贴了一份内容不同的完整报告：

| 编号 | SHA-256 | 字节数 | 处理 |
|---|---|---:|---|
| Review A | `82ec1d26100102b10a88111d5ce635882a737fa3bf092fcb9357ddf9aa27b6bb` | 27,749 | 独立文本 A |
| Review B | `d1f6ecab4a16e9ba4eee754e14a49691aefcccee4a90cc6da0699dff0679b3cc` | 20,063 | 独立文本 B |
| Duplicate B | `d1f6ecab4a16e9ba4eee754e14a49691aefcccee4a90cc6da0699dff0679b3cc` | 20,063 | 与 B 逐字节相同，不重复计票 |
| Review C | 无单独附件 hash | 用户消息中的完整文本 | 独立文本 C；禁止联网，未独立运行实验 |

所以当前是 **3 份唯一 AI 评审**，而不是把重复附件算成第四票。三者都基于同一作者提供 snapshot，没有真实 private oracle；A/B 未独立运行 Python/cedar，C 也明确没有运行项目实验且不能联网核查最新工作。它们可作为高质量 design critique，不能作为系统正确性、新颖性或论文录用概率的独立实验。

## 2. 共识

三份评审在以下判断上形成强共识：

1. 研究问题真实且有价值：现有 input optimizer 需要用户提供 randomness/dependency/reorder hints，自动生成可失效安全约束有明确缺口。
2. P5F 的 pure-but-noncommutative 真实 cedar 反例、P5H trust attack 和后续 fail-closed 修复是当前最可信、最有叙事价值的材料。
3. 当前机制在内部已知语料上形成闭环，但 P5K–P5M 不是 independent evidence，P5N 24-pair fixture 只是行政自测。
4. 当前适合 workshop/short paper 或技术报告；正规 systems/MLSys full paper 当前应 Reject/Weak Reject。
5. 真实独立 20–40 pairs、双人 oracle、one-shot seal/reveal 是不可替代 P0。
6. 没有真实 end-to-end training/workload benefit，不能声称系统值得部署。
7. 手写 relation lemma/adapter 是 trusted semantic bridge，mutation testing 不能升级为形式 soundness。
8. P4A 4/8 lightweight gate 与 P5M 208 semantic SLOC 使“adapter 普遍轻量”不可恢复。
9. 声明 input domain 与实际 runtime sample membership 之间缺少 assurance layer。
10. RNG assignment 会改变 pair evidence，final 必须按 global sequential、operator-keyed 等 context 分层。
11. novelty 是组合增量：不能声称发明 optimizer、commutativity 或 effect analysis；最可能的新意是 rewrite-specific、source/version/context-bound、locally replayed/fail-closed proof transport 与 invalidation。
12. Python SourceIndex 对 native kernel、ABI、底层库与硬件状态不透明；若不显式缩窄范围或增加 native identity/boundary policy，不能把 Python 绑定泛化为跨语言完整语义绑定。
13. Final 语料必须覆盖非平凡 family、异常/definedness、浮点与随机上下文，不能靠大量 `identity` 或简单仿射对跨过 coverage gate。

三份报告对 workshop 的推荐横跨 Borderline/Weak Accept 到 Strong Accept，因此只记录为“已具 workshop/technical-report 价值”，不伪造一个统一分数；对 full paper 则一致为 Reject。Review C 的创新性判断因无法联网而自报置信度降级，不能据此确认 2026 年 novelty。

## 3. 对批评的逐项裁决

### 3.1 “独立 final 尚未执行”：接受，P0

这是当前最硬 blocker。P5N 只证明 public/private/prediction schema、commitment、seal 和 reveal scorer 能工作；不能把 synthetic `NovelFrame-*`、synthetic labels 或 30/30 admin PASS 写进 Results。下一次核心安全/coverage 数字必须来自独立选择、密封 oracle 和 one-shot prediction。

### 3.2 “无 end-to-end benefit”：接受，full-paper P0；workshop 可降级

cedar 已真实消费 constraints 并改变 plan，但尚未回答真实训练吞吐、成本、模型 metric 是否受益。对于 full paper，这是 P0；对于明确定位为 mechanism/falsification 的 workshop，可作为 limitation，但不得使用“practical acceleration” headline。

### 3.3 “adapter burden 是 Fatal”：部分接受

它不是 soundness fatal，因为论文已经撤销“adapter 普遍轻量”和“自动化替代专家”。它是 **significance/deployability major risk**：如果独立 onboarding 显著高于 manual baseline，论文必须定位为 proof-carrying audit gate/经验研究，而非低成本自动系统。P5O 必须前瞻记录 selector 以外的 analyzer onboarding wall-clock、SLOC、规则数、失败/放弃和人工复核轮次。

### 3.4 “input-domain membership 无热路径 gate”：接受问题，修复方式需收窄

当前 receipt 绑定声明 domain，未证明运行样本实际属于声明。评审建议逐样本检查 dtype/shape/value range；直接照做可能引入不必要热路径扫描，而且 P5L 的 pointwise/spatial lemma 实际并未使用 `[0,1]` value bound。

先做 **premise minimization**：明确每个 lemma 真正依赖的 representation/channel/dtype/device/shape/finite 前提，删除不参与证明的 value-range 条件。然后比较三种 assurance：registration-time schema attestation、batch-boundary structural sentinel、per-sample guard。只对证明必需且能低成本验证的前提进入 runtime guard，并报告 overhead。不能用“上游保证”一句话掩盖该假设。

### 3.5 “RNG semantics 覆盖不足”：接受，P0 protocol amendment

P5K 已观察到三对 context contrast。Final public manifest 必须把 RNG assignment 视为 statement identity 的一部分；至少预注册 global-sequential 与 operator-keyed strata，并分开报告 coverage/unsafe Supported。分布式/per-worker/explicit-generator 若不纳入，必须列为范围外，不能在结论中泛化。

### 3.6 “30% coverage gate 太低且可能集中于 trivial identity”：接受风险，修订 viability gate

保留 safety gate `unsafe Supported=0` 和 completion=100%，但不再让单一 overall 30% 决定“系统有用”。Final 还应：

- 报告 Commutes denominator 的 Wilson 区间；
- 按 identity、pointwise/spatial、random-context、boundary/rounding 等 family 分层；
- 要求 Supported 不只来自 identity，并至少跨两个 framework；
- 与 manual-reviewed/external-proof upper bound 比较；
- 把 overall ≥30% 视为最低 pilot viability，不是 full-paper sufficiency。

真实 final 执行前可以修改 protocol；一旦 public manifest/oracle commitment seal，禁止再改 gate。

### 3.7 “需要第二 backend”：部分接受，P1

第二 backend 能提高外部有效性，但在 independent safety/coverage 以前立即扩 HyCache/Cachew 容易再次扩大工程支线。先完成一个独立 reorder stratum 与真实 cedar workload；通过 safety/coverage gate 后，再以第二 backend 证明 constraint transport 不是 cedar-specific。Full paper 最终应包含，workshop 不必作为当前 P0。

### 3.8 “pairwise complete cover 对随机/状态链可能不足”：接受为威胁，当前机制有条件成立

对真正 pairwise commuting 且同一 operation context、无隐藏共享 mutable state 的算子，complete pair cover 可支持 permutation；风险在于 pair statement 是否遗漏 RNG assignment、state、definedness 或 indirect dependency。Final 应包含多随机算子链和共享状态 adversarial case，并执行 target optimizer 实际选中的 plan，而不只验证 pair receipt。

### 3.9 “gradient、epoch order 也应进入 Commutes”：部分接受

对于纯 input tensor transformation，exact output、definedness/exception 与 RNG post-state 是当前 reorder statement 的核心观测；gradient 并非所有 preprocessing framework 的语义维度。真正缺失的是 workload-level sample/epoch trace 与 model metric。它们应在 backend benefit 层验证，不必不加区分地塞进每张 pair receipt。

### 3.10 评审人提出的 8 小时/operator、5% throughput、10% overhead：不采纳为现成 gate

这些数值没有来自冻结 pilot、相关系统基线或成本模型，是 posthoc reviewer suggestion。可将其作为设计讨论，但不能直接写入 protocol。应在 final 前用小型流程 dry-run 估计量纲，再预注册与 manual/no-constraint baseline 的相对判据和描述性区间。

### 3.11 “SourceIndex 遗漏 Native/ABI/hardware state”：接受为范围与失效边界，P0 明示、P1 扩展

Python AST/bytecode/source-tree digest 不能代表 C++/CUDA kernel、动态链接库、cuDNN 算法选择或硬件状态。当前不能宣称跨语言 exact source binding。P5O 应增加 native-boundary inventory：区分 pure-Python、known native callable、opaque native/side-effecting boundary；严格模式对未绑定的 native implementation 默认 Unknown。对确需支持的 native op，至少绑定 framework/build/backend/ABI identity 和可观测执行语义，但 OOM、调度等非确定环境事件仍作为范围外 limitation。第二阶段再研究 binary/kernel attestation，不能把它塞进当前 SourceIndexV1 的既有结论。

### 3.12 “`max_abs_delta=0` 没覆盖浮点、异常和 RNG 步进”：部分接受

P5M 已对当前 admitted exact lemma 检查 exact output、exception behavior 与 Python/NumPy/torch RNG post-state，所以不是只看一个数值 delta；但这只覆盖固定版本、受限算子族。Final schema 应把 output relation、definedness/exception 和 RNG post-state 分列。对数学上只能近似等价的 interpolation/reduction/low-precision family，不能临时放宽 tolerance 后签发现有 `commutes` receipt；必须定义新的 observational relation、误差预算及下游 metric obligation，否则保持 Unknown。

### 3.13 “需要 50–80 units 与 20–40 pairs”：拆分两个评测层级

当前 P5N 是 reorder-specific final，20–40 个 pair 是它的目标样本；50–80 units 属于更广的 Effect/Replay/Cache full-paper evaluation，不能为了显得规模大而混进 pair 分母。先完成独立 reorder final；若论文保留跨 rewrite headline，再单独执行 broader unit corpus，并为两类任务分别报告 oracle、coverage 与 burden。

## 4. 修订后的贡献主线

保留：

1. **Rewrite-specific safety obligations**：以 P5F 证明 cache/replay/effect purity 不能替代 reorder commutativity。
2. **Contract-carrying, versioned invalidation**：exact operation/context/config/input/source binding、local replay/trusted revocable verifier、fail-closed optimizer translation。
3. **Evidence-first integration**：在真实 cedar 中执行反例、约束消费、换序 output/RNG preservation，并以独立 sealed evaluation 衡量 unsafe accepts、coverage、burden 和 benefit。

降级或删除 headline：

- EffectV7 相对强 analyzer 的准确率优势；
- adapter 普遍轻量；
- 自动证明任意 Python/torchvision；
- 通用 rewrite capability；
- 仅凭 10/28、864/864 或 30/30 推断泛化；
- 已证明 end-to-end acceleration。

## 5. 修订后的执行路线

### P0-A：P5O domain assurance 与低负担 dry-run

在不查看任何未来 final pair/oracle 的前提下：

1. 对 V2 两个 lemma 做 premise-use audit；
2. 实现 registration/batch/per-sample 三种 domain assurance prototype，测 overhead 与漏检；
3. 增加 native-boundary inventory 与 fail-closed classification，不把 Python source binding 泛化到 opaque kernels；
4. 将 RNG context strata、pair family、definedness/exception、observational relation、Wilson interval 和 manual baseline 字段加入 P5N schema；
5. 提供 human-friendly worksheet/CLI；用 6–8 个 synthetic/已污染 pair 做流程 dry-run，只验证人机交接耗时，不产生科学 score。

### P0-B：独立 reorder final

由未参与 P5K–P5O 规则设计的人选择 20–40 real pairs；至少 3 framework、2 domain，并预设非平凡 family 配额，避免全是 identity/简单平移；双人 oracle + adjudication + custodian；public/oracle/prediction 依次 seal；reveal 前 analyzer freeze。首先报告 unsafe/unresolved Supported，再报告分层 coverage、interval、burden。

### P0-C：真实 cedar workload benefit

在 prediction seal 后、oracle reveal 前执行 receipt 驱动的 cedar plans，报告实际 path、output/exception/RNG/sample trace、throughput/cost 和 model metric；保留 no-constraint、all-fix/manual constraint baselines。Benefit 与 safety 分表，不能互相替代。

### P1：第二 backend 与 external proof producer

P0-B/C 通过后，选择一个非 cedar backend 验证 constraint transport，并比较 local relation algebra、manual-reviewed proof、external trusted verifier 的 coverage/burden。

### P2：论文收口与独立复现

以 P5F 开场，压缩 P5A–P5E calibration history；提供容器/lockfile、固定 cedar checkout 和最短复现命令；把所有 unsupported/excluded family 与 adapter negative result 放入主文而非只放 appendix。

## 6. 当前论文级别与 go/no-go

- 当前：workshop/technical report **Borderline–Weak Accept**；full paper **Reject**。
- 继续 full-paper 路线：independent final 的 unsafe Supported=0，coverage 不集中于 identity 且跨 framework；prospective burden 相对 manual baseline 有合理价值；真实 workload 有可解释 benefit 且 model/trace 不回归。
- 收缩：安全通过但 coverage/benefit 低，或 burden 高于 manual；定位为 narrow proof-carrying audit gate/负结果经验研究。
- 当前 verifier no-go：出现任何经 adjudication 确认的 unsafe Supported；必须撤销 verifier version、恢复 full fix，不能在 reveal 后针对同一 corpus 修规则并重报 final。

## 7. 对三份评审的最终响应

三份评审没有推翻 AutoContract 的研究价值，反而使价值边界更清楚：最强贡献不是“我们已经自动优化了大量 pipeline”，而是发现 rewrite safety 不能由通用 purity 代理，并构建了 source/version/context-bound 的保守 proof gate。它们也一致证明当前离 full paper 还差的不是文档或内部测试数量，而是独立 external validity、真实部署收益和人工成本；第三份进一步迫使我们把 native/ABI boundary 与 definedness 写入明确边界。后续工作必须围绕这些项，不再用新增 known-corpus PASS 回避主问题。
