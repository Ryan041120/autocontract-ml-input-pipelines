# R3-P1：Kornia 真实源码 greybox 校准复盘

日期：2026-07-30
证据等级：已知 H7H 语料上的 posthoc 方法校准，不是新的 blind holdout

## 1. 本轮要回答的问题

H8C-R2 只证明了有限黑盒探测存在 coverage/budget 边界，尚未和能读取公开源码的强灰盒动态基线比较。R3-P1 因此在 H7H 已冻结的 9 个 Kornia `(public symbol, configuration, phase)` 单元上，比较：

1. stateful black-box dynamic；
2. source-guided greybox dynamic；
3. 冻结的 EffectV7；
4. 逐单元人工完整提示的上界。

协议在 runner 正式运行前写入：

`benchmark/final_v1/r3_p1_kornia_greybox_protocol.json`

协议 SHA-256：

`351a05a0ca6015e7ce8a32fc59923b7165b8c60ba103baa6a61ec1015d09b46c`

runner SHA-256：`d0db0dec7215728c32f439feee9f15bf704f7e8ac2024fd300e3b96783737fc4`
最终复跑 JSON SHA-256：`b4a48a7f62b8b9dd44df6f9ca6841fef9675cc7d24486afa6489fc5d2363c8fc`

正式环境与 H8C/H7H freeze 一致：Python 3.12.4、PyTorch 2.4.0、NumPy 1.26.4、CPU；Kornia 固定为 v0.8.3 commit `d6bb4bf0d8a043c2bb8cef0c346a1b006d100930`。

## 2. 结果

| Policy | Budget | TP | FP | FN | TN | Safe recall | Reason accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| EffectV7 frozen | — | 4 | 0 | 0 | 5 | 100% | 100% |
| black-box dynamic | 25 ms | 4 | 1 | 0 | 4 | 100% | 88.9% |
| black-box dynamic | 100 ms | 4 | 1 | 0 | 4 | 100% | 88.9% |
| black-box dynamic | 500 ms | 4 | 1 | 0 | 4 | 100% | 88.9% |
| source-guided greybox | 25 ms | 4 | 0 | 0 | 5 | 100% | 100% |
| source-guided greybox | 100 ms | 4 | 0 | 0 | 5 | 100% | 100% |
| source-guided greybox | 500 ms | 4 | 0 | 0 | 5 | 100% | 100% |
| manual full | — | 4 | 0 | 0 | 5 | 100% | 100% |

黑盒动态能够稳定区分四个 `params_provided` replay 与四个 `params_absent` sampling case；唯一错误是把 `AugmentationSequential` 的 provided-params 单元接纳，因为它观察到的本次执行稳定，却没有 child contract。灰盒策略使用预声明的 1 条公开 MRO/container heuristic，保守拒绝 unresolved Sequential child delegation 后消除了这一 false accept。

三个预算下的混淆矩阵完全一致。25 ms 是 soft budget，单次算子调用不能被安全地中断，因此 black-box 有 6 个、greybox 有 4 个单元发生尾部 overrun；500 ms 下均无 overrun。该 timing 只用于校准，不能写成系统性能结论。

## 3. 直接的 falsification 结论

在这 9 个已知 Kornia 单元上，EffectV7 **没有显示出相对于强 source-guided greybox 的决策准确率增量**。按照预注册规则：

- “EffectV7 比合理强动态/灰盒基线检测更准”这一宽 C1 主张，在 H7H 范围内 **no-go**；
- 旧 `dynamic_output_only` 不能再作为 headline baseline；
- 以后必须把 source-guided greybox 列为正式强基线，并单独报告规则、工厂和一次性源码索引成本；
- EffectV7 的 8 条 adapter rules 对比灰盒 1 条 heuristic，不能在当前材料上声称更低工程负担。

这是有价值的负结果：它在 final-blind 前阻止了一个很容易被评审击穿的创新叙事。

## 4. 仍可保留的研究假设

R3-P1 只否定了当前小范围内的 detection-accuracy 优势，没有否定以下更窄问题：

1. 灰盒的一条 container heuristic 是否能迁移到不同框架、不同 effect 和多层 delegation；
2. 当两种方法给出相同 admit/reject 时，谁能产出稳定、可组合、可验证的原因与 proof obligation；
3. source/configuration/version/content/lineage 发生变化后，谁能准确使旧结论失效；
4. contract 能否避免每次部署或重配置时重新进行高预算探测；
5. contract gate 与 optimizer 集成后，是否在真实 workload 中以可接受代价阻止错误 rewrite。

因此主线从“更强检测器”改成：

> AutoContract 将 effect discovery、rewrite-specific obligation、版本/配置/lineage binding 和运行时验证组合为可审计的重配置 gate；动态/灰盒探测是反例搜索与校准组件，而不是被刻意设置成弱对手。

## 5. 局限

- H7H 已被开发者看过，灰盒 heuristic 是 posthoc 预声明，不具备独立 holdout 证据等级；
- 9 个单元只有 sampling RNG 和 unresolved child 两类主要原因，effect 多样性不足；
- 规则数和 LOC 是机械 proxy，不能代替真实 onboarding 工时；
- EffectV7 的共享源码索引可跨单元摊销；两次本机复跑受文件缓存影响约为 0.55–2.78 s，当前表中的逐单元 latency 没把它重复计入，因此不能用单次数字作性能主张；
- manual full 是免费使用 oracle 的上界，不是可部署方案；
- soft budget overrun 说明正式 benchmark 需要进程级 hard timeout 或将 overrun 独立作为失败状态。

## 6. R3 后续路线

### R3-P2：decision-equivalent invalidation test

在真实 Kornia replay pipeline 上先让 greybox 与 contract 对原始配置作出相同决定，再注入 version、commit、operator graph、child order、parameter record、input schema 与 sample lineage drift。主要指标改为 required-invalidation recall、benign-change preservation、reason completeness、验证成本与重新探测成本。该实验检验 contract artifact 的增量，不再重复证明决策准确率。

### R3-P3：跨框架迁移校准

冻结一套不读取 oracle 的 source-guided greybox 规则，在已有 TorchIO、imgaug、Albumentations 等已知语料上做 posthoc transfer；规则修改必须进入新版本并累计 burden。只有发现稳定的跨框架增量后，才决定 final-blind 是否保留检测精度 RQ。

### final-blind 前的决策

如果 P2 也表明动态+简单 bindings 能以明显更低成本完全替代 contract，则收缩为工程 prototype 或停止 full-paper 路线；如果 P2 支持 versioned/auditable artifact，而 P3 的检测结果持平，则论文贡献明确转为 contract-carrying reconfiguration safety，不再把 analyzer accuracy 放在标题级贡献中。
