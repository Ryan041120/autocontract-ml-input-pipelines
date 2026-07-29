# Cachew / Pecan 后续优化研究备忘录

更新日期：2026-07-26

## 结论先行

当前最值得继续的方向，不是再做一个“自动缩放 + 缓存 + 重排”的大一统系统，而是研究：**当训练过程中的 CPU 竞争、网络状态、数据处理开销或资源价格发生变化后，如何检测原执行计划已经失效，并在考虑重配置开销的前提下安全地重新优化。**

暂定题目：

> **Pecan-RT: Reconfiguration-aware Online Adaptation for ML Input Pipelines**
> 面向非平稳训练环境、考虑重配置代价的 ML 输入流水线在线自适应系统

经过新一轮对抗性查重，这个方向必须进一步收窄：**动态调 DataLoader worker、状态感知资源调度和按变化扩缩 loader 本身已经不是开放问题。** 当前只保留一个条件性候选——对整个输入计划做带估计置信度、失败探测预算、显式切换成本和回滚退化上界的安全在线重优化。正式立项前必须通过本文第 5.2 节的负结果复核和 `.research/topic_dossier.md` 中的升级/终止测试。

## 1. 已有工作把什么做掉了

| 工作 | 已解决的问题 | 对新工作的边界 |
|---|---|---|
| [Cachew (ATC 2022)](https://www.usenix.org/system/files/atc22-graur.pdf) | 将输入处理服务化；根据 batch time 扩缩远端 worker；根据 profiling 在重算、source cache、full cache 之间选择 | 不能把“自动扩缩容或自动缓存”本身当作新点 |
| [Pecan (ATC 2024)](https://www.usenix.org/conference/atc24/presentation/graur) | AutoPlacement 搜索 local/remote worker 组合；AutoOrder 按 transformation 特征重排；论文报告平均降低 87% preprocessing cost | 不能只做 local/remote 混合放置或按 inflation factor 重排 |
| [cedar (PVLDB 2025)](https://www.vldb.org/pvldb/vol18/p488-zhao.pdf) | 用统一优化器组合重排、缓存、融合、offloading、prefetch；运行时 Scaler 持续调整并行度和执行 variant | “统一这些优化”已不够新；应盯住静态执行计划在环境变化后是否失效 |
| [Plumber (MLSys 2022)](https://proceedings.mlsys.org/paper_files/paper/2022/hash/d0e90e9a9310570dfa643aa3b2da6e89-Abstract.html) | 基于可解释模型调 parallelism、prefetch、cache | 不能只做一个普通 profiler/tuner |
| [A-Dloader (IEEE CLOUD 2022)](https://par.nsf.gov/servlets/purl/10404709) | 多个 DDL 作业运行时动态分配本地 DataLoader worker，考虑 CPU/I/O 竞争 | 只做动态调整本地 worker 数，创新风险高 |
| [DART (FGCS 2026)](https://doi.org/10.1016/j.future.2025.108303) | 用状态估计在 epoch 边界联合调整 dataset shard、batch size、DataLoader worker 与学习率，并限制更新速率 | “状态感知动态 worker 调节”已经被直接占据；必须比较其安全性和动作空间边界 |
| [MegaScale-Data (EuroSys 2026)](https://doi.org/10.1145/3767295.3803568) | 面向多源 LFM 数据按混合比例动态扩缩 Source Loader，支持 live resharding，并分析 rescaling cost | “动态扩缩 + 切换成本”也不够新；剩余空间只能是 whole-plan 的置信度安全试探与回滚 |
| [GiPH (MLSys 2023)](https://proceedings.mlsys.org/paper_files/paper/2023/hash/3e3eec95971350490e37a076fdc100ad-Abstract-mlsys2023.html) | 面向变化的异构设备集群学习通用任务放置策略 | 如果用学习方法做 placement，需要说明 ML 输入流水线特有的状态、约束和切换代价 |
| [Youmu (MLSys 2025)](https://proceedings.mlsys.org/paper_files/paper/2025/hash/136b9a13861308c8948cd308ccd02658-Abstract-Conference.html) | LLM 训练直接读取 columnar data，减少格式转换和内存占用 | LLM 数据格式/I/O 是另一条较窄但可行的路线 |
| [Seneca (FAST 2026)](https://www.usenix.org/conference/fast26/presentation/desai) | 并发多媒体训练中的多形态缓存分区与机会式采样 | “多租户缓存分区”已经出现强相关新工作 |

### 关键证据

1. Pecan 的论文把 AutoPlacement 描述为在训练前几轮搜索并收敛；其源码进入 `STABLE` 状态后直接保持原 worker 数，不再重新探索。对应代码在 [local_worker_decision_utils.cc](https://github.com/eth-easl/cachew/blob/pecan/tensorflow/core/data/service/easl/local_worker_decision_utils.cc#L294-L298) 第 294–298 行。
2. cedar 明确把复杂的重排、缓存、融合、offloading 放在 **Static Optimization**，运行中的 Scaler 主要负责按照既定计划调 parallelism/variant、满足训练吞吐需求。它能适应吞吐需求，但论文没有系统评估“运行中统计特征变化后，重新搜索整个计划”的收益、切换开销与稳定性。
3. 因此，最合理的缺口不是笼统的“dynamic”，而是：**何时触发跨优化维度的 plan re-optimization；改变哪些部分；如何证明切换值得；如何避免振荡和语义/准确率风险。**
4. DART 与 MegaScale-Data 是当前最危险的相近工作。前者已经解决 noisy state 下的限速在线协同调度，后者已经解决动态 source scaling、live resharding 并讨论 rescaling cost。因此，本题不能再把 change detector、worker scaling 或 reconfiguration cost 单独列为贡献。

## 2. 核心研究问题

设当前输入流水线执行计划为 `p`，运行环境状态为 `s_t`。计划不仅包括 worker 数，还可能包括：

- local/remote worker 比例；
- 每个 transformation 在哪里执行；
- cache 的位置和内容；
- transformation order、fusion 和 prefetch；
- 每个算子的并行度。

当 `s_t` 变化时，原来的 `p` 可能不再合适。但切换到新计划 `p'` 也有代价：worker 冷启动、缓存变冷、队列排空、数据重分片、重新 profiling，甚至短暂训练停顿。

可以把决策写成：

```text
未来 H 个窗口继续使用 p 的预计成本
    >
未来 H 个窗口使用 p' 的预计成本
  + 重配置成本 K(p → p')
  + 安全裕量
```

待回答的研究问题：

1. 哪些 runtime signal 能可靠地区分瞬时噪声和真正的 phase/environment change？
2. 只调 worker 数什么时候够用，什么时候必须重选 operator placement/cache/order？
3. 如何估计重配置后未来一段时间的收益，避免来回切换？
4. 如何在不破坏随机增强、样本顺序和 exactly-once 等语义的情况下切换？
5. 在多少变化频率、作业长度和资源价格下，在线重优化才值得？

## 3. 建议系统设计：两层控制器

### 快速控制环：秒级资源调整

每 10–30 秒执行，优先做低风险动作：

- 增减 local/remote worker；
- 调每个 operator 的 parallelism；
- 调 prefetch buffer；
- 目标是快速恢复 GPU/TPU 的数据供给。

这部分继承 Cachew/Pecan/cedar 的思想，不作为主要新颖点。

### 慢速控制环：epoch 或安全点重选计划

只有检测到持续变化并且预计收益覆盖切换成本时才触发：

- 重选 operator 的 local/remote placement 或 pipeline split；
- 调整 cache 位置；
- 必要时重新排序或融合 transformation；
- 失败或收益不达标时自动 rollback。

建议监控状态：batch time、GPU input stall、输出 prefetch queue、per-op latency、input/output bytes、CPU 利用率、内存带宽、I/O wait、网络带宽/RTT、remote worker 单价。

建议先用 EWMA/CUSUM/ADWIN 一类变化检测，不要为了“AI for Systems”强行上强化学习。只有当规则/模型控制器在复杂状态下明显不够，再研究 contextual bandit 或 model-based RL。

## 4. 可检验假设

- **H1：** Pecan 的一次性收敛在 host CPU contention、网络拥塞或 preprocessing phase 改变后，会出现显著额外成本或 GPU stall。
- **H2：** 仅重新调整 worker 数，在 operator bottleneck 或网络/计算比例变化时不如重选 operator placement。
- **H3：** 加入切换成本、迟滞和 cooldown 的控制器，可以接近动态 oracle，同时显著减少无效重配置。
- **H4：** 两层控制比每次变化都重跑完整优化器更稳定，且大部分时间只需要快速控制环。

## 5. 已完成的初步可行性实验

我写了一个明确标注为 **toy、不是论文复现** 的非平稳仿真：

- [实验脚本](experiments/dynamic_reoptimization_toy.py)
- [汇总结果](outputs/dynamic_reoptimization_summary.csv)
- [完整 trace](outputs/dynamic_reoptimization_trace.csv)

仿真依次构造 steady、host contention、network congestion、augmentation-heavy 四个阶段。比较：

1. `one_shot_stable`：初始找到 placement 后不再改变；
2. `change_aware`：连续三个窗口检测到偏移，且未来 30 个窗口预计收益覆盖 2 秒重配置成本后才切换；
3. `phase_oracle`：每个阶段都知道最优 placement 的理想上界。

结果：

| 策略 | 总 batch 时间 | 归一化成本 | 重配置次数 |
|---|---:|---:|---:|
| one-shot stable | 326.05 s | 1.6172 | 0 |
| change-aware | 220.07 s | 1.3789 | 3 |
| phase oracle | 210.39 s | 1.3211 | 0 |

在这个人为构造的场景中，change-aware 相对 one-shot 将时间降低 **32.5%**、成本降低 **14.7%**，成本只比 oracle 高 **4.4%**。这只能说明研究假设“值得做真实实验”，不能作为论文效果结论，因为阶段参数和性能模型都是合成的，而且重优化器使用了理想化的当前阶段估计。

### 5.1 本机真实 CPU contention 微基准

在 toy 仿真之后，我又完成了一轮真实执行实验：

- 硬件：AMD Ryzen 5 7535HS（6 核 12 线程）与 NVIDIA RTX 4060 Laptop GPU；
- 软件：PyTorch 2.4.0 + CUDA 12.4；
- workload：DataLoader worker 在 CPU 上生成并执行多轮 synthetic image augmentation，小型 CNN 在 GPU 上训练；
- 扰动：额外启动 4 个独立进程持续占用 CPU 与内存带宽，模拟 checkpointing、logging 或 collocated job；
- 测量：0/1/2/3/4/6/8 个 DataLoader worker，记录 mean/P95 batch time、input wait、stall ratio 和 loader startup；
- 性质：这是一个真实运行的 mechanism microbenchmark，但仍然不是 Cachew/Pecan 复现，也没有使用真实数据集。

文件：

- [实验脚本](experiments/real_cpu_contention_benchmark.py)
- [完整 worker sweep](outputs/real_cpu_contention_profiles.csv)
- [完整 sweep 图](outputs/real_cpu_contention_profiles.png)
- [6/8-worker 定向复测](outputs/real_cpu_contention_profiles_confirm68.csv)
- [切换回本分析](outputs/real_cpu_contention_break_even_confirm68.csv)

完整 sweep 的关键结果：

| 场景 | 6 workers | 8 workers | 当前最优 |
|---|---:|---:|---:|
| normal | 8.24 ms/batch | 8.18 ms/batch | 8（与 6 很接近） |
| CPU/memory contention | 19.51 ms/batch | 27.85 ms/batch | 6 |

为避免短测偶然性，我又只对 6/8 workers 各测量 50 个 batch：

| 场景 | 6 workers | 8 workers | 结论 |
|---|---:|---:|---|
| normal | 13.19 ms/batch | 11.16 ms/batch | 8 更好 |
| CPU/memory contention | 21.35 ms/batch | 26.27 ms/batch | 6 更好 |

这说明同一流水线的 worker optimum 确实会随 host contention 移动，而且 worker 过多时会因资源竞争变慢。更重要的是，竞争状态下创建 6-worker DataLoader 的实测 startup 约为 10.2 秒；从固定 8-worker 切到 6-worker 每个 batch 节约约 4.93 ms，因此要运行约 **2,071 个 batch（约 49,700 个样本）**才能覆盖这次重配置成本。用固定 8-worker 的速度换算，break-even time 约为 **54 秒**。

在假设正常和竞争阶段各持续 5,000 个 batch 的 trace replay 中：

- 一直固定 8-worker：总时间约 187.2 秒；
- 竞争后切到 6-worker，并计入 10.2 秒 startup：总时间约 172.7 秒；
- 改善约 7.7%。阶段更长时收益继续增大；阶段短于约 2,071 batch 时则不应切换。

所以真实实验不仅支持“最优配置会变化”，也支持本题最关键的第二点：**变化检测本身不够，控制器必须预测变化还能持续多久，并显式比较未来收益与重配置成本。**

离线结果只说明“这个现象值得做连续实验”，不能证明离线 profile 能迁移到真实运行阶段。下一节的连续实验恰好推翻了朴素的乐观判断。

### 5.2 连续训练中的负结果：朴素自适应显著变慢

我把正常阶段与 contention 阶段连成一次连续训练，并比较：

- `fixed_8`：始终使用 8 个 worker；
- `change_aware`：检测到 batch-time shift 后，真实关闭 8-worker DataLoader，创建 6-worker DataLoader 做 probe；只有预测剩余收益覆盖重配置成本才保留，否则回滚到 8 worker。

文件：

- [连续实验脚本](experiments/online_adaptation_experiment.py)
- [汇总结果](outputs/online_adaptation_summary.csv)
- [逐 batch trace](outputs/online_adaptation_trace.csv)
- [trace 图](outputs/online_adaptation_trace.png)

关键结果：

| 策略 | 正常阶段 mean | contention 阶段 mean | 重配置计费 | 总计费运行时间 |
|---|---:|---:|---:|---:|
| fixed 8-worker | 10.86 ms/batch | 27.68 ms/batch | 0 s | 92.49 s |
| 朴素 change-aware | 8.60 ms/batch | 25.48 ms/batch | 38.46 s | 124.12 s |

朴素自适应相对 fixed-8 **慢 34.2%**。它检测到变化后试探 6 worker，但 probe 的 batch-time 中位数约 22.63 ms，反而差于切换前 8 worker 检测窗口的约 19.03 ms，最终只能回滚。离线 sweep 中“contention 下 6 worker 更好”的结论没有稳定迁移到连续运行。

这是比正结果更重要的证据：

1. 环境状态和测量噪声会让离线 profile 失效；只按点估计切换容易选错。
2. DataLoader 的破坏式重建与 rollback 可能比稳态 batch-time 差异大一个数量级，必须完整计费。
3. 检测到 drift 不等于存在可获利的新配置；控制器必须允许“不行动”。
4. 论文问题不应再表述为“动态调 worker”，而应是“如何限制错误 probe 对真实训练造成的累计损失”。

当前结论改为 **conditional go**：只有当 DART/MegaScale-Data 全文查重确认该安全问题仍未被覆盖，并且 Linux + 真实数据的实验能同时证明静态计划存在持续损失、拟议控制器计入全部成本后不劣化，才扩成系统题目。否则转成 reconfiguration/probing 成本与不稳定性的经验研究。

## 6. 实验路线

### 第一阶段：两周内验证问题是否真实

1. 已完成单机 PyTorch DataLoader 的离线 worker sweep 与 CPU/memory contention 复测。
2. 已完成正常与竞争状态的连续训练，在运行中真实执行 8→6 probe→8 rollback；结果显示朴素 change-aware 比 fixed 慢 34.2%。
3. 下一步换到 Linux，并使用 CIFAR-10/ImageNet 子集或公开音频数据，确认失败模式与最优配置漂移能否复现。
4. 实现置信区间门控的 staged/canary probe，比较 static、周期性重调、DART-like 限速控制、朴素 change-aware 和 safe change-aware。

Go/No-Go 标准建议：至少在两类真实扰动、两个模型上，static 相比 phase oracle 有超过 10% 的 cost 或 time gap；safe change-aware 计入全部 probe/rebuild/rollback 成本后恢复其中至少一半，同时在无变化、短变化和高噪声场景相对最佳 fixed 的总时间退化不超过 2%，每阶段错误切换少于一次。

### 第二阶段：最小系统原型

优先顺序：

1. **Pecan 小改版**：给 `STABLE` 增加变化检测和重新进入 `ONLY_REMOTE/INCREASING_LOCAL` 的路径。实现快，适合验证。
2. **cedar 原型**：利用 per-Pipe trace，在变化后重新执行静态 optimizer，并加入 reconfiguration-aware objective。这更接近完整论文贡献，但工作量更大。
3. 只在证据充分后，加入 cache relocation 或 operator reordering；先做 placement + parallelism，避免范围失控。

### 正式评估

- Workloads：ResNet50、SimCLR、ASR 或 cedar 的 PyTorch/TF pipelines；至少覆盖 CV 和一类非 CV。
- 扰动：host CPU/DRAM contention、网络带宽/延迟变化、preprocessing 计算量变化、并发作业到达/退出、remote price 变化。
- Baselines：static placement、Cachew/Pecan、cedar scaler、DART-like 限速控制、周期性 full re-opt、朴素 change-aware、无切换成本的 oracle。
- Metrics：mean/P95 batch time、GPU stall ratio、训练成本、remote worker-seconds、收敛/恢复时间、probe/rebuild/rollback 时间、错误触发数、累计 regret、最坏退化、SLO violation area。
- Ablation：无置信度门控、无 hysteresis、无 reconfiguration cost、无失败 probe 预算、只调 worker、不允许 rollback。

## 7. 其他候选方向与排序

| 排名 | 方向 | 新颖性判断 | 实习可行性 | 主要风险 |
|---:|---|---|---|---|
| 1 | 非平稳环境下、考虑重配置代价的在线 plan re-optimization | 中高，但需进一步查重 | 中 | 真机扰动可能没有 toy 中明显 |
| 2 | Pecan AutoOrder 的 accuracy-safe reordering：自动推断依赖/随机性并量化数据分布变化 | 中高；Pecan 和 cedar 都留下语义提示/推断问题 | 低到中 | 需要程序分析和模型准确率大规模实验 |
| 3 | 历史任务迁移与低冷启动 profiling | 中 | 高 | 容易变成工程缓存，贡献不够深 |
| 4 | 多租户公平的缓存/worker 联合分配 | 中 | 中 | A-Dloader、Cachew、Seneca 已覆盖相邻问题，查重压力大 |
| 5 | LLM columnar/shuffle-aware 输入流水线 | 中 | 中 | Youmu 已很强，需要找到更具体的新瓶颈 |

## 8. 当前建议

先不要承诺“我要做一个完整新系统”。更合适的汇报说法是：

> 我继续查了 DART、A-Dloader、cedar 和 MegaScale-Data，发现“动态调 worker”“状态感知扩缩”和“考虑 rescaling cost”都已经有人做，不能作为新点。我又做了连续在线切换实验：离线 profile 认为 contention 下 6 worker 更好，但真实 8→6 probe→8 rollback 计入重建后，比固定 8 worker 慢 34.2%。因此我把问题收窄为：能否对整个 input plan 做带置信度、失败 probe 预算和退化上界的 staged/canary reconfiguration。下一步先精读 DART/MegaScale-Data 查清边界，再在 Linux 和真实数据上验证；若任何升级条件失败，就不做通用新系统，改成 reconfiguration 成本与不稳定性的经验研究。

这个表述把“已有工作已经占据的部分”“负实验确认的失败模式”和“仍需证明的窄假设”分开，更适合现在发给学长讨论。完整三道门判断见 [.research/topic_dossier.md](.research/topic_dossier.md)。
