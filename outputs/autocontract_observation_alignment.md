# AutoContract：同版本观察关系诊断

开发诊断；非独立 benchmark，不是性能证据，不授予执行权限。

使用未改写的 V2 producer/verifier 与现有 Tensor observer。

| 已知操作对 | V2 receipt 重放 | 逻辑字节 | RNG 后状态 | 严格观察 | view(-1) 后续 |
|---|---|---|---|---|---|
| normalize_center_crop | True | 相同 | 相同 | 不同 | 不同 |
| normalize_random_hflip | True | 相同 | 相同 | 相同 | 相同 |
| identity_center_crop | True | 相同 | 相同 | 相同 | 相同 |

原序 Normalize/CenterCrop：stride=[16, 4, 1]；storage_offset=5。

交换 Normalize/CenterCrop：stride=[4, 2, 1]；storage_offset=0。

该 witness 排除了将现有 receipt 直接解释为严格布局／任意下游上下文等价。
它不否定此样本的数值/RNG 相等，也不回写历史结果；旧声明若包含任意上下文则需收窄。
不能因为两个控制样本未发现差异就签发新的严格证明。

诊断核对：10/10；受保护文件内容未变化。

原始输入、完整 receipt、逐项观察、源文件 hashes 见同名 JSON。
