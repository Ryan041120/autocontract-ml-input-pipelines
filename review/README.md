# AutoContract anonymous review bundle

> 历史评审材料：本说明主要对应 H8C / final-v1；另有 P5N 提示与打包工具。最新 P5V 状态见 [CURRENT_STATE](../CURRENT_STATE.md)。这些材料不代表当前完整成果，也不表示独立最终盲测已经完成。
>
> 2026-09-09 整理后，P5N 打包脚本读取保存的历史 README，避免混入新的项目入口。既有输出包保持原样；此轮未重新打包。`SHA256SUMS.json` 仅在实际封装时生成，本目录当前没有该文件。

This bundle is a sanitized snapshot for a submission-readiness review of:

> Semantics-Aware and Reconfiguration-Safe Optimization for ML Input Pipelines

It contains the current claims, research notes, benchmark protocols, analyzer
and runtime source, and text/CSV/JSON experiment outputs. It intentionally
excludes Git history, credentials, databases, third-party source snapshots,
large plots, caches, and any future private final-benchmark oracle.

The generated single-file Markdown packet is a smaller narrative subset. It
does not embed all Python source or every CSV. A reviewer must distinguish
"not embedded in the packet" from "absent from the repository" and should ask
for the named artifact before concluding that it does not exist.

## Suggested reading order

1. `README.md`
2. `.research/semantics_safe_reconfiguration/paper_claim_freeze_v0.zh-CN.md`
3. `.research/semantics_safe_reconfiguration/optimizer_integration_spec_v0.zh-CN.md`
4. `.research/semantics_safe_reconfiguration/effect_v7_spec.zh-CN.md`
5. `.research/semantics_safe_reconfiguration/h8a_effect_v7_optimizer_postmortem.zh-CN.md`
6. `.research/semantics_safe_reconfiguration/h8b_cache_prefix_postmortem.zh-CN.md`
7. `.research/semantics_safe_reconfiguration/h8c_multiworkload_cache_postmortem.zh-CN.md`
8. `benchmark/autocontract_h8c_cache_protocol.json`
9. `outputs/autocontract_h8c_multiworkload_cache.md`
10. `outputs/autocontract_evidence_inventory_v0.md`
11. `benchmark/final_v1/threat_model.zh-CN.md`
12. `.research/semantics_safe_reconfiguration/literature_matrix.md`
13. Relevant files in `experiments/` and their corresponding raw outputs

## Evidence boundary

- H8C is a registered internal calibration over five CV/audio workloads.
- The source and oracle in H8C were not independently blinded.
- The final independent 50-80-unit benchmark has not been run.
- The final-v1 administrative self-test tests protocol guardrails only; it is
  not model-effectiveness evidence.
- H7L-H7M are distributed-systems extensions, not the current central claim.

Start with `review/AI_REVIEW_PROMPT.zh-CN.md`. Verify any claimed result against
the included raw artifact, and report missing evidence rather than inferring it.
`review/SHA256SUMS.json` records every packaged file after staging.
