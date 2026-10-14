# P5V：DTD 数据集与隔离 split 设计（no-data）

## 当前状态

本文件只完成 P5V 的数据集选择与 split 规则设计。状态为 `design_only_no_data`：未下载或读取 DTD，未枚举样本，未生成实际 manifest，未运行 profiling、训练、benchmark、smoke 或 launcher，也不产生新的科学结果。

本设计继承 P5T/P5U 的全部边界：P5T 的 8 个 calibration-only points 不参与数据集、cell、阈值或结果选择；P5S 的 benefit No-Go 不被推翻；v11–v13 失败现场及 P5T canonical 工件不得修改、复用或清理。任何真实数据访问或 P5V 正式运行仍需用户再次明确授权。

## 数据集决策

主数据集选择 **Describable Textures Dataset（DTD）r1.0.1，官方 partition 1，category 标签**。

选择理由：

- 官方资料给出 5,640 张真实图像、47 个类别、每类 120 张，图像尺寸约为 300×300 至 640×640；不是把 32×32 小图强行放大后伪装成高分辨率 workload。
- 官方提供 10 套预定义 partition；每套均按每类 40 张 train、40 张 validation、40 张 test 划分，便于预先固定且保持类别平衡。
- 数据集页面明确供计算机视觉研究使用，下载包约 625 MB；本科阶段在单机上可管理。
- 固定的 torchvision 0.15.x runtime 已提供 `torchvision.datasets.DTD(split=..., partition=...)` 接口；实际导入、archive identity 和兼容性仍需在获授权后的 no-data/data preflight 中绑定，当前不把网页说明当成本机验证结果。
- DTD 的纹理分类任务对局部 crop 有实际含义，同时允许固定 `Resize(shorter_edge=512)` 后安全覆盖 crop 224/448 两个 P5U cell。

未选择的候选：

| 候选 | 优点 | 本轮不选原因 |
|---|---|---|
| Oxford-IIIT Pet | 37 类、约 7,349 张、规模约 800 MB、标签清楚 | torchvision 只直接暴露 trainval/test；仍需额外拆分，类别/姿态差异也会增加小样本任务波动 |
| Food-101 | 101,000 张、真实分类任务 | 数据、类别和 CPU 训练规模过大；会把主要精力从安全重排转成数据与训练成本 |
| CIFAR-10 | 小、易下载、标签成熟 | 原图 32×32；放大到 448 会人为制造预处理工作，不能诚实回答高分辨率场景的动机 |
| DIV2K | 已有 P5S/P5T 资产、真实高分辨率 | 没有分类标签；pseudo label 只能作执行 trace，不能回应老师提出的模型结果问题 |

官方依据：

- DTD 数据页：`https://www.robots.ox.ac.uk/~vgg/data/dtd/`
- DTD 论文：`https://www.robots.ox.ac.uk/~vgg/publications/2014/Cimpoi14/cimpoi14.pdf`
- torchvision DTD 接口：`https://docs.pytorch.org/vision/0.13/generated/torchvision.datasets.DTD.html`

## 固定的四类数据用途

只采用官方 **partition 1**；不得查看其他 9 个 partition 的实验表现后换 partition。

| 研究用途 | 官方来源 | 预期数量 | 允许用途 |
|---|---|---:|---|
| profile/calibration | `train1.txt` 每类固定抽 10 张 | 470（47×10） | 仅 P5V baseline profiling、cell 资格判断、target/contrast 选择 |
| effect-evaluation | `train1.txt` 每类剩余 30 张 | 1,410（47×30） | 仅未来 A/B/C/D 性能比较；未来三 seed 任务训练也只能从此 split 取训练 batch |
| task-validation | 官方 `val1.txt` 全部 | 1,880（47×40） | 仅任务层 secondary sanity check 的评价，不参与 profiling、候选选择或模型更新 |
| test | 官方 `test1.txt` 全部 | 1,880（47×40） | P5V/P5W 全阶段禁止实验访问或报告 |

官方 archive 可能以单包形式把 test 文件放在本地；这不授权实验代码使用它们。study-level 代码不得解析 `test1.txt`，不得按 test relative path resolve、stat、hash、decode 或交给 DataLoader。若将来需要正式 test 评价，必须另立阶段、另行授权，且不能回写本轮选择。

P5V 产生的任何模型/优化器状态一律丢弃，不得初始化 P5W。P5W 的任务层训练从相同的预注册初始化开始，只在 effect-evaluation 上更新参数，并只在 task-validation 上评价。若任何两个允许 split 间发现重复 relative path 或重复内容 SHA-256，first-error stop，不移动样本补洞。

## train1 的确定性二次划分

当前不读取 `train1.txt`；只冻结未来 manifest 的生成算法。

1. 读取官方 partition 1 的 `train1.txt`，要求恰好 47 类、每类恰好 40 个 canonical relative paths；不满足即停止。
2. canonical relative path 使用官方大小写和 `/` 分隔，不包含本机绝对路径。
3. 对每个类别独立计算：

```text
split_key = SHA256(
  UTF8("autocontract.p5v.dtd.partition1.split.v1"
       + NUL + class_name
       + NUL + canonical_relative_path)
)
```

4. 每类按 `(split_key, canonical_relative_path)` 升序排列；前 10 张进入 profile/calibration，其余 30 张进入 effect-evaluation。
5. 不根据图像尺寸、decode 时间、模型结果或 P5T/P5S 数值调整划分。
6. 获授权后的实际 manifest 必须为每个允许样本记录 split、class、label、relative path、bytes、SHA-256、width、height，并绑定官方 archive、annotations 和生成器的 SHA-256。

这一定义保证类别平衡和可复现，但不声称它能消除内容难度差异。profile 只负责 workload 选择，不能变成 effect evidence。

## 与现有 AutoContract 成果的绑定

本轮不扩大算子族，只复用已通过边界验证的：

```text
Normalize([0.45, 0.40, 0.35], [0.25, 0.30, 0.35], inplace=False)
↔ RandomCrop(size, padding=None, pad_if_needed=False)
```

固定前缀为：RGB JPEG decode → `Resize(shorter_edge=512)` → float32 scale-to-[0,1] → domain guard。`Resize`、decode、dtype conversion 和 guard 不进入可移动区段。P5V baseline 始终为 `Normalize → RandomCrop`；crop 仅取 P5U 预注册的 224 或 448。

运行前必须将 Resize 的 interpolation/antialias 语义、torchvision 版本、RGB/EXIF 处理、Normalize 参数、crop 参数和 receipt source/config/domain/RNG binding 固定到实际 manifest/freeze。DTD 的使用不把已有 receipt 自动升级为新环境下的证明。

分类标签固定为 47 类 category label；class-to-index 映射按官方类别名的确定性排序写入实际 manifest。P5V 的 MobileNetV3-small/ResNet18 输出维度相应为 47。P5V 只做 baseline forward/backward/optimizer step 的时间分解，不做完整收敛评价。

## 运行前仍未闭合的事项

以下 blocker 尚未解决，因此现在不得执行 P5V：

1. 用户尚未授权下载/读取 DTD 或正式运行 P5V。
2. 官方 archive 与 annotations 的实际 SHA-256、文件清单及许可记录尚未形成。
3. 四类 split 的实际 write-once manifest 尚未生成并绑定；当前只有算法和预期数量。
4. fixed Python/torch/torchvision/Cedar identity、Resize 细节、batch size、steps per block、环境/电源/温度门尚未写入 P5V execution freeze。
5. 本机磁盘、内存和依赖兼容性尚未做获授权后的 preflight。
6. P5W 的任务级 non-inferiority margin 仍是 P5W freeze 前 blocker，不阻塞 P5V baseline profiling。

## 允许与禁止的结论

当前只允许声称：DTD 被选为 P5V 的预注册数据集候选，四类用途和确定性划分算法已经设计。

当前禁止声称：数据已取得、split 已实例化、DTD 上存在输入瓶颈、AutoContract 在 DTD 上加速、模型指标保持、结果可泛化，或任何 P5V/P5W Go/No-Go。

