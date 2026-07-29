# AutoContract 第一轮可行性实验结果

更新日期：2026-07-26

## 1. 阶段判断

**第一阶段通过，可以继续；但还不能据此声称论文贡献成立。**

本轮完成了两个可重复运行的 pilot：

1. 对真实 `torchvision.transforms.v2` 算子做 effect probing、全局 RNG/算子键控 RNG 下的相邻交换验证和分布检验。
2. 对无缓存、安全前缀缓存和不安全完整缓存做性能、逐样本 trace 与增强多样性比较。

最重要的发现不是小规模准确率本身，而是发现了一个具体、可复现、现有 `random/non-random` 二元标记难以表达的失败：

> 固定 `sigma` 的 `GaussianBlur` 输出是确定的，但 torchvision 0.19 仍推进全局 Torch RNG。把它与后续随机增强交换，或者缓存并跳过它，会改变下游增强的随机轨迹。

这说明 AutoContract 至少要把“输出是否随机”和“是否读取/推进哪一种 RNG 状态”拆成两个 effect。

## 2. 实验 A：effect 与交换验证

### 设置

- 环境：Python 3.9.19、PyTorch 2.4.0+cu124、torchvision 0.19.0+cu124。
- 13 个算子：12 个 torchvision v2 算子，加 1 个带隐藏 counter 的 stateful UDF。
- 16 组人工构造的相邻交换，包括安全交换、几何不等价、dtype 前置条件、共享 RNG、跨调用隐藏状态和 cache 相关反例。
- 24 个 trace trial、16 个 effect seed；分布检验使用 96 个样本和 199 次 permutation。
- 动态验证只负责寻找反例，不被解释为数学证明。

### 结果

| 项目 | 结果 |
|---|---:|
| 基础 effect 判断 | 52/52 |
| 全局 RNG 下安全交换 | 6/6 接受 |
| 全局 RNG 下不安全交换 | 0/10 误接收 |
| 全局 RNG precision / recall | 1.000 / 1.000 |
| operator-keyed RNG 下安全交换 | 9/9 接受 |
| operator-keyed RNG 下不安全交换 | 0/7 误接收 |

operator-keyed RNG 使三组在共享 RNG 下不满足 trace equivalence 的交换变得逐元素一致：

- fixed-sigma `GaussianBlur ↔ RandomHorizontalFlip`；
- `RandomHorizontalFlip ↔ RandomVerticalFlip`；
- `ColorJitter ↔ RandomHorizontalFlip`。

这三组在全局 RNG 下把不同随机数分配给不同 operator；用 `(epoch, sample_id, operator_id)` 生成稳定随机流后，operator 得到的参数不再受计划顺序影响。注意：这改变了 legacy global-RNG contract，不能静默启用；它应由用户选择的契约或迁移模式控制。

### 分布层结果

小规模 RBF-MMD 诊断正确区分了本轮 15 组有 distribution ground truth 的交换。尤其是，上述三组 global trace 不一致的交换仍通过了 distribution-level 检验，而几何顺序变化、`ColorJitter ↔ Normalize`、`RandomErasing ↔ Normalize` 等被拒绝。

该结果只说明“契约分层”值得继续，不能证明当前特征统计足以代表真实训练分布。

## 3. 实验 B：缓存、RNG 与增强多样性

流水线包含一个昂贵的确定性前缀：fixed-sigma Gaussian blur + resize；随机后缀为 horizontal flip + random crop + color jitter。24 个 synthetic image 运行 5 个 epoch，每种 policy 重复 3 次。

| Policy | 中位运行时间 | 相对同 RNG 无缓存加速 | 相对 global 无缓存运行时间 | epoch 0 后 trace match | 每样本平均唯一输出数 |
|---|---:|---:|---:|---:|---:|
| global:none | 0.4030 s | 1.00× | 1.00× | 1.000 | 5.00 |
| global:prefix | 0.2373 s | 1.70× | 0.59× | 0.000 | 5.00 |
| global:full | 0.0984 s | 4.09× | 0.24× | 0.000 | 1.00 |
| operator_keyed:none | 1.3471 s | 1.00× | 3.34× | 1.000 | 5.00 |
| operator_keyed:prefix | 0.7612 s | 1.77× | 1.89× | 1.000 | 5.00 |
| torch_keyed:none | 1.1156 s | 1.00× | 2.77× | 1.000 | 5.00 |
| torch_keyed:prefix | 0.8269 s | 1.35× | 2.05× | 1.000 | 5.00 |

三个含义：

1. **性能机会真实存在。** 缓存 deterministic prefix 在同一 RNG 机制内获得约 1.7× 加速。
2. **仅标记“输出是否随机”不够。** global prefix cache 保持了每 epoch 的增强多样性，却从第二个 epoch 起与无缓存 pipeline 的逐样本 trace 完全不同，因为 cache hit 跳过了隐藏 RNG 消耗。
3. **朴素修复不可接受。** 当前原型通过每个 operator 前调用 `manual_seed` 获得 100% trace match，但整体比 global 无缓存慢 2.77–3.34×。最终系统必须使用真正的 stateless/functional RNG，而不是反复修改全局 RNG。

完整缓存看起来最快，但把 5 个 epoch 的唯一增强数从 5 降为 1，直接展示了吞吐指标为何不能替代语义契约。

## 4. 与已有随机性工作的边界

[Reproducible Randomness in Parallel ML Input Pipelines](https://doi.org/10.3929/ethz-b-000563990) 已提出 per-element seed，把随机操作转为 stateless function，并用 seed splitting 支持同一样本上的多个随机操作；其 TensorFlow 原型报告相对非确定 baseline 的开销很小。因此以下内容不能作为我们的新贡献：

- per-element seed 本身；
- stateless random augmentation 本身；
- 并行情况下的可复现随机性本身。

该工作按随机操作出现顺序不断 split/update seed，没有研究 optimizer 重排或 cache 跳过 operator 后如何维持 operator identity；全文也没有 `reorder` 或 `cache` 相关设计。TensorFlow 也已经公开提供 stateless image augmentation API。

所以 AutoContract 应把已有 stateless RNG 当作机制，主贡献保持为：

1. 自动推断 output randomness、RNG source/consumption、字段/shape/dtype、状态和 sample scope；
2. 根据用户选择的 trace/distribution/visitation contract 判断 reorder/cache/fusion 是否可接受；
3. 为被接受的计划生成必要的 RNG virtualization 或 cache-key 条件；
4. 对未知 UDF 保守固定，并输出可解释的拒绝理由。

## 5. 当前最值得验证的假设

- **H1：** 只检测“不同 seed 下输出是否变化”会漏掉 deterministic-but-RNG-consuming operator；联合检测 RNG state transition 可以显著降低不安全改写误接收。
- **H2：** `(sample_id, epoch, stable_operator_id)` 键控的 stateless RNG 能让 plan reorder/cache hit 不改变 trace，同时保持随机操作之间的独立性。
- **H3：** `registry + static analysis + runtime effect probe + differential validation` 的混合方法，相比任一单独方法能在不接受已知 unsafe rewrite 的前提下保留至少 80% 的人工 oracle 机会。
- **H4：** 用 functional/stateless kernel 实现 H2 后，RNG 机制相对 global baseline 的端到端开销不超过 5%。

H4 是当前最危险的可行性门槛。本轮 2.77–3.34× 的朴素开销证明不能回避它。

## 6. 威胁与不能声称的结论

- 16 个 pair 的 ground truth 由同一研究过程构造，存在确认偏差；下一轮需要从官方语义、源码和独立人工标注建立 ground truth。
- synthetic tensor 没有覆盖 PIL、JPEG decode、bounding box、mask、video、audio、batch transform 和自定义 I/O。
- 动态 differential test 只能发现反例，不能证明所有输入等价。
- MMD 使用的是少量手工 summary feature，不等同于训练分布或模型收敛保证。
- 当前性能是单进程 CPU microbenchmark，没有包含 DataLoader worker、GPU stall 或真实 cache backend。
- 结果绑定到 torchvision 0.19.0；跨版本 RNG 消耗可能改变。

## 7. 第二阶段 go/no-go 线

继续到 30 个 operator、10 条 pipeline 时，只有同时满足以下条件才升级为论文原型：

1. 已知 unsafe rewrite 的误接收数仍为 0；
2. safe rewrite recall 至少 80%；
3. 自动推断减少至少 70% 的人工 annotation；
4. stateless/keyed RNG 相对 global baseline 开销不超过 5%；
5. 至少一条真实 pipeline 在维持所选 contract 时获得 20% 以上 input throughput 提升；
6. 至少覆盖视觉分类和一种结构不同的 workload（detection、audio 或 multimodal）。

若第 4 条失败，保留“隐藏 RNG effect 的经验研究/检测工具”，不宣称通用优化系统。

## 8. 可重复运行文件

- `experiments/autocontract_feasibility.py`
- `experiments/autocontract_cache_benchmark.py`
- `outputs/autocontract_effects.csv`
- `outputs/autocontract_pairs.csv`
- `outputs/autocontract_distributions.csv`
- `outputs/autocontract_feasibility.md`
- `outputs/autocontract_cache_benchmark.csv`
- `outputs/autocontract_cache_benchmark.md`

## 9. 第二轮更新：H4 无状态 RNG 门槛

更新日期：2026-07-27

### 9.1 原型机制

新增原型不再在每个算子前调用 `manual_seed`，而是把每次随机抽样直接寻址为：

```text
random_word = PRF(base_seed, epoch, sample_id, stable_operator_id, draw_index)
```

当前 Python 原型使用 SplitMix64 做 64 位混合，并用 functional kernel 复刻
`RandomHorizontalFlip`、`RandomCrop` 和 `ColorJitter` 的参数分布。稳定算子 ID
使同一算子在计划重排前后仍取得相同参数；`draw_index` 区分一个算子内部的多个随机抽样。
SplitMix64 只是低成本可行性实现，不是本文的 RNG 创新，也不能据此声称跨硬件、跨版本或
密码学质量；正式系统应换用经过统计测试的 counter-based RNG（例如 Philox/Threefry）。

### 9.2 计时方法

- 48 张合成图像，6 个 epoch；单线程 CPU。
- 端到端计时重复 5 次，随机后缀单独计时重复 7 次。
- 原生与无状态实现按 AB/BA 顺序交错成对运行，避免整段顺序执行造成温度或系统负载偏差。
- 计时包含输出摘要；缓存计时包含第一轮缓存构建。
- 随机后缀单测移除 Gaussian blur 与 resize，防止高成本确定性工作掩盖 RNG 控制开销。

### 9.3 正式结果

| 测试 | 原生中位数 | 无状态中位数 | 无状态相对开销 |
|---|---:|---:|---:|
| 完整流水线 | 1.0131 s | 0.8786 s | -13.28% |
| 仅随机后缀 | 0.5197 s | 0.4600 s | -11.48% |

因此 H4“相对原生流水线开销不超过 5%”在当前 CPU/torchvision 原型上通过。负开销不应
泛化为“无状态 RNG 总会更快”；它只说明本实现消除了 `manual_seed` 的灾难性成本，而且
Python 整数混合与 functional dispatch 在这组算子上没有形成新的性能障碍。

其他语义检查：

- 无状态前缀缓存相对无缓存获得 1.51× 加速，epoch 0 之后逐样本 trace match 为 100%。
- 完整流水线缓存为 4.21×，但每个样本跨 6 个 epoch 的唯一输出从 6 降到 1，正确触发
  “冻结随机增强”拒绝条件。
- `GaussianBlur ↔ HFlip`、`HFlip ↔ VFlip`、`ColorJitter ↔ HFlip` 三组稳定-ID
  重排共 96 次 trial 全部 `allclose`；最大绝对误差不超过 `7.153e-7`。
- 原生与无状态随机后缀的 12 维输出特征 RBF-MMD² 为 `0.0032986`，199 次置换检验
  `p=0.485`，未检测到分布差异。该结果不是分布相等证明。

### 9.4 与已有工作的边界

- [Random123](https://random123.com/releases/docs/) 已系统化 counter-based RNG；无状态
  `(counter, key) -> random` 不是新贡献。
- [JAX random](https://docs.jax.dev/en/latest/jax.random.html) 已使用显式 PRNG key、
  `split` 和 `fold_in`；显式 key 管理不是新贡献。
- [TensorFlow stateless random crop](https://www.tensorflow.org/api_docs/python/tf/image/stateless_random_crop)
  已保证给定 seed 时结果不受调用次数和 global seed 影响；无状态增强 API 不是新贡献。
- ETH 的 *Reproducible Randomness in Parallel ML Input Pipelines* 已覆盖 per-element seed、
  stateless random op 和 seed splitting。

所以 AutoContract 的可保留贡献必须是组合闭环，而不是 RNG 本身：

1. 自动识别输出随机性、RNG 消耗/来源、隐式状态和 sample scope；
2. 根据 trace/distribution/visitation contract 判定具体 rewrite；
3. 只为被接受的 reorder/cache 生成稳定 operator identity 与 RNG virtualization；
4. 对未知 UDF 保守拒绝，并给出可解释证据。

### 9.5 更新后的 go/no-go

- H1/H2 的小规模证据成立；H4 从“最大风险”降为“当前平台已通过、仍需真实流水线复验”。
- 当前总判定仍是 **conditional go**，不能升级为论文结果，因为 30 算子覆盖、自动标注减少率、
  真实 DataLoader/GPU stall 和第二类 workload 仍未验证。
- 下一优先级改为 H5：在真实 JPEG/ImageFolder + 多 worker DataLoader 中验证安全前缀缓存能否
  在保持所选 contract 时带来至少 20% input throughput 改善；若达不到，再判断机会是否只存在于
  昂贵 decode/augmentation 或存储受限区间。

新增可重复运行文件：

- `experiments/autocontract_stateless_benchmark.py`
- `outputs/autocontract_stateless_benchmark.csv`
- `outputs/autocontract_stateless_components.csv`
- `outputs/autocontract_stateless_reorders.csv`
- `outputs/autocontract_stateless_benchmark.md`

## 10. 第三轮更新：H5a 真实 JPEG/DataLoader 路径

更新日期：2026-07-27

### 10.1 问题与实验边界

本轮验证“语义安全的 deterministic-prefix cache 在真实 JPEG 解码与多 worker DataLoader
路径上是否仍有系统收益”。由于官方 CIFAR-10 源和 Hugging Face 镜像均被本机网络策略阻断，
实验改用 scikit-image 随环境提供的 7 张真实照片，生成 600 个确定性裁剪，并编码为
224×224、quality 92 的真实 JPEG；目录符合 ImageFolder 结构。它能够验证 JPEG、文件系统、
worker 与 GPU transfer 路径，但内容多样性不足，不能作为训练数据集实验。

两条流水线只在 deterministic prefix 的来源不同：

```text
uncached = JPEG read/decode -> GaussianBlur -> Resize -> stateless random suffix
cached   = shared uint8 memmap prefix cache          -> stateless random suffix
```

随机后缀仍按 `(epoch, sample_id, stable_operator_id, draw_index)` 寻址。缓存由主进程一次性构建，
worker 只读共享 memmap，避免每个 worker 持有各自的 Python cache。测试使用 600 个样本、4 epoch、
batch size 64、CUDA transfer/normalize/reduce consumer；每个 worker 配置做两次 AB/BA 成对运行。

### 10.2 结果

| Workers | 端到端加速 | 去除首批后的稳态加速 | 稳态 samples/s（无缓存→缓存） | Trace match | 离线回本 epoch | 4 epoch 含构建摊销 |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 3.41× | 3.41× | 189.5→646.4 | 1.000 | 5.14 | 0.83× |
| 2 | 1.37× | 2.73× | 344.3→941.5 | 1.000 | 10.41 | 0.72× |
| 4 | 1.17× | 2.52× | 526.6→1324.8 | 1.000 | 16.76 | 0.77× |

H5a 的稳态门槛（至少 1.20× 且 exact trace）在三种 worker 配置上都通过。2-worker 配置即使
包含首批启动成本，在 4 epoch 的测量窗口内也有 1.37× 执行加速；4-worker 配置则因 Windows
spawn/initial prefetch 使首批约需 20–21 秒，端到端只剩 1.17×。

但是，若把 11.51 秒的离线 cache build 作为额外 pass 计入，4 epoch 的总耗时在所有配置下
都比不缓存更慢（0.72–0.83×）。因此“安全且稳态更快”不等于“当前训练任务值得采用”。

### 10.3 新的关键研究点：horizon-aware rewrite admission

这一结果把 AutoContract 的优化判定从两维扩展为三维：

```text
admit(rewrite) = semantic_contract_holds
                 AND expected_benefit(workers, epochs, cache_lifetime) > 0
```

候选 cache 不仅需要 effect/contract 证明，还应生成并检查一个收益证书：缓存构建成本、worker
启动成本、每 epoch 稳态节省、预期训练 horizon、缓存能否跨 run 复用以及存储占用。最简单的
离线回本条件为：

```text
epochs > cache_build_time / (uncached_epoch_time - cached_epoch_time)
```

本轮对应阈值随 worker 数从 5.14 上升到 16.76 epoch。这个“contract-safe but
economically-invalid rewrite”是优化器必须处理的反例，但后续文献复核确认：Cachew 已经覆盖
性能/成本驱动的 autocaching、pipeline fingerprint 和跨作业 reuse。因此 horizon-aware admission
是完整系统的必要层，不应单独包装成 AutoContract 的主要创新。

### 10.4 当前判定

- **H5a：PASS。** 真实 JPEG/DataLoader 系统路径上存在大于 20% 的稳态机会，且 trace 不变。
- **完整 H5：尚未通过。** 当前 CUDA consumer 只做 transfer、normalize 和 reduce，没有真实模型
  backward、GPU stall、p95 step time 或准确率验证。
- AutoContract 仍为 **conditional go**。下一步应做 H5b：选择一条真实分类训练 workload，比较
  baseline、无条件缓存、contract-safe cache 与 horizon-aware admission，并报告 input wait、step
  time、GPU utilization、训练 trace/metric 和跨 run cache reuse。

新增文件：

- `experiments/autocontract_h5_jpeg_dataloader.py`
- `outputs/autocontract_h5_jpeg_workers.csv`
- `outputs/autocontract_h5_jpeg_dataloader.md`

## 11. 第四轮更新：H5b 真实 ResNet-18 训练路径

更新日期：2026-07-28

### 11.1 设置

本轮把 H5a 的 600-JPEG、2-worker DataLoader 接到真实 ResNet-18，执行 4 epoch 的
forward、backward 和 SGD step。uncached 与 cached 每次都使用相同模型初始化、样本顺序和
operator-keyed augmentation；两种计划按 AB/BA 顺序各运行两次。除训练时间外，同时记录：

- 每个 batch 的输入 digest；
- 每个 step 的 loss；
- 训练结束后的完整 model-state digest；
- DataLoader wait、compute time、median/p95 step time；
- `nvidia-smi` 的 GPU utilization 与 memory 采样。

### 11.2 训练结果

| Policy | 中位训练时间 | Samples/s | Data wait | Compute | Median / p95 step | GPU util mean / p95 | Final loss | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| uncached | 18.79 s | 127.8 | 5.80 s | 1.25 s | 0.136 / 0.371 s | 11.5% / 30.5% | 0.09921 | 0.838 |
| cached | 13.61 s | 176.4 | 1.08 s | 1.07 s | 0.052 / 0.085 s | 11.8% / 47.1% | 0.09921 | 0.838 |

热缓存训练加速为 **1.38×**。主要收益来自 DataLoader 等待从 5.80 秒降到 1.08 秒；平均 GPU
utilization 被约 10–11 秒的 Windows worker 首批启动拉低，因此仅小幅变化，但 p95 utilization
从 30.5% 提高到 47.1%。

语义检查全部通过：

- 所有 batch digest 完全相同；
- 逐 step loss 最大差异为 `0.000e+00`；
- 最终 model-state digest 完全相同；
- final loss 与 accuracy 相同。

### 11.3 冷/热缓存决策

H5a 在 2 workers 下预测离线缓存需 10.41 epoch 回本，而本任务只有 4 epoch。因此：

| 状态 | Admission | 实测最优 | 结果 |
|---|---|---|---|
| 冷缓存，构建成本 11.51 s | REJECT | uncached：18.79 s；naive cache：25.11 s | 正确 |
| 可复用热缓存，剩余构建成本 0 | ACCEPT | cached：13.61 s | 正确 |

这验证了成本层确实需要区分 cache lifecycle 和 sunk cost，但文献定位必须保守：Cachew 已经会
在作业内和跨作业检查 fingerprint/cache hit，并选择性能/成本有效的执行模式。因此不能把
“冷拒绝、热接受”本身当新贡献。

### 11.4 与 Cachew/cedar 的重新定位

Cachew 的 `autocache` 由用户放到“训练语义允许复用”的位置，并明确建议位于随机变换之前；
其评估也假设用户已经给出 acceptable location。cedar 同样依赖用户提供 dependency/randomness
信息。AutoContract 最有防御性的组合方式应是：

```text
AutoContract:
  automatic effect inference
    -> certified rewrite/cache candidates
    -> required trace/distribution contract
    -> stable operator RNG + cache-key/invalidation obligations

Cachew/cedar-style optimizer:
  choose the fastest/cost-effective plan among certified candidates
```

所以当前建议名称可以进一步收窄为：

> **AutoContract: Contract-Carrying Rewrites for ML Input Pipelines**

这里的 “contract-carrying” 指每个被接受的 rewrite 同时携带：(1) 自动推断的 effect 证据，
(2) 所保证的语义层级，(3) RNG/cache key 条件，(4) 动态反例测试结果；成本模型是消费者，
不是论文主贡献。

### 11.5 更新后的判断

- **H5b pilot：PASS。** 真实 model training path 上获得 1.38×，且 batch/loss/model trace 一致。
- H4/H5 已不再是最危险门槛；继续做更多同类 cache 性能实验的边际价值下降。
- 现在最大的论文风险回到核心 H3：自动 effect inference 能否扩到 30 个算子、10 条 pipeline，
  保持 0 个已知 unsafe rewrite 误接受、safe recall ≥80%、annotation reduction ≥70%。
- 下一轮应停止扩展 cost controller，优先构建 `registry + static/bytecode analysis + runtime probe +
  differential validation` 的消融实验；若 H3 失败，课题应降级为隐藏 RNG effect 检测工具。

新增文件：

- `experiments/autocontract_h5b_training.py`
- `outputs/autocontract_h5b_training.csv`
- `outputs/autocontract_h5b_decisions.json`
- `outputs/autocontract_h5b_training.md`

## 12. 第五轮更新：H3 自动 effect inference 消融

更新日期：2026-07-28

### 12.1 预注册协议

本轮回到 AutoContract 的核心风险，而不再扩展 cost controller。实验固定为：

- 30 个唯一算子签名、10 条流水线、37 个相邻交换候选；
- 只为 6 个常见算子提供可信 registry，其余由静态分析、运行时探针或两者融合推断；
- effect 包含 output randomness、RNG source、shape/dtype change、hidden state 与 sample scope；
- 实际 validator 使用 8 轮差分测试，oracle 使用 48 轮差分测试；
- 预先固定的通过线为：known-unsafe false accepts = 0、safe recall ≥80%、人工标注减少 ≥70%。

算子集同时放入了三类对有限动态测试不友好的反例：Python/NumPy RNG、输出固定但仍消耗
Torch RNG 的 blur，以及在本次运行中表现为恒等函数但读取可变环境变量的 UDF。候选并非在原始
pipeline input 上孤立测试；每个位置会先执行其真实前缀，再在当前中间张量上比较交换前后。

### 12.2 正式结果

| Mode | Effect coverage | Resolved-cell accuracy | TP | FP | FN | TN | Safe recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| registry-only | 20.0% | 100.0% | 6 | 0 | 9 | 22 | 40.0% |
| static-only | 66.1% | 99.2% | 15 | 0 | 0 | 22 | 100.0% |
| runtime-only | 100.0% | 98.9% | 15 | 1 | 0 | 21 | 100.0% |
| hybrid | 99.4% | 100.0% | 15 | 0 | 0 | 22 | 100.0% |

37 个候选中，oracle 判定 15 个 safe、22 个 unsafe。hybrid 正确接受全部 15 个 safe
候选，并拒绝全部 22 个 unsafe 候选。唯一无法完全解析的算子是 `external_env`；因此
剩余需要人工确认的签名为 6 个 registry 签名加 1 个未解析签名，相比 30 个全人工
签名减少 **76.7%**。

因此 H3 三条门槛全部通过：

- known-unsafe false accepts：**0，PASS**；
- safe recall：**100.0%，PASS**；
- annotation reduction：**76.7%，PASS**。

### 12.3 最重要的反例证据

runtime-only 的唯一个误接受是：

```text
external_env -> center_crop
```

`external_env` 读取 `AUTOCONTRACT_EXTERNAL_GAIN`，但测试期间环境值没有变化；所以 8 轮动态探针把它
错判为 replayable per-sample 恒等函数。hybrid 在源码中识别到外部状态读取，将 scope 保持为
unknown，因而在差分测试之前保守拒绝。这个结果支持一个明确论文命题：

> Finite runtime equivalence tests cannot establish rewrite safety for dormant external state;
> effect evidence and unresolved-scope rejection are necessary.

### 12.4 当前 go/no-go 与边界

- **H3 pilot：PASS。** 同时 H4 和 H5b 也已通过，因此课题从 `conditional go` 升为
  **go for a research prototype and broader evaluation**。
- 这仍不是形式正确性证明。30 个算子与 10 条 pipeline 是人工构造的 pilot corpus；48 轮 oracle
  只是更高预算的反例搜索，不能证明交换律。
- 下一个关键风险是 external validity：需要从真实 GitHub 项目抽取 torchvision/Albumentations/Kornia
  pipeline 和自定义 UDF，在不手工调整规则的前提下重复同一组门槛。
- 静态层目前是 Python source/AST token prototype，未覆盖 C++/CUDA extension、closure/global alias、I/O
  间接调用、multiprocessing state 和版本依赖。这些应成为下一轮 adversarial UDF corpus。

新增可重复运行文件：

- `experiments/autocontract_h3_ablation.py`
- `outputs/autocontract_h3_effects.csv`
- `outputs/autocontract_h3_pairs.csv`
- `outputs/autocontract_h3_ablation.csv`
- `outputs/autocontract_h3_ablation.md`

## 13. 第六轮更新：H6A 真实 GitHub effect-schema pilot

更新日期：2026-07-28

### 13.1 设置

将 torchvision、timm、Ultralytics、Detectron2、Albumentations 和 Kornia 固定到具体 commit，
抽取 20 个真实 pipeline builder/transform container。原型不安装上游项目，而是通过 AST
及本地继承/调用闭包推断 randomness、RNG source、target set、external dependency、sample
cardinality 和 target coupling。

H6A 只是 schema-feasibility 门槛，不是完整 rewrite 安全性验证。通过线预先设为：
holdout effect-cell accuracy ≥80%、coupling FN = 0、many-to-one FN = 0。

### 13.2 结果

| Split | Units | Effect-cell accuracy | Coupling FN | Many-to-one FN |
|---|---:|---:|---:|---:|
| debug | 3 | 100.0% | 0 | 0 |
| holdout | 17 | 71.6% | 0 | 0 |

**H6A v1：FAIL。** 虽然未漏掉已知 target coupling 和 `k->1` 算子，但 holdout accuracy 未达
80%，不应继续把 v1 schema 接到 rewrite validator。

29 个错误 cell 中，14 个来自 target set、8 个来自 RNG 委托边界、5 个为 coupling 保守误报、
2 个是把构造期环境写入当成逐样本外部依赖。这说明问题不只是 token rule 不够多，而是 effect
language 需要同时表达：

- construction 与 execution phase；
- read set 与 write set；
- direct RNG 与 delegated RNG；
- fixed target signature 与 child/config-parametric signature。

### 13.3 方法学处理

已查看错误的 6 个仓库全部转为 calibration corpus。为避免在同一 holdout 上反复调规则，
另行密封 MONAI、MMDetection 和 NVIDIA DALI 的具体 commit；在 EffectV2 规则冻结前不打开它们的
transform 源码。

当前判定不是 no-go：H3/H4/H5 仍成立，而 H6A 也表明样本基数与 coupling 可被保守识别。
但在 EffectV2 和新 blind holdout 通过之前，不能声称已实现通用真实项目的自动 contract inference。

新增文件：

- `experiments/autocontract_h6_github_corpus.py`
- `outputs/autocontract_h6_sources.csv`
- `outputs/autocontract_h6_effects.csv`
- `outputs/autocontract_h6_summary.csv`
- `outputs/autocontract_h6_schema_pilot.md`
- `outputs/autocontract_h6_blind_holdout.csv`

## 14. 第七轮更新：EffectV2 冻结与一次性 blind holdout

更新日期：2026-07-28

EffectV2 在已打开的 6 个 calibration 仓库上完成 20 单元、15 字段的标注与分析，
300/300 effect cells 匹配、关键漏检为 0。在打开新 source 前，分别固定 analyzer hash、calibration
oracle hash、blind oracle hash 与通过线。

一次性 blind 包含 MONAI、MMDetection 和 NVIDIA DALI 的 12 个单元，得到：

| 指标 | 门槛 | 结果 |
|---|---:|---:|
| Effect-cell accuracy | ≥95% | 76.1% |
| Critical false negatives | 0 | 9 |
| Known-unsafe false accepts | 0 | 2 |

**H6 blind：FAIL。** 误接受是 MMDetection `CachedMosaic` 和 DALI `Pipeline`。根因包括 MONAI
`self.R` RNG alias、MMDetection 的 `transform` entrypoint/跨模块基类、执行期 cache state，以及 DALI
many-to-many backend graph。

因此研究判断改为：

- 对 framework-agnostic arbitrary-Python automatic inference：**no-go**；
- 对 adapter-assisted AutoContract：**conditional go**；
- generic analyzer 对未解析基类、entrypoint、RNG alias 或 backend 必须返回 `Unknown(reason)` 并拒绝；
- framework adapter 只补充框架级结构语义，不回退到逐算子人工 annotation。

新增文件：

- `experiments/autocontract_h6_effect_v2.py`
- `experiments/autocontract_h6_blind_eval.py`
- `outputs/autocontract_h6_v2_calibration.md`
- `outputs/autocontract_h6_v2_freeze.json`
- `outputs/autocontract_h6_blind_oracle.json`
- `outputs/autocontract_h6_blind_report.md`
- `.research/semantics_safe_reconfiguration/h6_blind_postmortem.zh-CN.md`

## 15. 第八轮更新：H7A `Unknown(reason)` 与 framework adapters

更新日期：2026-07-28

### 15.1 改动

冻结的 EffectV2 analyzer 保持不变。新原型在其上增加：

```text
EffectV3 = EffectV2 + execution_state_writes
AnalysisResult = Resolved(EffectV3, adapter, evidence) | Unknown(reason...)
```

validator 对 `Unknown`、参数化 target、非一对一 cardinality、combine lineage、执行期内部状态写入和
执行期外部 effect 默认拒绝。框架 adapter 只注入 entrypoint、RNG alias、record schema、外部基类摘要、
lineage convention 和 state lifecycle，不按算子名字建立 safe 白名单。

### 15.2 校准结果

本轮复用已经打开的 H6 blind 失败集做 postmortem calibration，因此不是第二次 blind evaluation：

| 指标 | 结果 | H7A 门槛 |
|---|---:|---:|
| Validator decision accuracy | 12/12 (100%) | 描述性 |
| Known-unsafe false accepts | 0 | 0，PASS |
| Supported safe recall | 2/2 (100%) | ≥70%，PASS |
| Unsupported reason coverage | 2/2 (100%) | 100%，PASS |

MONAI 四个组合容器被 adapter 解析，但因 parametric target signature 拒绝。MMDetection 的
`RandomFlip`/`RandomCrop` 被接受；Mosaic/MixUp/CopyPaste 因 many-to-one combined lineage 拒绝；
`CachedMosaic` 还被检测出 `self.results_cache` 的执行期状态写入。DALI 没有 adapter，两个单元均输出
带具体原因的 `Unknown` 并拒绝。

初次实现曾因 `RandomFlip.transform` 来自外部 `MMCV_RandomFlip` 基类而只得到 50% safe recall；
加入既定的“外部基类 execution summary”框架规则后恢复为 100%。这次中间失败说明 adapter 必须显式
建模跨模块控制流，不能只把 `transform` 字符串加入通用入口列表。

### 15.3 不能提前通过的门槛

两套 adapter 共 10 条结构规则，覆盖本轮 10 个 supported 单元，即 1.00 rules/unit。若以 16 个
EffectV3 字段的逐单元标注作描述性基准，cell-equivalent reduction 为 93.8%；但规则和 effect cell
不是同一种标注成本，也没有记录人工分钟数。因此 annotation reduction ≥70% 仍是 **UNRESOLVED**。

**H7A safety/recall mechanism：PASS；H7 overall：INCOMPLETE。** 下一步冻结当前 analyzer 与 adapter
manifest，预注册未见项目/版本的 H7B holdout；在不修改 adapter 的前提下测试跨项目泛化和真实标注成本。

新增文件：

- `experiments/autocontract_h7_adapters.py`
- `outputs/autocontract_h7_decisions.csv`
- `outputs/autocontract_h7_summary.csv`
- `outputs/autocontract_h7_adapter_manifest.json`
- `outputs/autocontract_h7_adapters.md`

## 16. 第九轮更新：H7B 冻结 release-version holdout

更新日期：2026-07-28

### 16.1 预注册与冻结

发现三个仓库的 HEAD 与 H6 commit 完全相同后，放弃把 HEAD 伪装成新 holdout，改用未下载过的
release commit：MONAI 1.6.0、MMDetection v3.3.0、DALI v1.53.0。下载目标源码之前固定：

- H7 analyzer SHA256：`29084054dd86c215de7e8767ff23dcf23f32ae75604dbf1aa64084f9893fdcb5`；
- adapter manifest SHA256：`2b00443dfc9454417558d1d58c2021e90706df9aa3f96e680413d25f2d78418a`；
- oracle SHA256：`7a0440b205ea4d167ee42ab07fd7a12176e734d82cbe5cf69f1e94e7e9260a32`；
- 14 个评估单元和四条门槛。

冻结前最后一个结构调整是把 adapter 选择从具体 source ID 改为 `monai_*` / `mmdet_*` framework
namespace；旧 H7A 校准仍为 12/12。源码打开后没有修改 analyzer 或 adapter。

### 16.2 一次性结果

| 指标 | 门槛 | 结果 |
|---|---:|---:|
| Decision accuracy | 描述性 | 14/14 (100%) |
| Known-unsafe false accepts | 0 | 0 |
| Supported safe recall | ≥70% | 3/3 (100%) |
| Unsupported reason coverage | 100% | 2/2 (100%) |
| Reason-category accuracy | ≥90% | 14/14 (100%) |

**H7B blind gate：PASS。** 新 safe 单元 `RandomShift` 被接受；新 unsafe 单元 `CachedMixUp` 被识别为
many-to-one + combine lineage + execution-state write。`CachedMosaic` 得到相同的三重拒绝证据，DALI
两个 unsupported 单元均返回具体 Unknown reason。

### 16.3 证据边界

这是 release-version holdout，不是完全独立的新项目/新框架 holdout。`RandomShift` 和 `CachedMixUp`
没有进入 H7A 的评估单元，但 H6 复盘时曾打开过相同路径的另一版本源码。因此它能支持“冻结规则具有
跨版本和新增算子迁移能力”，不能支持“对未见工程生态普遍泛化”。

H7 overall 仍为 **INCOMPLETE**：adapter 的 10 条结构规则尚未与逐算子 EffectV3 标注做真实人工计时。
下一实验应测量 adapter setup time、每个新增算子的 marginal review time、自动解析率和 break-even
operator count；同时另选完全独立 package 做 fail-closed transfer。

新增文件：

- `experiments/autocontract_h7b_holdout.py`
- `outputs/autocontract_h7b_freeze.json`
- `outputs/autocontract_h7b_oracle.json`
- `outputs/autocontract_h7b_sources.csv`
- `outputs/autocontract_h7b_decisions.csv`
- `outputs/autocontract_h7b_summary.csv`
- `outputs/autocontract_h7b_holdout.md`

## 17. 第十轮更新：H7C TorchIO 独立框架与成本 pilot

更新日期：2026-07-28

H7C 选择此前未进入 corpus 的 TorchIO v1.0.2。源码 blob 打开前预注册 calibration/holdout split、
决策与 reason 门槛、adapter setup/manual review/marginal review 计时方法及 break-even 公式。

generic analyzer 在四个 calibration 单元上 safe recall 为 0。六条 TorchIO 结构规则将 Subject 建模为
一个逻辑样本，将 SpatialTransform/IntensityTransform 分别映射为 typed-subrecord effect，校准 4/4。

冻结后的七单元 holdout 得到：unsafe false accept=0、safe recall=5/5、决策7/7，但 reason-category
accuracy=6/7=85.7%，低于预注册90%。`MonaiAdapter` 被安全拒绝，但错误归因为 user callable，而不是
external-framework delegation。**H7C transfer gate：FAIL**，不在同一 holdout 上修复重跑。

adapter setup 代理时间为178.2秒；人工源码确认均值/中位数为13.322/11.626秒每算子。break-even
为13.48–15.47个算子；50算子预计节省为72.5%（均值）或68.4%（中位数），所以70%成本门槛
INCONCLUSIVE。计时仅为单 AI 研究者工程代理，不能声称人类 annotation reduction。

本轮提出 EffectV4 的两个候选字段：`record_scope` 与 `delegation_kind`。详见：

- `.research/semantics_safe_reconfiguration/h7c_torchio_postmortem.zh-CN.md`
- `experiments/autocontract_h7c_torchio.py`
- `experiments/autocontract_h7c_holdout.py`
- `experiments/autocontract_h7c_cost.py`
- `outputs/autocontract_h7c_protocol.json`
- `outputs/autocontract_h7c_freeze.json`
- `outputs/autocontract_h7c_holdout.md`
- `outputs/autocontract_h7c_cost.md`

## 18. 第十一轮更新：EffectV4 与 H7D TorchGeo 零源码 holdout

更新日期：2026-07-28

将 H7C 全部11个单元转为 calibration 后，EffectV4 引入 `record_scope` 和 `delegation_kind`，在 TorchIO
上达到 decision/reason 11/11。随后依据公开文档、未读仓库源码编写 TorchGeo/Kornia 五条 adapter
规则，并冻结 v0.9.0 commit、五个单元、代码/manifest/protocol 哈希与门槛。

正式 H7D 得到 unsafe false accept=0、safe recall=75%、resolved coverage=80%，但 reason accuracy=80%
低于90%，所以 **H7D FAIL**。`SatSlideMix` 的 one-to-many batch expansion 被正确拒绝；错误来自
`Rearrange` 被 protocol 错绑到 `spatial.py`，实际位于 `temporal.py` 并被顶层模块 re-export。

失败后的路径修正 counterfactual 在不改 adapter 时会正确解析并接受 `Rearrange`，但不计入正式结果。
由此新增 blind protocol 要求：冻结 public symbol、export module、defining module 与 source hash 的映射，
并在任何 analyzer 运行前验证。

新增文件：

- `experiments/autocontract_h7d_effect_v4.py`
- `experiments/autocontract_h7d_torchgeo.py`
- `outputs/autocontract_h7d_v4_calibration.md`
- `outputs/autocontract_h7d_v4_manifest.json`
- `outputs/autocontract_h7d_protocol.json`
- `outputs/autocontract_h7d_freeze.json`
- `outputs/autocontract_h7d_torchgeo.md`
- `.research/semantics_safe_reconfiguration/h7d_torchgeo_postmortem.zh-CN.md`
