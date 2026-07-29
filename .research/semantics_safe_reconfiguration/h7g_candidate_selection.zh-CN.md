# H7G 候选选择记录（冻结前）

日期：2026-07-29

## 目标

在未参与 EffectV6 开发的新框架上，同时检验：

1. 存储 RNG 对象的方法调用能否识别为 `delegated_mutation`；
2. module-bound 与 public-input callable 能否分开；
3. seeded sequence 与 per-sample replay 是否会被错误等同；
4. child operator 与动态外部 operand 是否继续 fail-closed。

## 候选比较

- **Albumentations 2.0.8**：独立实现的 CV augmentation 框架；Compose 拥有内部 Python/NumPy RNG，ReplayCompose 记录具体参数；同时有普通 transform、组合器、Lambda 和 `read_fn` 类入口。它对 V6 三项增量均有直接挑战。
- **Kornia**：PyTorch tensor-native，`params` 重放和 `AugmentationSequential` 很适合测试模式义务与 child composition；但公开 API 中缺少同样清晰的 user-callable / module-bound 对照，更适合作为后续参数重放专项。
- **tsaug**：跨时间序列且组合/cardinality 语义清晰，但 callable provenance 与具名 replay mode 的挑战较弱。
- **torch-audiomentations**：freeze/mode 语义强，但受 audiomentations 启发，与 H7E 的实现谱系不独立。

## 选择

选择已归档、MIT 许可的 `albumentations-team/albumentations` tag `2.0.8`，tag/commit
`4d2cf04b6635663275a747333754410ef255e54c`。归档状态不影响固定源码 holdout，反而消除了上游漂移；
结论不外推到后继 AlbumentationsX。

## 关键语义边界

- `Compose(seed=...)` 只保证在相同结构、输入顺序和调用顺序下复现随机序列；同一实例连续调用仍推进状态。
- `ReplayCompose` 才记录一次调用的具体随机决策，并允许对兼容输入重放。
- 因此 H7G 不会把“seeded”直接当作 rewrite-safe mode。普通随机 transform 只有在显式 replay-parameter
  context 下才可能接纳；默认 sequence mode 下应带未满足义务或保守拒绝。

## 污染控制

- 先选一组只用于 adapter calibration 的 public symbols；
- H7G 正式 symbols 与 calibration 完全不相交；
- seal 阶段只解析顶层定义/re-export 与文件哈希，不运行 EffectV6；
- 正式 EffectV6 只运行一次。

正式单元、oracle 与阈值将在 adapter 校准完成后、打开正式方法体之前写入 protocol 并冻结。
