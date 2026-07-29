# H7E 候选框架选择记录

更新日期：2026-07-28

## 选择

H7E 选择 `iver56/audiomentations` v0.43.1，commit
`19609e6d6624ef9e4933412ccda78fb6221f77e1`。

原因：

- 此前未进入 AutoContract 的开发、校准或 blind corpus；
- 从视觉和医学影像切换到 CPU/NumPy 音频 waveform，提供跨数据域证据；
- 公开文档列出稳定 top-level API、输入输出与 source module；
- 具有一对一变换、组合器、用户 callable、外部文件 operand 和参数 replay state；
- 纯 Python 显式导出模式可由 symbol-origin sealer 审计。

## 排除的候选

- torchvision：早期原型和 microbenchmark 已大量使用，不能再算独立 holdout；
- MONAI、MMDetection、DALI：已进入 H6/H7 corpus；
- Albumentations、Kornia、Ultralytics、Detectron2：源码已在 H6 开发或复盘中暴露；
- TorchGeo、TorchIO：分别用于 H7D 和 H7C；
- Keras/KerasCV：跨 backend 和动态 layer registration 会把 symbol binding 与 backend semantics
  同时引入，当前无法区分失败来源；
- AugLy：多模态覆盖有吸引力，但项目 API 与依赖面更大，不如 audiomentations 适合先隔离
  replay state 与 external operand 两个假设。

## 核心压力点

公开文档说明，每次调用后 transform 会保存 chosen `parameters`，并可通过 `freeze_parameters()` 将这些参数
用于后续输入。因此“execution state write”至少存在两种语义：

1. 默认 unfrozen 模式中的 last-call metadata；
2. frozen 模式中的 future-output control state。

H7E 不在看到源码前升级 schema，而是固定默认/unfrozen evaluation context，测试 EffectV4 是否会安全但
过度保守。若 ordinary transforms 因状态写入被大量拒绝，下一版候选字段应是配置依赖的 state role/guard，
而不是把所有 execution state write 直接视为同一种危险。

## 正式与非正式指标

正式 gate 使用 binding integrity、unsafe false accept、safe recall、coarse reason accuracy 和 resolved
coverage。fine-grained subtype、parameter replay state role、extent/layout effect 只作诊断，避免再次让
解释粒度掩盖核心安全判断。

### 冻结前协议修订

在 symbol binding 完成后、adapter 冻结和 operator body 查看前，发现 `resolved coverage` 与预期的
fail-closed 单元存在逻辑冲突：`Lambda`/`Compose` 的正确结果本来就是 unresolved child/callable effect。
因此在 `2026-07-28T23:51:26.0951191+08:00` 将该指标更名为 `classified coverage`：完整 effect 或明确的
安全拒绝类别都计入，generic unknown 不计入。其余样本、oracle 和阈值不变。
