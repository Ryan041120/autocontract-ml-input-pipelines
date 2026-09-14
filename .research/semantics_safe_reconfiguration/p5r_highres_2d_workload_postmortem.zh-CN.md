# P5R-v2：高分辨率 2D 重排的内部 proxy 复盘

## 当前结论

P5R-v2 是一次受限的、内部的 resident-tensor proxy 验证。它不构成独立评测、dataset-I/O 吞吐量测量、scientific evidence 或通用训练加速结论。

在固定 Python 3.11.9、PyTorch 2.0.1+cpu、torchvision 0.15.2+cpu 与 cedar `f062305fcdab196e871c5d09b4c82ab788b4da79` 下，AutoContract receipt 使 cedar 能将 `Normalize→RandomCrop(224)→Identity` 重排为 `RandomCrop(224)→Normalize→Identity`；精确语义检查通过，并且在此预注册 proxy 的收益门槛通过。

## 公平比较与冻结

- baseline 与 receipt-guarded 两臂都调用 cedar `optimize` 和 `load_from_plan`，使用同一份 workload-specific、cedar-compatible frozen profile，而非任何 tests 目录下的默认 profile。
- profile phase 在真实 baseline node path `source→Normalize→Crop→Identity` 上实测每算子 latency、输入/输出 tensor bytes，并生成 `benchmark/final_v1/p5r_highres_2d_profile.yml`；confirm 会核验其 SHA。
- `Identity` 是语义惰性的第三 mapper；它对应当前冻结 profile 的三节点工作负载。complete-pair 的 3 张 receipts 是该三节点区段的 pairwise complete cover，不应被误说成通用 proof 成本。
- 输入为 cedar `tests/data/images` 中真实 JPEG 解码后、在计时外确定性 resize 到 2048² 的 resident tensors。输出记录 JPEG SHA；因此它是 **real-image-content / shape-faithful resident-tensor proxy**，但不测量 decode、resize 或真实 dataset I/O。

## 语义与审计

每个 confirm 都有 21 个 AB/BA paired blocks、每臂 3 次丢弃的 warmup；每一 block 都有 fresh cedar preprocessing 和 deterministic MobileNetV3-small training pass。

两次独立 CLI fresh process 均通过 19/19 检查：exact output tensors/shapes/definedness、Python/NumPy/torch RNG、MobileNet loss/logits/gradients/model state。manual `Crop→Normalize→Identity` arm 仅用作语义 oracle，且与 guarded 精确一致；它不是性能 comparator。

负控制全部 fail-closed：输入域缩到 crop 不全定义范围、修改 Normalize 配置、以及 **source-binding digest tamper** 均被拒绝。最后一项是 receipt 绑定摘要篡改，不等于实际修改 torchvision 源码或 native kernel。

aggregate 强制审计：两个 run UUID 和 PID 不同、UTC 时间可解析且按执行顺序递增、每次恰有 21 pairs、runner/protocol/profile SHA 都与当前文件匹配。

## 预注册 proxy 门槛

语义通过和收益门槛分开报告：

- 每个 run：paired median `guarded/baseline < 0.95`；
- aggregate：两 run 的 paired log ratio 进行 10,000 resample bootstrap，95% CI 上界 `< log(0.95)`；
- 仅当全部语义检查通过时，才允许 `benefit_go=true`。

运行时仍输出 2,000-resample paired delta CI，但那是描述性统计，不能替代 confirmatory gate。

## 证据边界

P5R-v2 只说明：在一个已知可交换、空间缩减明显、真实 JPEG 内容但内存驻留的 CPU proxy 中，AutoContract 可以安全地授权 cedar 重排，并满足预注册的内部 proxy 收益门槛。它没有证明真实训练系统的普适收益，也未覆盖 native ABI/hardware 漂移、独立语料或未见算子对。

当前证据文件：

- `benchmark/final_v1/p5r_highres_2d_workload_protocol.json`
- `benchmark/final_v1/p5r_highres_2d_profile.yml`
- `experiments/autocontract_p5r_highres_2d_workload.py`
- `outputs/autocontract_p5r_highres_2d_profile.json`
- `outputs/autocontract_p5r_highres_2d_confirm_run1.json`
- `outputs/autocontract_p5r_highres_2d_confirm_run2.json`
- `outputs/autocontract_p5r_highres_2d_aggregate.json`
