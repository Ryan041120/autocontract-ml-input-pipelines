# P5N reorder-final 独立评测交接：复盘

日期：2026-07-30
状态：administrative readiness 30/30 PASS；真实 independent evidence 仍为 NO-GO

## 1. 目标与范围

P5M 之后，继续在 P5K 已知语料上扩 lemma 已不能补足论文最关键的独立性缺口。P5N 不选择真实 pair、不制作真实标签，也不运行 final prediction；它把独立 selector、双人 oracle、oracle custodian、analyzer operator 和 evaluator 的可见性与交接顺序做成机器可验证协议。

P5N 是 final-blind v2 的 reorder 专用子协议。它复用相同的 canonical JSON、salted commitment、artifact freeze 和 seal-before-reveal 原则，但不把 ReplayCapability schema 错误泛化到 reorder。

## 2. 三套分离 artifact

### Public manifest

包含 20–40 个精确 pair statement，至少 3 个框架、2 个领域；每个 statement 绑定 release/commit/source tree、两侧 type/config/SourceIndex、input domain、RNG assignment、state reset、exact output/exception/RNG comparison 和 source anchors。Public pair 禁止出现 label、commutes/noncommutes、counterexample、prediction 或 receipt。

### Private oracle

primary 与 reviewer 独立给 `Commutes / Noncommutes / Unknown`，不一致必须由 adjudicator 处理。`Commutes` 必须有 formal/manual source proof 和 premises；`Noncommutes` 必须有一个输入/seed/双结果/reproduction-command digest 绑定的 witness；`Unknown` 必须保持 unresolved，有限差分阴性不能升级为 Commutes。

### Sealed prediction

分析器只输出 `Supported / Unknown / Unsupported`、assurance、reason、receipt digest、generation time 和 prospective adapter minutes。Prediction schema 禁止 oracle label/witness 字段，但允许并要求严格 Supported 携带 receipt digest。

## 3. 密封与评分顺序

1. selector seal public manifest；
2. oracle custodian 将带 32-byte salt 的 private oracle 绑定 public canonical hash，只发布 commitment；
3. public freeze 重新计算所有 analyzer artifact 文件 hash，且不包含 private oracle instance path/content；
4. analyzer 完成全部 pair prediction 并生成 prediction seal；
5. reveal 后同时验证 oracle commitment 和 prediction seal；
6. 评分首先报告 unsafe Supported，再报告 unresolved Supported、Unknown/Unsupported 分母、Commutes coverage、completion 和 burden。

冻结门槛为：unsafe Supported=0；oracle Unknown 上的 unresolved Supported=0；Commutes strict coverage≥30%；prediction completion=100%。Backend benefit 仍需另一个冻结实验，不能用 coverage 代替。

## 4. Attempt 0：泄漏扫描 false positive

第一次 self-test 在 strict prediction validation 阶段 ERROR。通用泄漏扫描器把预测 artifact 的合法字段 `receipt_sha256` 当成答案泄漏。该失败被保留为 `outputs/autocontract_p5n_reorder_final_handoff_selftest_attempt0_receipt_false_positive.json`。

修复只拆分 forbidden-key sets：public selection artifact 仍禁止 receipt/prediction；sealed analyzer prediction 允许 receipt digest，但继续禁止 oracle/label/counterexample/expected/safe/unsafe。Pair quota、角色隔离、commitment、metric gates 和 oracle semantics 均未改变。

## 5. 最终 self-test

24-pair、3-framework、2-domain synthetic administrative fixture 最终 **30/30 PASS**，覆盖：

- frozen predecessor、public/private/prediction exact schema；
- oracle commitment、prediction seal 和全部 analyzer artifacts freeze；
- freeze 排除 private oracle 路径、label 和 witness；
- public label/counterexample 泄漏；
- selector/annotator independence violation；
- pair quota、duplicate、contamination、unknown framework、placeholder source；
- public/private ID/hash 不一致和缺 unit；
- Noncommutes 缺 witness、Commutes 携带 witness、disagreement 缺 adjudicator/count 错误；
- post-commit oracle tamper 与 post-seal prediction tamper；
- prediction label leak 与缺 pair；
- synthetic unsafe Supported 令 safety gate 明确 FAIL。

Self-test PASS 只证明行政机制能拒绝这些攻击。`NovelFrame-*`、synthetic labels/predictions/burden 和得分均不构成论文证据。

## 6. 当前真实 blocker

P5N 后，reorder-final 的技术交接包已经具备；缺的不是另一轮内部代码，而是角色真正独立的人与未污染数据：

1. 独立 selector 按指南选择真实 20–40 pairs；
2. primary/reviewer/adjudicator 在看不到 analyzer outputs 的条件下制作 private oracle；
3. custodian 保管 oracle 与 salt，只交付 commitment；
4. analyzer 侧前瞻记录接入耗时并一次性预测；
5. seal 后 reveal，禁止针对同一 corpus 调规则重跑 final。

如果由项目开发者或当前对话中的 AI 自己选择、标注、预测和评分，只能叫 dry-run/held-out，不能叫 independent blind。这个边界现在由 protocol 和文档同时冻结。

## 7. 可复核产物

- selection/annotation guide：`benchmark/final_v2/reorder_pair_selection_guide.zh-CN.md`
- protocol：`benchmark/final_v2/p5n_reorder_final_handoff_protocol.json`
- public/private/prediction schemas 与 templates：`benchmark/final_v2/reorder_*`
- manager：`experiments/autocontract_p5n_reorder_final_handoff.py`
- attempt 0：`outputs/autocontract_p5n_reorder_final_handoff_selftest_attempt0_receipt_false_positive.json`
- final self-test：`outputs/autocontract_p5n_reorder_final_handoff_selftest.json`
- final result SHA-256：`e48438d1ad1802781b184b6120eec97d6656e22940f9d919b5bf0c774754202f`
