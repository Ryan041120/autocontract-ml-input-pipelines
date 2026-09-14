# P5U：瓶颈门控的安全重排研究设计（no-data）

## 研究定位

P5U 是 AutoContract 在本科阶段的收敛性研究阶段：研究“在确实存在输入管线瓶颈时，能否只对经过语义证明的预处理重排进行选择性优化”。研究对象不是通用训练加速器，也不扩展到分布式近数据处理、主动推送或存储系统改造。先用可复现的 baseline profiling 判断是否值得优化，再用 AutoContract 的严格语义约束限制可尝试的重排，最后在任务结果层检查没有明显损害。

本文件是 design-only/no-data 文档，不授权访问数据、训练或 benchmark，不包含正式运行结果；P5T calibration points 不参与本阶段的选择、推断或统计。

## 研究问题与可证伪假设

### RQ1：什么时候重排值得研究？

在固定硬件、软件和输入规模下，预处理是否占据端到端训练输入等待的主要部分，并且存在足够大的理论可移除时间？

H1：至少存在一个预先登记的 workload cell 同时满足 `exposed_input_share >= 20%` 与 `predicted_gain_share >= 5%`。若四个 cell 均不满足，P5U 不继续声称当前 workload 有足够动机进行安全重排。

### RQ2：安全证明能否有效缩小候选空间？

H2：对预先固定的候选变换集合，AutoContract 授权集合不会包含严格语义反例；若出现已确认的语义反例，H2 失败，相关规则回退为 Unknown/拒绝。

### RQ3：安全重排是否能带来可观察的端到端收益？

H3：未来四臂实验中，D 相对 A 的配对端到端 wall-time ratio 满足预注册性能门，且不超出任务结果容忍范围；C/A 仅作描述性消融。若收益小于测量噪声，或任务结果超出容忍范围，H3 不成立。

### RQ4：成本门能否避免“安全但不值得”的重排？

H4：在严格安全候选中，D 只选择预测收益份额至少为 5% 的候选；D/C 是次要成本门比较。若成本门不能提高稳定性，报告其无效。

## P5V baseline-only profiling（四个 cell）

P5V 是下一步的单机 CPU-warm、worker=0、无 prefetch 的 baseline-only 测量，不是多臂收益实验，也不做完整训练/收敛评价。固定四个 cell：

| Cell | 模型 | 输入 crop | 目的 |
|---|---|---:|---|
| M1 | MobileNetV3-small | 224 | 轻量模型、较可能暴露输入等待 |
| M2 | MobileNetV3-small | 448 | 增大预处理与传输工作量 |
| R1 | ResNet18 | 224 | 中等模型、标准输入 |
| R2 | ResNet18 | 448 | 中等模型、高分辨率输入 |

P5V 不做多臂收益实验、不做完整训练/收敛评价；每个 block 只执行固定数量的 baseline forward/backward/optimizer steps，用于端到端时间分解。每个 cell 固定 5 个 warm-up blocks + 20 个 measured blocks，单机 CPU-warm、worker=0、无 prefetch。同一有标签数据 split、batch size、dtype、设备和随机种子由独立协议固定；若标签数据集、split 或环境合同尚未闭合，P5V 保持 blocked。

每个 cell 至少记录：数据读取、预处理、batch 交付、模型计算、输入等待和端到端 step 时间；batch/sample 数、warm-up 与测量区间、worker/prefetch、设备和软件版本；预处理算子清单、每个算子的估计时间、输入/输出字节数及随机状态；重复测量的中位数、离散程度和失败/丢样本/异常计数。

```text
exposed_input_share = median(consumer_blocked_wait_time) / median(end_to_end_step_time)
predicted_gain_share = predicted_gain_time / median(end_to_end_step_time)
```

`consumer_blocked_wait_time` 是 consumer 在关键路径上等待 batch 的暴露时间；`end_to_end_step_time` 从该 block 开始取 batch 到 optimizer step 完成，四个 cell 一致。`predicted_gain_time` 只能来自暴露在关键路径上的、已测量的串行成本，不是实际加速结果。

### 资格门与选择规则

只有同时满足 `exposed_input_share >= 20%`、`predicted_gain_share >= 5%`、完整 baseline 无数据/异常问题、且已有可复现有标签 validation split 的 cell，才进入后续安全重排实验。

若多个 cell 合格，target 选择 `predicted_gain_share` 最大者；contrast 选择四个 cell 中 `predicted_gain_share` 最小者。若 contrast 也合格，称为 low-opportunity contrast，不称其不合格。所有并列先选低 dispersion，再按固定字典序。不得依据 P5T 数值或事后收益选择。若没有合格 cell，停止重排实验，只保留 baseline 结论。

## 未来四臂实验矩阵（仅设计，不执行）

| 臂 | 配置 | 用途 |
|---|---|---|
| A | 原始预处理顺序 | baseline control |
| B | 仅成本/启发式重排，不使用 AutoContract 授权 | 不带安全门的风险对照 |
| C | 仅 AutoContract 严格安全候选 | 测量安全门本身的收益 |
| D | AutoContract 严格安全候选 + 成本模型 + 5% 选择门 | 主张中的候选方案 |

B 不能被描述为安全方案；其语义损害只能作为风险对照。C/D 候选必须先通过严格语义层，再进入任务层。target/contrast 各 20 个 paired blocks，并使用预生成平衡顺序。四臂使用相同数据、split、种子集合和停止规则；正式执行前需另行完成 freeze/launcher/execution closure 并获得明确授权。本设计不创建这些执行工件。

## 成本模型与 5% 选择门

```text
C(plan) = sum(profiled_latency(op_i, input_shape_i, dtype_i))
predicted_gain_share = [C(baseline) - C(candidate)] / baseline_median_step_time
```

成本模型为 `C(plan)=Σ profiled_latency(op_i,input_shape_i,dtype_i)`；只使用 profiling 已测量且边界明确的串行成本。expansion factor 仅解释 shape/bytes，不是安全证据。D 只有在严格授权且 `predicted_gain_share >= 5%` 时可选择。若 `per_batch_saving = C(baseline)-C(candidate) <= 0`，则 `break_even_batches` 为 nonexistent；否则按下方的向上取整公式记录。5% 是选择门，不是实际加速承诺。

未来 P5W 单独记录一次性的三项开销：receipt verification、cost selection、Cedar planning。定义为：

```text
fixed_overhead = median(receipt_verification_time + cost_selection_time + cedar_planning_time)
per_batch_saving = C(baseline) - C(candidate)
break_even_batches = ceil(fixed_overhead / per_batch_saving), if per_batch_saving > 0
```

若 `per_batch_saving <= 0`，`break_even_batches` 为 nonexistent。三项一次性开销不能混入 steady-state primary wall-time；D/A 主比较只使用稳态端到端 wall-time。

## Split 与参数隔离

四类数据用途互斥：profile/calibration split 仅用于 P5V baseline profiling 以及 target/contrast 选择；effect-evaluation split 仅用于未来 A/B/C/D 性能比较；task-validation split 仅用于任务层 secondary sanity check；test split 在全阶段禁止访问。P5V 产生的模型参数必须丢弃，不能作为 P5W 或任务评价的初始化。若资源限制迫使复用图像，必须在运行前冻结复用边界，且结果降为非盲描述性证据。

## 两层安全评价及其关系

严格语义层是必要条件，当前研究对象收窄为已验证关系 Normalize↔RandomCrop(no padding)、单机高分辨率视觉输入，其他候选不自动纳入。固定 exact tensor equality，并比较 shape/dtype/label、definedness/exception、Python/NumPy/PyTorch RNG post-state、相同 file/decode count，以及 receipt 的 source/config/domain/RNG binding；unsafe canary false accept 必须为 0。任意失败不得进入任务训练或 benefit 统计。无法证明等价的候选标为 Unknown 并拒绝授权。

任务结果层是 secondary sanity check：固定相同初始化、样本顺序和 seed，检查短训练的 loss/logits/gradient/model state，并在合法有标签 validation 数据上做 3 个固定 seed 的配对训练，同时记录总时间和输入等待。3 seed 不证明统计等价或一般非劣效；不能为严格层的语义反例免责。任务级 non-inferiority margin 尚未确定，是 P5W freeze 前 blocker，不能替代性能门。

关系是：严格语义层是进入任务层的必要门；任务层补充检查安全重排的实用性。两层分开报告，不把“验证准确率相近”写成“算子语义等价”，也不把“算子等价”写成“训练一定更快/更准”。

## 未来统计与停止规则

P5V 每 cell 固定 5 warm-up blocks + 20 measured blocks，报告 median/IQR/MAD。若 MAD/median > 10%，或环境/电源/温度门失败，profile 无效并 first-error stop；不自动重跑、不事后删异常值或补 block。异常/缺失 block 保留并使该 cell 无效，不用替代值补齐。未来四臂 target/contrast 各 20 个 paired blocks，预生成平衡顺序；primary comparison 为 D/A paired end-to-end wall-time ratio。对 log ratio 使用固定 seed、10000 draws percentile bootstrap；benefit 要求 D/A median < 0.95 且 95% CI upper < 0.95。C/A 为描述性消融，D/C 为次要比较。任务级 non-inferiority margin 尚未确定，是 P5W freeze 前 blocker。

出现数据泄漏、split 不一致、语义反例、未授权候选、异常退出、结果无法绑定固定配置时，立即 first-error stop，该 run 不发布为科学结果。若 target 不满足资格门、所有安全候选预测收益低于 5%、或 D/A 未达到性能门，则停止扩展 workload，不通过换 cell 或换指标追求正结果。

## 风险、blocker 与非主张

- 主要 blocker：当前需先解决有标签数据集与四类互斥 split（profile/calibration、effect-evaluation、task-validation、test）的可复现合同；还需在 P5W freeze 前确定任务级 non-inferiority margin。之前不能把 profiling 或任务层结果写成正式证据。
- 预处理计时可能受缓存、worker 调度、I/O 和边界影响；须先固定 warm/cold 状态和重复规则，不把单次墙钟差异当因果证据。
- 随机增强、状态依赖、空间变换和标签同步是高风险候选；默认 Unknown，除非已有对应 AutoContract 证据。
- 不主张通用训练加速、所有模型/数据集泛化、GPU/冷缓存收益、分布式 NDP 收益、统计显著性、因果关系或 test-set 性能。
- 不使用 P5T 的 8 个 calibration-only points 作为 target、contrast、阈值依据或总体证据。

## 当前状态

本文件完成的是 P5U no-data 设计。未访问数据，未运行 profiling、训练、benchmark、smoke、自测或 launcher，未生成任何 output/result。下一步推进 P5V 前，必须先解决有标签数据集和四类 split 合同、形成独立静态执行前提并再次取得明确授权；任务级 non-inferiority margin 属于 P5W freeze 前 blocker，不是 P5V 前置条件。
