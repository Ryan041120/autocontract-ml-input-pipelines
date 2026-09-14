# AutoContract 研究就绪审计（2026-07-30）

## 一句话状态

项目已从“想法/原型”进入**固定真实 backend 的机制集成与盲测基础设施阶段**，但尚未获得独立外部证据。cedar 的 API、runtime 数据路径、cache/reorder plan consumption 已跑通；一次真实执行还发现并修复了 reorder authorization 漏洞。当前最准确的状态仍不是“最终测试快结束”，而是“已具备更可信的内部系统闭环，真实独立语料、oracle 与最终收益测试尚未开始”。

## 贡献与证据状态

| 候选贡献 | 当前证据 | verdict |
|---|---|---|
| EffectV7 在已知框架上推断 operation/phase-sensitive effects | 多轮已知语料 calibration；强 greybox 在 Kornia 持平 | 机制成立；检测准确率 headline **no-go** |
| contract-carrying、版本化 rewrite invalidation | SourceIndexV1 跨进程 11/11 stable；mutation Reject/Unknown；known units | 最强主线，但仍缺独立 final |
| parameter replay capability 分层 | ReplayCapabilityV1；10/11 known runtime Supported、1 Unsupported；公共 schema 14/14 | 内部闭环；缺 novel framework |
| 面向现有 optimizer 的安全 constraint compiler | P5A 15/15；P5B/C 固定 cedar API/runtime；P5D/E 真实 plan consumption | cedar 机制集成成立；仍缺独立语料与训练收益 |
| adjacent reorder authorization | P5F–P5H 暴露 purity/trust 漏洞；P5I V1 23/23；P5J 6/6；P5K–M coverage/boundary；P5N handoff 30/30 | V2 固定已知 corpus coverage=10/28、864 trials 零 mismatch；reorder-final admin 就绪；真实 independent pairs/oracle 尚未开始，semantic bridge 208 SLOC |
| adapter 普遍轻量/节省人工 | 只有 4/8 通过轻量门槛，0/8 prospective time | **FAIL/unsupported**，必须作为负结果 |
| end-to-end training benefit | H8 内部 cache/replay pilots，不是 independent final | 不足以作论文最终收益主张 |

## 工程审计

- 70 个 `benchmark/final_v1`/`final_v2`/`final_v3` JSON 文件全部可解析。
- 101 个 `experiments/*.py` 文件全部通过 Python 语法解析；P5O/P5P/P5Q 另在固定 Python 3.11 runtime 通过 bytecode compile 与完整执行。
- 65 个 `.research` Markdown/README 文件全部能以 UTF-8 解码；另有 P5N 独立人员指南与 P5O final-v3 worksheet。
- `experiments/test_autocontract_symbol_origin.py` 以标准库 unittest 运行 7/7 通过；当前环境没有 pytest，因此 pytest 命令未运行。
- P4B 复跑 14/14 PASS，SHA-256 `811334a0ddba74aaaae966024b3258ade3f375e7df477cb717cb11b097f555a8`。
- P4C 复跑 20/20 PASS，SHA-256 `e9f4c87dd97a997f244aab632881081c56263e7abe1ebb2992440293ba803a3f`。
- P5A 复跑 15/15 PASS，SHA-256 `59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a`，且 protocol v2 hash 绑定一致。
- P5B/P5C/P5D/P5E 分别为 12/12、15/15、17/17、17/17 PASS；结果 SHA-256 分别为 `217a4060fbe16326365102611968bf8ecbc9a4fa2697ebb5ea18c85b577766d9`、`776f62f171d84d87d87e5fb56367cd00db8cb36d59494b3ecbff5b5dec881cdc`、`b22523811a844b39ddcd1991866220af275fee42d35370830bdbb0ad0b49c7fe`、`db80c6d97c27a4c19c4feb1d497fcffcaca5e849ea19dc30c932b2ad8ed01317`。
- P5F counterexample reproduction 11/11 PASS，但系统 verdict 为 `fail_unsafe_reorder_authorization`；结果 SHA-256 `83076a5667e219c334e10402ddad8b1ef813a3ab6264ed5f5a67e175cca16eff`。
- P5G ReorderCapabilityV0 20/20 PASS，SHA-256 `0922f625d24880719aa4d1e148b5288297bea0759d41eff6be81114685c6d060`；所有 P5A–P5G result 的 protocol hash 均与当前文件一致。
- P5H untrusted-receipt attack reproduction 8/8 PASS，系统 verdict 为 `fail_unverified_receipt_trust_boundary`，SHA-256 `057fda1f173f4f94dce50dc37c17798a3ffa0d5702f09faef0b08ab220390419`。P5G 应降格表述为 trusted-receipt composition calibration。
- P5I ReorderCapabilityV1 在固定 cedar 上 23/23 PASS：本地重放 restricted affine proof、SourceIndexV1 callable binding、verifier closure/version、revocation 与公开 schema 均通过；真实可交换正例恢复 6 个计划且输出不变。
- P5J attempt 0 保留 5/6 FAIL（55/55 mutations 拒绝，但 subset monotonicity 18/19）；V1 改为 full-base-segment complete-cover 后 attempt 1 为 6/6 PASS，55/55 mutations、19/19 monotonicity、post-issue callable replacement 和 complete-cover gate 全部通过。
- P5K 在固定 torchvision 0.15.2+cpu source tree 上 11/11 PASS：28 pairs 中 global RNG 14 个 counterexample、14 个 Unknown，operator-keyed 为 11/17；strict affine Supported=0/28。该 PASS 是证据分层与负覆盖结论，不是自动证明成功。
- P5L ReorderCapabilityV2 11/11 PASS：最小 source-bound relation algebra 将 P5K 14 个 Unknown 中 10 个升级为本地可重放 Supported（71.43%），全 corpus strict coverage=10/28，已知反例冲突=0；8 类 binding/revocation/duplicate 攻击全部 fail closed。固定 cedar chain 从 1 个候选恢复到 6 个并保持 exact output。结果 SHA-256 `832e2f721ae4df169d55d4e2763faa5483e2fbdf7e42b3f1af08cd7590980b38`。
- P5M relation-boundary falsification 11/11 PASS：15 个 domain/totality 与 13 个 operator-config mutations 全拒绝；864 个 admitted boundary trials 的 exact output/exception/Python+NumPy+torch RNG post-state 零 mismatch。随机 cedar chain 从 1 个候选恢复至 6 个，8/8 outputs 与 RNG post-state 一致。receipt 2,928 bytes，generation/verification median 约 80.526/101.798 ms，semantic adapter 208 SLOC。结果 SHA-256 `f244a33287d66902ff569d6fe94c2f7489120c1d0974f6468036954823edbec8`。
- P5N reorder-final handoff attempt 0 因把 prediction `receipt_sha256` 误判为泄漏字段而 ERROR，修正 public/prediction 分离词表后 30/30 PASS。24-pair synthetic fixture 覆盖 public/private/prediction schema/templates、角色独立性、污染、双 commitment、artifact freeze、oracle/prediction tamper、witness 义务和 unsafe Supported gate。结果 SHA-256 `e48438d1ad1802781b184b6120eec97d6656e22940f9d919b5bf0c774754202f`；它是行政证据，不是真实 pair score。
- P5N 后第一轮三份外部 AI 回传中两份逐字节相同，之后又收到一份不同的完整报告，故当前为三份唯一 design review。三者对 workshop 从 Borderline/Weak Accept 到 Strong Accept 不等，但一致判 full paper Reject，并共同指出 independent final、真实 workload、adapter burden、domain membership 与 RNG strata；新增报告还强调 native/ABI boundary、definedness/exception 和非平凡 pair selection。评审均未独立复跑完整源码，其中一份不能联网，故作为路线压力测试而非 correctness/novelty evidence；裁决记录在 `p5n_external_ai_cross_review_response_2026-08-01.zh-CN.md`。
- P5O domain/native assurance 21/21 PASS，结果 SHA-256 `c46bcdcfca3901bce8145866eda0d1e9d7cd66cef236685bde968df3f578bf46`。5 类结构违例的 registration/list-boundary/per-sample 检出为 0/5、1/5、5/5；uniform dense batch 为 3/3。当前 lemma 不使用 value/nonfinite/max-spatial 字段，故不做无依据热扫描。torchvision 被降格表述为 known-versioned native，opaque builtin 无 external attestation 强制 Unknown。final-v3 schema/worksheet 与 8-pair contaminated dry-run 已完成，但 `scientific_evidence=false`。
- P5P final-v3 handoff 25/25 PASS，结果 SHA-256 `a100a54395fc1281a817003603c6cd3d4c01770e7413b1ac828a9372e0e8a4a8`。validate/commit/freeze/seal/reveal、family/RNG/Wilson、domain/native policy 与 prospective burden 已机器化；8-pair fixture 仍不可升级为 independent evidence。
- P5Q cedar→ResNet18 19/19 PASS，结果 SHA-256 `8b77cd9fdfbd569a26bc72fb29045b017889b742febcef7eea88599471d645b2`。candidate 1→6、path 改变，24 tensors/RNG/loss/logits/gradients/model state exact；但预热复跑 preprocessing ratio=1.057×（guarded 较慢），端到端小差异是 timing noise，故 workload benefit 仍未 PASS。
- cedar 隔离 runtime 约 2.38 GiB；主环境未被修改。该负担必须计入真实 onboarding/adapter RQ。
- `git diff --check` 无 whitespace error；工作树包含大量此前研究产物和用户改动，未擅自 stage/commit。

## 真正的关键路径

### Gate F0：冻结前声明

先把论文 headline 冻结为：为已有 ML input optimizers 生成 operation-context-aware、source-bound、fail-closed constraints，并针对不同 rewrite 合成独立 obligation。parameter replay 使用 ReplayCapabilityV1；reorder 需要受信且可验证的 pairwise capability；cache 使用 randomness/state/external/cardinality closure。明确撤销“检测准确率优于强 greybox”“adapter 普遍轻量”“通用 rewrite capability”“pure 即可 reorder”“V0 receipt 自身证明 commutativity”五项强说法。

### Gate F1：独立 corpus

由没有参与 EffectV7/P3/P5 调规则的人选择 50–80 个真实 units；至少 3 个框架、2 个领域、20 rewrite、6 optimizer workload，并单列 20–40 个真实 reorder operator pairs。选择时只看公开任务定义，不给 analyzer 开发者 oracle。若研究者本人选和标全部语料，只能称 held-out，不应称 independent blind。

P5N 已提供 reorder 专用 selection guide、public schema/template 和 contamination gate，并用 synthetic 24-pair fixture 自测通过；这只完成 F1 的交接基础设施，真实 selector 尚未执行选择，因此 F1 仍未 PASS。

### Gate F2：独立 oracle 与 commitment

两名独立标注者依据 exact operation/configuration/phase/source binding 给出 semantic labels、replay capability labels 和 pairwise commutativity/Unknown labels，完成 adjudication；public manifest sealed 后私有 oracle 绑定 public canonical hash 并生成 salted commitment。

P5N 已把 reorder oracle 细化为 Commutes/Noncommutes/Unknown、proof/witness obligation、primary/reviewer/adjudicator、oracle commitment 与 prediction seal；真实 annotators/custodian 尚未到位，因此 F2 仍未 PASS。

### Gate F3：真实 backend integration

cedar 已完成固定 source/API、runtime 数据路径和 plan-level constraint consumption，并用真实执行复现/修复 reorder 反例；P5L deterministic chain 与 P5M RandomCrop chain 均已消费 locally replayed V2 receipts，后者同时保持 output/exception/RNG post-state。故 F3 的“只展示 JSON”和单一 deterministic chain 障碍已部分解除。剩余要求是：独立真实算子 oracle、实际 cache 执行、训练 workload throughput/cost/model metric，以及至少一个非 cedar backend。完成前 F3 仍不是 PASS。

### Gate F4：one-shot final

完整 freeze 后只跑一次预测；揭示 oracle 后按固定顺序报告：unsafe false accepts、Unknown/Unsupported、coverage/recall、reason accuracy、benefit、adapter burden。任何 unsafe FA 都使当前系统版本 no-go。

## 论文大纲 v2

1. Introduction：现有 cedar/HyCache/Cachew 已有强 cost optimizer，但安全 randomness/dependency/online-only boundary 仍依赖用户。
2. Motivation：同一 symbol 在 sample/replay phase 不同；随机祖先污染下游 cache point；same-commit callable replacement；公开 replay serialization 不支持。
3. Contract Model：decision unit、operation context、effects、Unknown、rewrite-specific obligations。
4. Effect Recovery：EffectV7 + adapter，强调 soundy/fail-closed 而非完整 Python soundness。
5. Contract Carrying and Invalidation：SourceIndexV1、configuration/input/source digests、deployment/hot sentinel。
6. Rewrite-Specific Capabilities：ReplayCapabilityV1、ReorderCapabilityV0、cache-specific obligations；以 P5F 说明不可互相泛化。
7. Optimizer Constraint Compiler：cedar/HyCache/Cachew hints、祖先 effect closure、pairwise-complete reorder regions、cost/control-plane separation。
8. Evaluation：RQ1 safety/coverage；RQ2 invalidation；RQ3 replay capability；RQ4 reorder capability；RQ5 backend benefit；RQ6 adapter burden；强 greybox/manual/oracle baselines。
9. Related Work：cedar、HyCache、Cachew、Pecan、LAMBDA、HELIX/SystemDS/mlinspect。
10. Limitations：adapter cost、native/descriptor/TOCTOU/ABI、独立性、非形式 soundness、rewrite-specific scope。

## 若现在就写论文，是什么程度

现在足够写出更扎实的完整系统设计稿、技术报告或 workshop submission：不仅有 API mock，还已有固定真实 backend、负例执行和 fail-closed repair。P5F 是很有价值的研究结果，因为它迫使系统从“通用 purity”转为 rewrite-specific proof obligations。但 full systems paper 的核心 Results 表仍缺最重要的一列：独立新语料的一次性安全性、capability coverage、真实 backend benefit 和 prospective burden。继续在 synthetic receipt 上加功能不会补上这列；只有 F1–F4 能提升论文等级。
