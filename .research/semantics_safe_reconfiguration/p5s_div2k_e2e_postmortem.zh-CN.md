# P5S：DIV2K 流式端到端确认实验复盘

## 结论先行

P5S 在固定的 Cedar / PyTorch CPU 环境、两个预先划分的 DIV2K blind folds 上，验证了一个很窄的机制：经 V2 receipt 授权后，Cedar 可仅交换 `Normalize` 与仍保持随机的 `RandomCrop`，同时保持受检张量、RNG、loss、logits、gradients 和 model state 的逐项一致。两 fold 的单独中位数均低于 0.95，但预注册的 30-pair bootstrap 上界为 **0.952507**，未严格低于 0.95。因此正式结论是 **No-Go for an end-to-end benefit claim**；机制成功不等于超过 benefit threshold。

所有正式 JSON protocol、evidence 与 result 工件均标记 `scientific_evidence=false`。这是一项单机、固定版本、warm-cache CPU 实验，不是外部复现，也不能外推到任意模型、GPU、冷 I/O 或任意视觉变换。

## 研究问题与冻结 workload

研究问题是：在真实 PNG 解码、Cedar 执行、MobileNet 训练步骤都计入计时的条件下，一个由可验证 relation receipt 授权的、局部的 `Normalize`/`RandomCrop` 交换，能否在不改变可观察语义的前提下带来至少 5% 的稳定端到端收益？

每个 arm 的精确路径为：

```text
fixed DIV2K file paths
  -> PNG open/decode (RGB uint8 CHW)
  -> uint8 -> float32 / 255
  -> runtime domain guard
  -> Normalize -> RandomCrop                 (baseline)
     或 RandomCrop -> Normalize              (authorized)
  -> Cedar optimize/load_from_plan
  -> stack 32 tensors [3,224,224]
  -> MobileNetV3-small forward
  -> cross-entropy with stem-mod-10 pseudo labels
  -> backward -> SGD.step
```

模型构建、profile/optimizer planning、receipt verification 和 cache warming 在 primary timer 外；计时从 `load_from_plan` 到最后一个 `optimizer.step`。每 fold 一个 fresh CLI process、15 个 block、奇数 AB / 偶数 BA，共 30 个 paired ratios；主要指标始终是 `authorized / baseline` wall-time ratio。

## 数据、fold 与运行边界

- 官方数据：DIV2K validation HR；manifest 记录的 archive SHA-256 为 `20dd31fd84d777bc1cf5d6b7654a3f569c0aec74458ae094122ad1d0489900fc`。
- calibration：0801--0810，仅用于 profile/smoke/control-selftest。
- Fold A：0811--0842；Fold B：0843--0874；reserved：0875--0900，不触碰。
- runtime：Python 3.11.9、torch 2.0.1+cpu、torchvision 0.15.2+cpu、torch threads=1、clean Cedar commit `f062305fcdab196e871c5d09b4c82ab788b4da79`。
- warm-cache 仅支持 warm-cache 解释；不能把结果叙述成冷存储或数据下载收益。

## incident、修复与重新冻结链

首次正式 Fold A 进程及随后用于复现异常的诊断进程，共发生两次同源的 deterministic implementation failure。`confirm()` 在 block 1 后把语义 operator mapping 覆写为该 block 的布尔语义结果。两次失败都处于可评价 confirm 输出形成之前：没有输出文件、没有 ratio 被查看或持久化，B 未启动。因为 PID 及 UTC start/end 没有被捕获，incident 记录明确写为 **“not captured”**，不补造元数据。

修复将 mapping、block boolean 和全程 accumulator 分离为 `semantic_ops`、`block_semantic_pass` 和 `all_semantic_pass`，并在每个 block 前检查 mapping 仍为 dict。随后执行：15-block synthetic control-flow（30 fake calls，精确 AB/BA）与 calibration-only 两 block（四个真实 arms）回归。旧 freeze 与 launcher 失效，新的链条是：修正 runner → profile → smoke → control-selftest → amendment-bound freeze → review-approved launcher → fresh A/B restart。旧失败 process 不进入 aggregate。

incident amendment：`035f9e2a6bce4a4cd3248e6bc401e6b6c077911542af8023572c58eb05724fcd`。

## 正式结果与 No-Go

| 预注册量 | 结果 |
|---|---:|
| Fold A 中位数 | 0.9357463 |
| Fold B 中位数 | 0.9381244 |
| 30-pair log bootstrap 95% CI | [-0.0984924, -0.0486576] |
| ratio scale 95% CI | [0.9062026, **0.9525073**] |
| Go 条件 | 两 fold median <0.95 **且** ratio CI 上界 <0.95 |
| 判定 | **No-Go**：0.9525073 ≥ 0.95 |

两个 fold median 都通过，不足以推翻 bootstrap gate。因为阈值、30 个 ratio、10,000 draws、seed=20260807 和 percentile index 在运行前冻结，不能在结果不理想后改用 pooled median、几何均值或删去极端 block 来替代主要检验。

## 语义门与独立审计

正式 runs 通过了固定候选数（baseline=1，authorized=2）、固定前缀、唯一可移动 pair、`RandomCrop(random=true)`、32 次 open/decode、32 个 `[3,224,224] float32` tensor digest、Python/NumPy/torch RNG digest、finite loss/logits/gradients/model state、AB/BA 顺序和跨 arm exact equality。独立审计复核为 **279/279**；这是一项保存工件的独立审计结论，不等于另一台机器或另一研究组的外部复现。

修复后的 control-selftest 为 5/5 PASS，aggregate parser/adversarial selftest 为 36/36 PASS。它们说明 receipt、冻结锚、identity、有限值、digest、order 和类型门是 fail-closed 的；它们不构成性能证据。

## 预先区分的 exploratory 描述

以下仅作描述，不能替代 primary Go gate：

- pooled median=0.9369354；pooled geometric mean=0.9321859；30 个 ratio 中 22 个 <0.95。
- Fold A geometric mean=0.9453892；Fold B geometric mean=0.9191670。
- AB（baseline→authorized）16 个 pair：median=0.9338108、geomean=0.9211772；BA（authorized→baseline）14 个 pair：median=0.9407400、geomean=0.9449284。这提示顺序/运行状态可能参与波动，但不是 post-hoc 调整检验的理由。
- B11 的 ratio=0.6750105，B14 的 ratio=1.0341467。二者都保留，不删 outlier；其 arm 内 model-state digest 相同，语义 gate 仍通过。它们记录的是 block 内及跨 block 的运行状态变化线索，而不是可据以重算主要效应的排除规则。

## 哈希与工件定位

| 工件 | SHA-256 |
|---|---|
| runner | `5453de6a8b5c97e6b30999aabbc3a6030b3c586cc6e96b013f10b0ccc501d7cc` |
| protocol | `d78c1a6c6e662b374dea5624fe2804baeac50564f2505c919d57a26e33e6a77a` |
| execution freeze | `be805691ba027f24d4b1681cb1f8a94635bb365baac9a645dd6dc6481d22b0da` |
| frozen launcher | `913f2e0967957a557dbe19c3d8afc95d2d94c3beca106c4aabf128aa6e69a36a` |
| confirm A / B | `b3e831aee5e659854d32171237427d6c5d6b341971ced117e1c8f5f9d1149362` / `b7d7312581bbf90dca23ee9f1f1b82218f3938bb29ff5b444e3242d529f46475` |
| aggregate | `9983402db0e8bfa00677a1ac00aa75e9e959dcaf2b8714ea3acc2d4b8a76013b` |
| control-selftest | `2b1d67beab25ac5a9477de1fc9adc46baff083635c4d3138adbb4ed4eccf0cbb` |
| aggregate-selftest | `4d6f48876723c3f99a83bde9eddad622b997ff123d63cd368a084b58cdb3fbdc` |

## 可以与不可以声称什么

支持的说法：在本 pinned CPU runtime 和两 fixed DIV2K folds 上，receipt-authorized local reorder 通过了本 protocol 的语义、provenance、identity 与 adversarial validation gates；其点估计大多朝加速方向，但未满足预注册 benefit threshold。

不支持的说法：已经证明真实端到端收益；对所有 vision pipelines、任意 transform、cold I/O、GPU 或其他硬件的收益；外部可复现性；或者由 mechanism success 推出 systems benefit。P5S 的正确论文定位是严格的负结果：**semantic authorization can be real while a practically meaningful end-to-end benefit remains unestablished.**

## P5T：预注册 benefit-surface study

P5T 应是新的、单独预注册的 benefit-surface study，而非在 P5S 结果后扩张样本或移动门槛。其 workload axes 应事先限定为：

1. model-compute balance（轻/中/重训练计算）；
2. crop/transform intensity 与可授权 pair 的数量/位置；
3. cold 与 warm I/O 的明确分层；
4. 在资源允许时，单列 GPU backend，而不是把 CPU 结果外推为 GPU。

每个 axis、硬件/软件版本、计时边界、样本/重复数、语义门和分析规则应在运行前冻结，并报告所有 strata，而非只报告最好的一格。P5T 没有承诺会得到正结果；其目标是识别 benefit 何时存在、何时不存在，以及机制收益被 I/O 或模型计算稀释的边界。
