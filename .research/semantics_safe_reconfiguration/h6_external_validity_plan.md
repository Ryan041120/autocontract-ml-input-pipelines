# H6 真实 GitHub 流水线外部有效性计划

更新日期：2026-07-28

## 1. 本轮研究问题

H3 在 30 个算子、10 条合成 pipeline 上通过了预先固定的门槛，但它仍可能只是
torchvision 风格 unary image transform 的过拟合。H6 要回答：

> 在不针对每个项目调整推断规则的前提下，AutoContract 能否对真实、多目标、多样本的
> ML input pipeline 保持 0 个 known-unsafe false accept，并仍保留有用的安全候选？

## 2. 已确认的真实代码来源

| 来源 | 抽取单元 | 代表的新风险 | 作为基准的原因 |
|---|---|---|---|
| [torchvision classification presets](https://github.com/pytorch/vision/blob/main/references/classification/presets.py) | train/eval，PIL/tensor，AutoAugment/RandomErasing 开关 | 格式边界、配置分支、基础随机增强 | 与 H3 最接近，作为 in-domain control |
| [timm transform factory](https://github.com/huggingface/pytorch-image-models/blob/main/timm/data/transforms_factory.py) | no-aug/train/eval，RRC/RandAugment/AugMix/NaFlex/RandomErasing | 嵌套 `RandomApply`、随机 interpolation、三阶段 split transform、sequence/patch output | 同一项目内有多种实际配置和输出类型 |
| [Ultralytics augment.py](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/data/augment.py) | `v8_transforms`：Mosaic/CopyPaste/Perspective/MixUp/CutMix/Albumentations/HSV/Flip | 一变多/多变一、dataset buffer、partner sampling、image-box-mask-keypoint 同步参数 | 直接压力测试 visitation contract 与外部可变状态 |
| [Detectron2 DatasetMapper](https://github.com/facebookresearch/detectron2/blob/main/detectron2/data/dataset_mapper.py) | train/eval mapper，crop/resize/flip，annotation/proposal/sem-seg 同步 | 文件 I/O、配置依赖、多 target read/write、变换参数 replay | 验证 contract 不能只比较 image tensor |

这四个来源已经足以暴露合成集缺失的两个核心维度：**multi-target coupling** 与
**sample-cardinality/visitation**。Albumentations 和 Kornia 可在第二批作为库级 holdout，不应先用来
调参。

## 3. H3 effect schema 必须扩展

H3 的 `(randomness, rng_source, shape, dtype, state, scope)` 对分类增强够用，但对检测/分割
流水线不够。H6 的最小 effect 应改为：

```text
Effect = {
  reads, writes,                         # image / boxes / masks / keypoints / labels / metadata
  output_random, rng_sources,
  state_scope, external_dependencies,   # instance / worker / process / dataset / filesystem
  input_cardinality, output_cardinality,# 1->1, k->1, 1->k
  target_coupling_group,                # 哪些 target 必须共享同一随机参数
  shape, dtype, layout, device,
  sample_identity_effect                # preserve / combine / split / filter
}
```

其中 `target_coupling_group` 不是普通 read/write set 的别名。例如 RandomFlip 必须让 image、box、mask
和 keypoint 使用同一个 flip decision；即使每个分支各自的输出分布都正确，独立重抽样仍会
破坏标注语义。

## 4. 对 RNG identity 和 cache key 的新义务

对 unary transform，H4 的 key 是：

```text
(base_seed, epoch, sample_id, stable_operator_id, draw_index)
```

对 Mosaic/MixUp/CutMix，必须扩展为：

```text
partner_ids = PartnerSelect(epoch, anchor_sample_id, stable_operator_id, dataset_snapshot)
random_word = PRF(base_seed, epoch, anchor_sample_id, partner_ids,
                  stable_operator_id, target_coupling_group, draw_index)
```

缓存键也必须包含所有 parent sample IDs、顺序/权重、dataset snapshot、annotation schema 与变换版本。
否则即使 pixel digest 相同，visitation 或 label lineage 也可能错误。

## 5. 冻结评估协议

### 5.1 阶段 A：调试集

只使用 torchvision train/eval 和 timm 的一条基本 train pipeline 完成 parser/schema 调试。
当规则冻结后，不得根据后续项目的答案修改规则。

### 5.2 阶段 B：holdout

- timm：RandAugment/AugMix/NaFlex/separate 变体；
- Ultralytics：`v8_transforms` 默认检测 pipeline；
- Detectron2：train/eval DatasetMapper；
- 第二批库：Albumentations 和 Kornia，只在规则冻结后加入。

### 5.3 oracle

1. 文档/源码手工 effect 标注，由第二遍 blind review 复核；
2. 同时比较 image、boxes、masks、keypoints、class labels 和 parent sample lineage；
3. 主动改变 environment、dataset buffer、worker count 与 process start method；
4. 对随机算子使用 operator-keyed replay，并分别检查 exact trace、distribution 和 visitation。

### 5.4 预先固定的通过线

| 指标 | 门槛 | 理由 |
|---|---:|---|
| known-unsafe false accepts | 0 | 与 H3 保持一致，安全不用 recall 换 |
| safe rewrite recall | ≥70% | 真实多 target pipeline 允许更保守 |
| effect-cell accuracy on resolved cells | ≥95% | 防止只靠差分测试偶然通过 |
| non-registry operator coverage | ≥60% | 必须超过人工 registry 工具 |
| holdout 人工签名减少 | ≥50% | 真实语料上仍需有明显自动化价值 |

## 6. 当前最有价值的新命题

H3 之后，论文不应只说“检测随机性并安全重排”。真实 GitHub 代码表明，更强的命题是：

> A rewrite is safe only if it preserves not just tensor values or marginal distributions,
> but also target coupling and sample lineage under operator-keyed randomness.

这个命题把 AutoContract 与传统 DBMS UDF purity/read-write analysis（包括 Opening the Black Boxes 和
LAMBDA）区分开，同时也把 H1/H2 的 trace–distribution–visitation 层级变成真正会决定结果的
系统机制，而不是概念包装。

## 7. H6A 首次实测与协议重置

首次 H6A 将 6 个仓库固定到具体 commit，不安装上游项目，而是直接对源码 AST 做保守抽取。
评估包含 3 个 debug 单元和 17 个 holdout 单元。结果为：

| Split | Units | Effect-cell accuracy | Coupling FN | Many-to-one FN |
|---|---:|---:|---:|---:|
| debug | 3 | 100.0% | 0 | 0 |
| holdout | 17 | 71.6% | 0 | 0 |

因为 holdout accuracy 低于 H6A 的 80% schema-feasibility 线，**H6A v1：FAIL**。这不是完整 H6
的 95% 论文门槛；它说明当前 effect language 在进入 rewrite validator 前就必须改写。

29 个错误 effect cell 的分布为：

- `targets`：14；
- `rng_sources`：8；
- `target_coupled`：5，均为保守误报，非漏报；
- `external_dependencies`：2。

两个安全关键项目暂时没有失守：所有已知 target-coupled 单元均被识别，所有
Mosaic/MixUp/CutMix/CopyPaste 均未被误判为 `1->1`。但不能因此声称 H6 安全性已通过。

### 7.1 v1 暴露的 schema 缺陷

1. `targets` 把 read 和 write 合并，因此会把仅出现在类型检查、默认 no-op 基类或
   annotation 读取中的 target 误报为被改写。
2. Compose/OneOf/AugmentationSequential 的 target 集不是固定集合，而是由 child transform、
   `additional_targets` 或 `data_keys` 决定的参数化签名。
3. `rng_sources` 无法区分“本层直接消耗”和“委托给 child transform”；把 `delegated`
   与 concrete RNG source 直接求并会制造虚假不一致。
4. Ultralytics Albumentations wrapper 在构造期写 `NO_ALBUMENTATIONS_UPDATE` 环境变量，但这不等于
   逐样本输出依赖环境状态。effect 必须区分 construction 和 execution phase，也必须区分
   external read 和 write。

### 7.2 v2 effect language

```text
EffectV2 = {
  construction: {external_reads, external_writes, state_writes},
  execution:    {reads, writes, external_reads, external_writes},
  rng:          {direct_sources, delegated_sources, replay_key},
  target_signature: {fixed | parametric(child/config)},
  target_coupling_groups,
  input_cardinality, output_cardinality,
  sample_identity_effect
}
```

只有 execution-phase effect 参与逐样本 reorder/cache admission；construction effect 另行决定算子是否可
clone、hoist 或在 worker 间共享。这个 phase separation 是 H6A 比单纯加更多 token rule 更有研究价值的结果。

### 7.3 新的 blind holdout

由于 v1 错误已经被查看，torchvision/timm/Ultralytics/Detectron2/Albumentations/Kornia 全部降为
calibration corpus，不再冒充 blind holdout。v2 规则冻结后才能打开下列已密封 commit：

- MONAI：`3ee058bdd16dd4a566d23d3f84687c3c35268a36`；
- MMDetection：`cfd5d3a985b0249de009b67d04f37263e11cdf3d`；
- NVIDIA DALI：`1a8328edbc8db6786d764e309d519a3926171d19`。

密封清单保存在 `outputs/autocontract_h6_blind_holdout.csv`。
