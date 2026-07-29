# H7H 候选冻结前选择：Kornia v0.8.3

日期：2026-07-29

H7G 暴露的关键缺口不是某个 Albumentations 专用字段，而是效应是否在目标配置和阶段中可达。H7H 因而选择 Kornia：其公开 augmentation API 将 `params=None` 定义为生成新参数，将显式 `params` 定义为复用参数；官方容器文档还展示了以 `_params` 重放并得到相同输出。

检验的核心对照是同一公开算子的两个 operation：

```text
params=None       -> sample_apply -> sampling/RNG path reachable -> reject
params=recorded   -> replay_apply -> sampling branch pruned       -> admit
```

另加入 `AugmentationSequential(params=recorded)` 作为 child-delegation 反例；在没有逐 child contract 时继续 fail closed。

选择 v0.8.3 tag，checkout commit 为 `d6bb4bf0d8a043c2bb8cef0c346a1b006d100930`。适配器校准符号为 RandomHorizontalFlip、RandomGaussianBlur、ColorJiggle、RandomAffine 和 ImageSequential；正式符号为 RandomVerticalFlip、RandomPosterize、RandomSolarize、RandomMotionBlur 和 AugmentationSequential，两集合不相交。Kornia 顶层 API 经过 star re-export，保守 symbol sealer 不接受该绑定，因此协议使用同一算子的完整 defining-module 符号来保证源文件哈希可审计。共同基类可以用于适配器校准，但冻结前不对正式类方法体做 effect analysis。
