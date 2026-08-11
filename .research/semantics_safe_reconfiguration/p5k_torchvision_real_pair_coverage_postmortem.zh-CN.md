# P5K：torchvision 真实算子对证据与 proof coverage 审计

日期：2026-07-30

## 结论

P5K 在固定 Python 3.11.9、PyTorch 2.0.1+cpu、torchvision 0.15.2+cpu 环境中审计 28 个真实/真实相邻 pair，结果 11/11 checks PASS。该语料全部来自已污染的 torchvision calibration 范围，不能称 independent oracle 或 final blind。

最重要的结果是负结论：ReorderCapabilityV1 的整数仿射 producer 对 torchvision transform object 的 strict Supported coverage 为 **0/28**。P5I/P5J 解决了 receipt trust、篡改和单调性，但没有解决真实算子的证明覆盖率。若论文声称“已经自动证明真实 ML preprocessing reorder”，当前证据会直接否定该表述。

## 固定范围

- torchvision v2 Python source tree：24 个 `.py` 文件，规范化 tree SHA-256 为 `e63dbf5655cc72e815ffcc9fe8a50fcbc359b103ef24ca25a5600c1ecefb91a1`；
- 输入：CPU、CHW、3 channels、float32、值域 `[0,1]`、高度 31–35、宽度 37–43；
- 主 operation context：adjacent reorder + global sequential RNG；
- operator-keyed RNG 仅作对照，不与主 context 混合；
- floating output tolerance `2e-5`，shape/dtype exact；一侧异常构成 counterexample；
- 16 个旧 feasibility pairs 加 12 个 P5K extension pairs，共 28；旧标签只用于已知语料复现诊断。

## 结果

全局 RNG：

- 14/28 找到具体 counterexample，证据等级为 `Noncommutes(counterexample)`；
- 14/28 在 24 次固定探针中未找到反例，只能是 `Unknown(no_counterexample)`；
- strict Supported 为 0/28，有限差分阴性结果没有被升级成证明。

operator-keyed RNG：

- 11/28 找到 counterexample；
- 17/28 为 Unknown/no-counterexample；
- `gaussian_blur↔random_hflip`、`random_hflip↔random_vflip`、`color_jitter↔random_hflip` 三对与 global RNG 结论不同。这直接说明 commutativity receipt 必须绑定 RNG assignment semantics，不能只绑定 operator names。

旧 16 对在当前版本替代 statement 下复现 16/16：旧 10 个 Noncommutes 均找到反例，旧 6 个 Commutes 均未找到反例。但后者仍只称 Unknown；旧人工标签不是本轮独立 oracle。

12 个新 pair 中，`center_crop↔random_hflip`、`center_crop↔random_vflip`、`gaussian_blur↔center_crop`、`random_erasing↔random_hflip` 找到反例；其余 8 对保持 Unknown。

## 两个额外发现

第一，旧 feasibility 使用 `ToDtype(torch.uint8, scale=True)`，在冻结 torchvision 0.15.2 上构造即抛 `TypeError`。P5K 先保留该版本漂移，再为当前 `ToDtype(torch.uint8)` 建立新的明确 statement；没有静默把旧结果当成同一 API。

第二，SourceIndexV1 在显式 `forward/_transform/_get_params` slots 下对 12/12 torchvision operators 都生成 non-empty Supported index；但对 `StatefulOffset` 这类无这些 slots 的对象返回 `status=Supported, entries=[]`。P5K consumer 额外执行 non-empty invariant，把它改为 Unknown。历史 SourceIndexV1 不回写，但今后任何 proof consumer 都必须要求声明的 required slots 非空，不能把空索引当成功。

## 为什么不能直接扩展 V1 AST

torchvision transform 是对象，其语义分散在 inherited `forward`、`_get_params`、`_transform` 和 functional dispatch；整数表达式解析器对 13/13 operator objects 都返回 `source_unavailable_or_invalid`。简单允许 `Call` 节点只会把未知库函数伪装成已证明语义，重新引入 P5H 类信任问题。

更可行的 P5L 路线是本地可重放的 relation algebra：

1. `identity` lemma；
2. `pointwise_channel_affine` 与 `spatial_index_map/selection` 的交换律；
3. `pointwise_channel_linear` 与 spatial map/selection 的交换律；
4. 每个 operator adapter 必须重放 type、配置、required slots、SourceIndexV1、framework/version/source-tree 与 RNG context；
5. resize/interpolation、blur/boundary、dtype/rounding 暂不纳入第一版，因为它们需要数值误差、边界和 overflow 证明；
6. differential counterexample 仍可否定 lemma application，但无反例不能签发 Supported。

按 P5K 的 Unknown 集估算，这个最小 algebra 最多有望覆盖 identity 三对、Normalize 与 crop/flip 四对、Grayscale 与 crop/flip 三对，理论上约 10/14 Unknown；这是下一轮要预注册验证的 coverage 假设，不是本轮结果。
