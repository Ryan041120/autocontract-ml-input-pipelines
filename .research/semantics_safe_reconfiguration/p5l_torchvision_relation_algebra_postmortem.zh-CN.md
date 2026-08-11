# P5L torchvision source-bound relation algebra：复盘

日期：2026-07-30
状态：calibration PASS；不是独立 final evidence

## 1. 研究问题

P5K 已证明 restricted integer-affine verifier 在 28 个真实 torchvision v2 pair 上覆盖为 0，同时 bounded differential 的阴性结果只能是 `Unknown`。P5L 检验一个更窄的问题：不允许任意 Python `Call` AST，只为少量能人工审计的关系族建立 source/version/config/input-domain-bound lemma，能否在不接纳已知反例的前提下恢复真实 pair coverage？

预注册停止规则是：P5K 的 14 个 global-RNG `Unknown` 中 verified coverage 低于 30%，或任何 P5K counterexample 被签成 `Supported`，即停止扩展该自动 producer。

## 2. 冻结的关系代数与信任边界

V2 只实现两个 lemma：

1. `identity_composition_v0`：identity 与当前域上的 total operator 交换；
2. `pointwise_channel_map_spatial_index_v0`：逐像素 channel map 与不改变 channel 语义的空间 index map / 无 padding selection 交换。

当前识别 slice 为 torchvision v2 的 `Identity`、`Normalize(inplace=False)`、`Grayscale(num_output_channels=3)`、`CenterCrop`、无 padding 的 `RandomCrop`、`RandomHorizontalFlip`、`RandomVerticalFlip`；`Resize` 仅在 identity lemma 中作为 opaque total operator 出现。输入域固定为 finite、CPU、float32、三通道 CHW tensor 和声明的 H/W 范围。

每张 receipt 同时绑定：

- Python 3.11.9、torch 2.0.1+cpu、torchvision 0.15.2+cpu；
- torchvision v2 的 24 个 Python 文件 tree digest `e63dbf5655cc72e815ffcc9fe8a50fcbc359b103ef24ca25a5600c1ecefb91a1`；
- exact operator type、configuration 与必需 callable slots；
- SourceIndexV1 record、operation/RNG context、input domain；
- V2 verifier identity/version、dependency closure、lemma artifact 和 canonical receipt digest。

resize/interpolation 权重、blur boundary、dtype conversion/rounding、ColorJitter、RandomErasing、stateful UDF 和任意 `Call` AST 明确不在证明域内。

## 3. 结果

最终 runner 为 **11/11 PASS**：

- P5K 28 pairs 中，10 对获得 locally replayed strict `Supported`；
- 对 P5K 14 个 `Unknown` 的 verified coverage 为 **10/14 = 71.43%**；
- 全部 28 对上的 strict coverage 为 **10/28 = 35.71%**；
- 与 P5K 14 个已知 global-RNG counterexamples 的冲突为 **0**；
- identity lemma 覆盖 3 对，pointwise/spatial lemma 覆盖 7 对。

10 个 Supported 为：

- `identity-resize`、`identity-normalize`、`identity-random_crop`；
- `normalize-center_crop`、`normalize-random_hflip`、`normalize-random_vflip`、`normalize-random_crop`；
- `grayscale3-random_hflip`、`grayscale3-center_crop`、`grayscale3-random_vflip`。

仍为 Unknown 的四个 P5K 阴性 pair 为：

- `normalize-resize`；
- `resize-random_hflip`；
- `gaussian_blur-normalize`；
- `to_uint8-resize`。

前两者缺少 interpolation relation proof，后两者分别涉及 boundary semantics 和 dtype/rounding；不能从有限测试未发现反例升级为 Supported。

## 4. Fail-closed 攻击

8 类攻击全部被拒绝：lemma artifact 重哈希、verifier version 漂移、verifier closure 漂移、source binding 漂移、input-domain 漂移、operator-config 漂移、duplicate receipt 和 verifier revocation。拒绝原因分别落在 proof replay、verifier identity/closure、binding、domain/schema、duplicate/ambiguity 或 revocation gate，而不是依赖调用者自述。

公开 `reorder_capability_v2.schema.json` 只定义 transport shape；`autocontract_reorder_capability_v2.py` 才执行本地重放和 exact binding。V0 或手写 receipt 不能进入 strict V2 路径。

## 5. 真实 cedar 消费

在固定 cedar commit `f062305fcdab196e871c5d09b4c82ab788b4da79` 上，真实 torchvision 链 `[Identity, Normalize, CenterCrop]`：

- 无 receipt 时 candidate count 为 1，全部 `fix=True`；
- 三张完整 V2 receipt 后 candidate count 恢复为 6，`fix=False`；
- cedar 将路径从 `[3,2,1,0]` 改为 `[3,0,1,2]`；
- 5 个输入的 output digest 完全一致，`max_abs_delta=0.0`。

这证明固定 backend 能实际消费 V2 proof，而不是只验证 JSON；它仍是已知 deterministic chain 的机制校准，不代表随机链、训练指标或独立 workload benefit。

## 6. 科学解释与限制

P5L 通过了预注册 30% coverage gate，并保持零已知反例冲突，因此“source-bound local relation algebra 可以补足 restricted AST verifier 的部分真实 coverage”在该固定 slice 上成立。它不等于形式化证明整个 torchvision，也不支持自动推断任意库调用：这些 lemma 与 operator adapter 本身仍是受信、人工编写的语义桥。

主要限制：

- 28 pairs 是研究期间已见、已污染的 calibration corpus，没有独立双人 oracle；
- 结论只适用于固定版本、源码树、配置、输入域和 RNG context；
- 尚未系统攻击 shape/channel/dtype 边界和随机链执行；
- 没有测 proof generation/verification cost、adapter SLOC 或 prospective onboarding time；
- 没有第二个 proof producer、第二个 backend 或 end-to-end training benefit。

## 7. 下一步：P5M，而不是继续扩规则表

下一轮主线先做 relation-lemma boundary falsification：

1. 对 admitted pair 系统变异 shape/channel/dtype、crop 边界、Normalize `inplace`、Grayscale 输出通道、padding 和 config；域外必须拒绝签发；
2. 对域内极值和多 seed 做 metamorphic runtime 检验，用于寻找实现/lemma 桥接错误，但动态通过仍不能单独签发 receipt；
3. 在包含 `RandomCrop` 的真实 cedar chain 中同时比较 output、exception、RNG post-state 和实际 plan；
4. 报告 proof/verification latency、receipt bytes、relation adapter SLOC 与每种 lemma 的覆盖贡献；
5. 只有上述攻击保持零 unsafe accept，才考虑 interpolation 或 dtype relation；否则把 V2 定位为窄的 external-proof gate。

## 8. 可复核产物

- protocol：`benchmark/final_v1/p5l_torchvision_relation_algebra_protocol.json`
- public schema：`benchmark/final_v1/reorder_capability_v2.schema.json`
- V2 producer/verifier：`experiments/autocontract_reorder_capability_v2.py`
- runner：`experiments/autocontract_p5l_torchvision_relation_algebra.py`
- result：`outputs/autocontract_p5l_torchvision_relation_algebra.json`
- result SHA-256：`832e2f721ae4df169d55d4e2763faa5483e2fbdf7e42b3f1af08cd7590980b38`
