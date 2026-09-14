# AutoContract P5O 独立 pair 工作表（final-v3 草案）

> 本表只能在独立 selector 入场后用于正式语料；当前 6–8 pair dry-run 必须标记为 `development_dry_run`，不得进入论文 Results。

## A. Selector 公开字段

1. `pair_id`、framework/release/commit/source tree。
2. 左右算子的 exact type、configuration、SourceIndex digest。
3. `pair_family`：identity、pointwise/spatial、random context、boundary/definedness、rounding/precision、stateful/external 或 other nontrivial。
4. 输入域及 premise profile：哪些字段是 lemma 真正需要在运行时成立的，哪些只是声明绑定。
5. assurance plan：registration、batch-boundary、per-sample 或 external attestation。
6. 左右 native boundary：pure Python、known versioned native、opaque native 或 externally attested native。
7. operation context：RNG assignment、state reset、adjacent/permutation scope。
8. observational relation：output、definedness、exception、RNG post-state；若使用 tolerance，必须提供预先冻结的 artifact。
9. 只写 label-free inclusion reason；不得写“看起来可交换”等答案暗示。

## B. Annotator 私有字段

1. primary/reviewer 各自标签：Commutes、Noncommutes、Unknown。
2. 分别判断 output relation、definedness、exception、RNG post-state。
3. Commutes：记录完整 premises 与 formal/manual source proof anchor。
4. Noncommutes：记录 mismatch dimension、seed、input/outcome/command digests。
5. Unknown：明确未解决的 observation 或 native/domain premise。
6. 分歧必须由 adjudicator 处理；完成后再由 custodian seal commitment。

## C. Analyzer 前瞻负担

逐 pair 记录 source inspection、adapter、guard implementation、generation/verification time、semantic-rule SLOC。Opaque native 没有 external attestation 时必须输出 Unknown；runtime premise violation 时不得输出 Supported。

## D. Reveal 报告顺序

1. Unsafe Supported 与 unresolved Supported。
2. completion 与 Unknown/Unsupported 分母。
3. family/RNG/framework 分层 coverage 和 Wilson interval。
4. non-identity Supported 与 Supported framework count。
5. domain guard 检出率、overhead 与 native-boundary breakdown。
6. prospective burden。
7. 独立的 cedar workload benefit；不得用 benefit 抵消 safety failure。
