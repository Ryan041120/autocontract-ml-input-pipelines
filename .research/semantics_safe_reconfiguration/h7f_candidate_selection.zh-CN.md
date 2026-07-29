# H7F 候选选择记录（冻结前）

日期：2026-07-29

## 目标

检验 EffectV5 的“状态角色 × 运行模式”抽象能否迁移到一个独立实现的视觉增强框架，避免仅在 TorchIO / audiomentations 的设计家族内成立。

## 候选比较

- `imgaug 0.4.0`：独立视觉框架；每个 augmenter 持有 RNG，并提供 deterministic 模式；同时具备普通算子、组合算子与用户回调算子。它直接挑战 V5 的模式守卫和委托状态变更检测。
- `tsaug`：跨到时间序列且有组合、概率和重复运算符，但主要挑战 cardinality/composition，对本轮刚加入的模式敏感状态区分不够强。
- `torch-audiomentations`：有 freeze/unfreeze 及 per-batch/per-example/per-channel 模式，语义挑战很强；但官方明确说明它受 audiomentations 启发，与 H7E 的实现谱系不够独立，暂留作后续 H7G。
- `nlpaug`：跨到 NLP，但大量算子委托外部模型/资源，首轮结果容易被外部效应主导，难以单独归因于模式敏感状态。

## 选择

选择 `aleju/imgaug` tag `0.4.0`。该 annotated tag 对象为
`279d48a440f7de03f6a58c14ab4102d2996648ae`，实际 checkout commit 为
`14b85e2209de0107c250e4d9dd6507dec1eae826`。

## 为什么这是有效的新证据

`imgaug` 的 deterministic 模式不是“完全不采样”，而是每个 batch 从相同 RNG 状态开始，从而跨 batch 重放同样的随机选择。因而：

1. RNG 是可重放执行状态，不能被粗暴归类为任意持久写；
2. RNG 的 advance/derive 是经由对象方法发生的委托变更，而不一定表现为 `self.x = ...`；
3. deterministic 标志决定调用前是否复制 RNG，因此安全判断必须携带模式前提；
4. 组合器和用户回调仍应保守拒绝，防止“识别到 RNG”掩盖原有风险。

## 适配器校准单元

- 预期 admit：`Identity`, `Fliplr`, `Add`, `GaussianBlur`。
- 预期 reject / child：`Sequential`, `Sometimes`。
- 预期 reject / user callable：`Lambda`。
- 预期 reject / external effect：`SaveDebugImageEveryNBatches`。

上述八个单元只用于适配器校准，不计入 H7F 正式结果。正式 holdout 将从
官方文档中另选未用于校准的 public symbols；其标签和阈值必须在运行
EffectV5 之前写入 preregistration 并冻结，正式运行后不再修改判据。
