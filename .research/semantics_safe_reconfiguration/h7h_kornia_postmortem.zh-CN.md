# H7H Kornia / EffectV7 复盘

日期：2026-07-29

## 1. 实验设置

H7H 使用 Kornia v0.8.3，tag checkout commit 为 `d6bb4bf0d8a043c2bb8cef0c346a1b006d100930`。选择它的原因是 Kornia API 显式区分两条路径：

```text
params=None       -> 生成新的 augmentation parameters
params=recorded   -> 复用已记录 parameters
```

这提供了独立于 Albumentations `replay_mode` 的 phase contrast。正式上下文将 compatible parameter record 作为前置条件；不把 seed 相同等同于逐样本参数重放。

校准符号与正式符号完全不相交。Kornia 顶层 API 经 star re-export，现有 conservative symbol sealer 会返回 unresolved；因此冻结协议改用相同算子的完整 defining-module symbol，确保 definition、source hash 和 commit 可以审计。该调整发生在冻结前，第一次失败校准未进入正式 gate。

## 2. 冻结前校准

- EffectV7 completed-corpus calibration：36/36 decisions，36/36 reasons。
- Kornia adapter calibration：9/9 decisions，9/9 reasons。
- 四组 calibration phase contrast：100%。
- ImageSequential child-delegation 反例正确拒绝。

随后冻结 EffectV7、symbol sealer、adapter、adapter manifest、protocol、symbol manifest、calibration summary、Kornia commit 与所有正式定义文件 hash。

## 3. 一次性正式结果

| 指标 | 结果 |
|---|---:|
| Binding integrity | 5/5 = 100% |
| Operation decisions | 9/9 |
| Known-unsafe false accepts | 0 |
| Supported-safe recall | 4/4 = 100% |
| Coarse-reason accuracy | 9/9 = 100% |
| Classified coverage | 9/9 = 100% |
| Phase-contrast accuracy | 4/4 = 100% |
| H7H blind gate | **PASS** |

RandomVerticalFlip、RandomPosterize、RandomSolarize 和 RandomMotionBlur 均表现出相同的正确翻转：显式参数记录下 `forward_parameters` 不可达，接纳；`params=None` 下采样 helper 可达，以 `reachable_sampling_rng` 拒绝。AugmentationSequential 即使拿到显式 params，仍因未合成 child contracts 而以 `unresolved_child_effect` 拒绝。

## 4. 科学解释

H7H 首次为以下更窄、也更可信的主张提供独立 holdout 支持：

> adapter-assisted analyzer 可以利用框架公开的 replay/parameter interface，生成 mode/phase-sensitive rewrite certificate，并在同一算子的 sampling 与 replay operation 之间做出不同判定。

它不证明通用 Python path-sensitive analysis 已解决，也不证明任意 `params` 都安全。接纳结论严格依赖 compatible, complete, same-lineage parameter record 的协议前提。

## 5. 下一步最有价值的优化

下一阶段不应继续堆叠更多单算子。优先级应为：

1. **Parameter-record lineage certificate**：记录 producer operator/version、input schema、sample identity 和 parameter digest，防止拿错或过期参数仍满足 `params_provided`。
2. **Child-contract composition**：将容器参数列表与 child symbol、顺序、phase 和 contract 一一对应，争取安全接纳 AugmentationSequential，而不是永久 fail closed。
3. **真实 rewrite 验证**：在 Kornia tensor pipeline 中执行“预采样参数—跨 worker/设备边界应用”的实际优化，比较 trace、RNG state、梯度与吞吐。
4. **MRO/dispatch 完整性**：将当前源码级 DFS 近似替换为可审计的 C3 resolution，并显式处理 descriptor、decorator 和 dynamic module dispatch。

当前总体判断从“EffectV7 尚待实现”推进为：**mode/phase-sensitive IR 获得首个独立 blind PASS；项目仍是 adapter-assisted conditional go。**
