# AutoContract 当前实验总结

更新日期：2026-07-29

## 1. 一句话结论

**课题的机制可行性、性能和合成语义门槛已通过；EffectV7/Kornia H7H 获得一次性正式盲测 PASS。H7J/H7K 封住 TOCTOU 并缓存静态 proof，H7L 用 signed provenance 消除 caller 自报 lineage。H7M 进一步以 signed Merkle batch、fenced lease 和 buffered release 摊销事务并处理 stale worker：generic 7/7、Kornia 12/12、真实 crash/ack-loss 6/6、MixUp ordered partner 8/8。N=4 的每样本 consumer 成本为 H7L 的 0.488×，真实 Kornia H7M/H7L=0.835×且 10/10 轮更快；但 N=1 为 1.911×，并且 registry commit 仍不等于 optimizer side-effect exactly-once。下一关键问题是将 batch provenance、DataLoader position 与 model/optimizer state 纳入一致 checkpoint。**

因此当前状态是：

> go for an adapter-assisted research prototype; no-go for framework-agnostic arbitrary-Python inference.

## 2. 各假设的结果

| 假设/阶段 | 要回答的问题 | 核心结果 | 判定 |
|---|---|---|---|
| H1 | 只看输出随机性是否会漏掉危险 effect | fixed-sigma GaussianBlur 输出确定但仍推进 Torch RNG；联合检测 RNG state transition 能发现 | PASS |
| H2 | stable operator RNG 能否使 reorder/cache hit 不改变 trace | 3 组 global-RNG 下不安全的重排在 operator-keyed RNG 下逐元素一致；安全前缀 cache trace match 100% | PASS |
| H3 | 自动 effect inference 能否减少人工标注且不放过 unsafe rewrite | 30 算子、10 pipeline、37 候选；hybrid 接受 15/15 safe、拒绝 22/22 unsafe；人工签名减少 76.7% | PASS（合成 corpus） |
| H4 | stateless/operator-keyed RNG 的性能开销是否可接受 | 完整 pipeline 相对 native 为 -13.28% 开销（即更快）；随机后缀 -11.48%；MMD permutation `p=0.485` | PASS |
| H5a | 真实 JPEG/DataLoader 上安全 cache 是否有系统收益 | 600 JPEG，workers 0/2/4；稳态加速 3.41x/2.73x/2.52x，trace 100% | PASS |
| H5b | 真实 model forward/backward/SGD 路径是否仍有收益 | ResNet-18 热 cache 18.79s -> 13.61s，1.38x；data wait 5.80s -> 1.08s；batch/loss/model digest 完全一致 | PASS |
| H6A v1 | H3 schema 能否直接迁移到真实 GitHub 代码 | 6 仓库、20 单元；debug 100%，holdout 71.6%；coupling FN=0，many-to-one FN=0 | **FAIL** |
| H6 EffectV2 blind | phase-aware schema 能否在未见框架上泛化 | MONAI/MMDetection/DALI，12 单元；accuracy 76.1%，9 个关键漏检，2 个 unsafe false accept | **FAIL / strong claim no-go** |
| H7A adapters | `Unknown` 安全门与框架语义能否修复 blind 失败模式 | 在已打开的 H6 集上校准：12/12 决策正确，unsafe false accept=0，safe recall=2/2，unsupported reason=2/2 | **PASS（机制校准，非 blind）** |
| H7B frozen adapters | adapter 能否在不改规则时跨 release/新算子迁移 | 3 release、14 单元；14/14 决策与理由类别正确，unsafe false accept=0，safe recall=3/3，unsupported reason=2/2 | **PASS（release-version holdout）** |
| H7C TorchIO | 独立框架 adapter 能否安全恢复机会并摊销成本 | 7 holdout：决策7/7、unsafe FA=0、safe recall=5/5；reason 6/7；break-even 13.5–15.5 ops | **FAIL（reason gate）；cost inconclusive** |
| H7D EffectV4/TorchGeo | record scope/delegation 能否跨第二独立框架 | V4 calibration 11/11；TorchGeo unsafe FA=0、safe recall=75%，reason=80%；Rearrange source binding 错误 | **FAIL（protocol binding）** |
| H7E EffectV4/audiomentations | 修复 binding 后能否跨到音频域 | 7/7 decisions、unsafe FA=0、safe recall=100%、coarse reason=100%、classified coverage=100% | **PASS（default/unfrozen context）** |
| H7F EffectV5/imgaug | 状态角色与模式义务能否迁移到独立视觉框架 | 8 个正式单元：7/8 decisions、unsafe FA=0、safe recall=80%、coarse reason=87.5%、coverage=100% | **PASS（deterministic mode；刚好过线）** |
| H7G EffectV6/Albumentations | provenance 与具名 replay mode 能否跨到新框架 | 7/8 decisions、预注册 unsafe FA=1、safe recall=100%、reason=87.5%；分歧来自 replay-mode oracle 与 default-path reachability 混合 | **FAIL（mode/phase-conditioned oracle）** |
| H7H EffectV7/Kornia | reachable effect 能否区分同一算子的参数采样与参数重放 | 9/9 decisions、unsafe FA=0、safe recall=100%、reason/coverage/phase contrast=100% | **PASS（compatible params context）** |
| H7I lineage/composition runtime pilot | 参数记录能否绑定 lineage，且 child contracts 能否合成容器接纳 | self-test 7/7、runtime/attack 17/17、输出/RNG/梯度 trace 一致；发现 mutable-record TOCTOU | **机制 PASS；非 blind；需 atomic apply** |
| H7J sealed atomic replay | 私有 snapshot 与原子 validate-compose-apply 能否封住 TOCTOU | self-test 4/4、Kornia 12/12、并发 100/100、零调用拒绝与 operator-mutation postcheck 通过；配对性能中位 +25% | **机制/runtime PASS；非 blind；性能待优化** |
| H7K registered/owned executor | 私有 target pool 能否缓存静态 proof 并保留动态安全检查 | self-test 5/5、Kornia 14/14、并发 100/100；minimal/H7J=0.860×，minimal/direct=1.053×；pool=2 吞吐最佳 | **机制/runtime/performance PASS；非 blind** |
| H7L signed provenance/registry | 能否让 sample/epoch/partner/params lineage 不再依赖 caller 自报并跨 worker 验证 | generic 7/7、Kornia 21/21、spawn 5/5；50 次 input mutation 压力 0 错误输出；H7L/H7K=1.235× | **机制/runtime PASS；非 blind；事务成本待摊销** |
| H7M Merkle batch/fenced lease | 能否批量摊销签名/事务并在 crash recovery 后 fence stale worker | generic 7/7、Kornia 12/12、crash 6/6、MixUp 8/8；N4 consumer/H7L=0.488×，端到端 H7M/H7L=0.835× | **N≥4 机制/runtime/performance PASS；N=1 no-go；非 blind** |

## 3. 已经确定的科学结论

### 3.1 隐藏 RNG effect 是真实的

`output_random=False` 不意味着算子可以随意被跳过或重排。它仍可能消耗全局 RNG，改变后续增强的
随机轨迹。这是 AutoContract 最稳固的经验贡献之一。

### 3.2 语义契约必须分层

- trace contract：每个样本在每个 epoch 的具体输出不变；
- distribution contract：允许随机轨迹不同，但要求所选分布统计不变；
- visitation contract：样本、partner sample、标签与次数的 lineage 不变。

只比较最终 accuracy 无法代替以上任何一层。

### 3.3 性能收益与安全性是两个独立证书

H5 展示安全前缀 cache 可以显著加速，但冷 cache 的构建成本也可以使短任务变慢。因此完整系统必须同时要求：

```text
semantic certificate holds
AND
expected benefit over the remaining horizon > 0
```

但 Cachew/cedar 已经覆盖大量 cost/performance policy，所以 AutoContract 的贡献应是产生安全候选与义务，
而不是重新发明 cache cost model。

## 4. H6A 失败带来的 schema 修正

H3 的 unary-transform schema：

```text
(randomness, rng_source, shape, dtype, state, scope)
```

无法直接表达真实检测/分割 pipeline。H6A 的 29 个错误 cell 中，14 个来自 target set、
8 个来自 RNG delegation、5 个为 coupling 保守误报、2 个来自构造期/执行期混淆。

因此下一版必须是 phase-aware 的：

```text
EffectV2 = {
  construction: external_reads, external_writes, state_writes,
  execution:    reads, writes, external_reads, external_writes,
  rng:          direct_sources, delegated_sources, replay_key,
  target_signature: fixed | parametric(child/config),
  target_coupling_groups,
  input_cardinality, output_cardinality,
  sample_identity_effect
}
```

这里的重要区分是：

- construction effect 决定算子能否 clone/hoist/share；
- execution effect 决定能否 reorder/cache/fuse；
- delegated effect 必须在实例化 pipeline 时从 child operator 合成，不能伪装成固定签名。

## 5. 当前不能声称的事

- 不能声称 differential test 证明了交换律或语义等价；
- 不能声称已支持通用 Python/C++/CUDA UDF；
- 不能把已通过的 adapter-assisted GitHub holdout 外推成 framework-agnostic arbitrary-Python inference；
- 不能把 stateless RNG、UDF property inference、autocaching 或 cost-based placement 本身当作新贡献；
- 不能由当前小规模 ResNet-18/JPEG 结果推导所有 workload 都能加速。

## 6. 当前最合理的论文主线

> **AutoContract: Contract-Carrying Rewrites for ML Input Pipelines**

每个被接受的 rewrite 必须携带：

1. phase-aware effect evidence；
2. 所保证的 trace/distribution/visitation contract；
3. stable operator/partner RNG lineage；
4. cache-key/invalidation 条件；
5. 差分反例搜索结果与未解析项；
6. 由现有 cost optimizer 消费的 performance certificate。

## 7. 已完成的 H6 决策协议

1. 只在已查看的 6 个 calibration 仓库上实现并调试 EffectV2；
2. 冻结推断规则、oracle schema 和通过线；
3. 一次性打开 MONAI、MMDetection、NVIDIA DALI 的密封 commit；
4. 若 blind holdout 仍为 0 unsafe false accept，effect accuracy ≥95%、coverage ≥60%，再接入 rewrite validator；
5. 若失败，将课题收缩为 hidden/phase-crossing effect detector，不声称通用自动优化。

## 8. blind 结果后的新决策

第 7 节的一次性 blind 评估已执行，结果失败。因此后续不再继续追求“一套规则自动理解任意框架”，
而改为：

```text
framework-neutral Effect/Contract IR
  + conservative generic analyzer -> Unknown(reason)
  + amortized framework adapter
  + contract-aware rewrite validator
```

该路线仍能保留 H1–H5 的所有证据，并且与 blind 失败暴露的真实框架差异一致；但论文中必须把 adapter
成本、unsupported rejection 和跨项目泛化分别评估。

## 9. H7A 结果与下一决策点

EffectV3 在 EffectV2 基础上增加 `execution_state_writes`，分析结果改为：

```text
Resolved(EffectV3, adapter, evidence)
| Unknown(reason...)
```

MONAI adapter 只提供 `self.R`、`__call__`、parametric container 和单样本 lineage 四类框架事实；
MMDetection adapter 只提供 `transform`、外部基类摘要、results schema、RNG 映射、`mix_results`
lineage 与 `results_cache` lifecycle 六类事实。DALI 没有 adapter，因此保持 `Unknown` 并拒绝。

在已经打开、已经复盘的 H6 blind 集上，H7A 得到：

- 12/12 validator 决策正确；
- known-unsafe false accept = 0；
- supported safe recall = 2/2；
- unsupported reason coverage = 2/2；
- `CachedMosaic` 由 many-to-one、combine identity 和 execution-state write 三个理由拒绝。

这是 post-blind mechanism calibration，不得改写成新的 holdout 结果。10 条结构规则覆盖当前 10 个
supported 单元，描述性的 effect-cell-equivalent reduction 为 93.8%，但还没有人工时间数据，所以
adapter 成本门槛仍未通过。

下一轮必须先冻结 H7 analyzer/adapter manifest，再选择未参与开发的 MONAI/MMDetection 项目或版本；
不改 adapter 地执行一次性 H7B holdout。只有 H7B 达到 unsafe false accept=0、safe recall≥70%、
unknown reason coverage=100%，并补齐真实 annotation-time 对照，才可把总体状态从 conditional go 升级。

## 10. H7B 冻结 holdout 结果

H7 analyzer、adapter manifest、oracle、release commit、14 个单元和门槛均在下载源码前固定并哈希。
冻结版本为 MONAI 1.6.0、MMDetection v3.3.0 与 DALI v1.53.0；运行后 analyzer、manifest 和 oracle
哈希再次核验一致。

| 指标 | 门槛 | 结果 | 判定 |
|---|---:|---:|---|
| Known-unsafe false accepts | 0 | 0 | PASS |
| Supported safe recall | ≥70% | 3/3 (100%) | PASS |
| Unsupported reason coverage | 100% | 2/2 (100%) | PASS |
| Reason-category accuracy | ≥90% | 14/14 (100%) | PASS |

新增的 `RandomShift` 被正确接受，新增的 `CachedMixUp` 因 many-to-one、combine lineage 与
execution-state write 被拒绝。DALI 仍无 adapter，因此两个单元均以具体 `Unknown(reason)` 拒绝。

**H7B blind gate：PASS；H7 overall：INCOMPLETE。** 原因有两点：

1. 这是 release-version/operator transfer；H7A 没评估过两个新增算子，但 H6 复盘时打开过同一路径的
   较新源码，不能称为完全独立 project holdout；
2. 10 条框架规则相对逐单元 EffectV3 标注的 93.8% reduction 只是结构计数，还没有真实
   annotation-time 对照。

下一轮应把主要资源放在 adapter cost study 和真正独立的 package/project transfer，而不是继续增加
同文件算子数量。

## 11. H7C TorchIO 独立框架结果

TorchIO v1.0.2 在源码 blob 打开前完成 release、calibration/holdout split、阈值和成本公式预注册。
用四个 calibration 单元提炼出六条框架规则，并在打开七个 holdout 文件前冻结 analyzer 与 manifest。

结果有两层：

- 决策安全性与机会恢复：7/7 决策正确、unsafe false accept=0、safe recall=5/5；
- 解释精度：`MonaiAdapter` 被归为 `unresolved_user_callable`，而非预注册的
  `external_framework_delegation`，导致 reason accuracy=6/7=85.7% <90%，所以 H7C 正式判定 FAIL。

成本代理得到 adapter setup 2.97 分钟，break-even 13.48–15.47 个算子；50 算子预计节省按均值为
72.5%，按中位数为 68.4%，因此 ≥70% 门槛不稳健。这只是单 AI 研究者的源码确认计时，不能替代
人类 annotation-time study。

H7C 还暴露两个值得写进方法的 effect 维度：

```text
record_scope = whole_record | typed_subrecord | fixed_fields | unknown
delegation_kind = none | child_operator | user_callable |
                  framework_bridge | backend_graph
```

TorchIO 的 Subject keys 是参数化的，但 `SpatialTransform` 对 `subject.spatial_images` 这个 typed
subrecord 保持耦合，不能继续把所有 parametric target 都直接当成 unsafe。另一方面，UDF 与跨框架
wrapper 虽然都应 fail-closed，却需要不同的 proof obligation 和 unknown reason。

下一轮不允许修补并重跑 H7C。应把它转为新 calibration，设计 EffectV4，然后在另一个独立框架执行
H7D；正式成本结论需要至少两名人类参与者的交叉顺序计时。

## 12. H7D EffectV4 与 TorchGeo 结果

EffectV4 在完整 TorchIO calibration 上达到决策11/11、reason 11/11，新增 `record_scope` 与
`delegation_kind` 后成功区分 child operator、UDF 和 framework bridge。

随后仅依据 TorchGeo v0.9.0 公开接口编写五条零源码 adapter 规则，并在打开仓库源码前冻结全部哈希。
一次性结果为：

- unsafe false accept=0；
- safe recall=3/4=75%，达到门槛；
- resolved coverage=4/5=80%，达到门槛；
- reason-category accuracy=4/5=80%，低于90%，所以正式 H7D FAIL。

`SatSlideMix` 的 gamma batch expansion 被正确识别为 one-to-many 并拒绝。唯一失败的 `Rearrange`
不是语义误判：protocol 将公开符号错误绑定到 `spatial.py`，实际定义在 `temporal.py` 并由 package
`__init__` re-export。失败后、不修改 adapter 的路径修正 counterfactual 会正确接受，但不计入 gate。

因此系统还缺一个非语义但必要的组件：

```text
public_symbol -> export module -> defining module -> source hash
```

symbol-origin sealer 已在下一前置轮实现并完成 TorchGeo 回归；H7D 的正式结论不变。

## 13. H7E 前置轮：Symbol-Origin Sealer

已实现 `experiments/autocontract_symbol_origin.py`，以不执行目标 package 的方式解析显式 re-export、
alias 和顶层定义，并冻结 defining module、相对路径、行号、source SHA-256、binding SHA-256 与 exact
Git revision。star import、歧义、外部 re-export 和缺失符号均保守返回 unresolved。

七个正常/对抗单元测试全部通过；TorchGeo H7D 五个符号全部正确解析，其中 `Rearrange` 被定位到
`torchgeo.transforms.temporal` / `temporal.py:13`。portable manifest digest 为
`a95affe19f2e57ff2baae8f4ef117e5d467bb9215f34db6dd7796484a2ceff6d`。

该结果只验证新 protocol mechanism，不回写 H7D。H7E 必须在 operator body 打开前通过独立的 binding
integrity gate；正式评估拆为 binding integrity、coarse safety gate 与 diagnostic quality 三层。完整前置
条件见 `.research/semantics_safe_reconfiguration/h7e_symbol_origin_preconditions.zh-CN.md`。

## 14. H7E audiomentations 跨域 holdout

选择此前未进入 corpus 的 audiomentations v0.43.1，将验证域扩展到 CPU/NumPy 音频。七个 public symbols
先通过 symbol-origin gate，再冻结零 operator-body adapter、protocol 和全部哈希。正式一次性结果：

- binding integrity=7/7；
- decisions=7/7；
- unsafe false accept=0；
- supported-safe recall=4/4；
- coarse reason accuracy=7/7；
- classified coverage=7/7；
- **H7E blind gate：PASS**。

普通 waveform transforms 被接受；`Lambda`、`Compose`、`AddBackgroundNoise` 分别因 user callable、child
effect 和 filesystem external operand 被拒绝。六个冻结产物在运行后哈希保持6/6一致。

正式运行后的非 gate 诊断发现：EffectV4 未捕获 `self.parameters[...]` 下标写入，且冻结 adapter 未完整
跟随跨模块 `super().randomize_parameters()`；扩展审计在6/7单元中发现 replayable parameter state。
因此 H7E 的 PASS 只在预注册的 default/unfrozen context 下成立，系统尚未自动生成或强制
`requires_parameters_unfrozen` guard。下一步应把 H7E 转为 calibration，设计 configuration-aware
EffectV5，然后只在新框架 H7F 上执行下一次正式 blind。

## 15. EffectV5 calibration

EffectV5 将 H7E 的 posthoc 缺口正式编码为：`state_accesses`（attribute/subscript/container
mutation）、`state_roles`（replayable/cache/control/unknown）、`required_modes`、
`refresh_before_use` 和跨模块 `super_resolution`。在 TorchIO 11 单元与 audiomentations 7 单元上，
decision 18/18、reason 18/18、audiomentations state oracle 7/7、super resolution 18/18，达到冻结条件。

关键变化是 replayable state 不再被 `execution_state_write` 一刀切拒绝；只有能证明每次调用前刷新/恢复，
且 validator 的 active mode 满足 contract obligation 时才允许优化。cache/control/unknown state 仍然
fail-closed。

## 16. H7F imgaug 跨框架 holdout

H7F 使用 `aleju/imgaug` 0.4.0 commit `14b85e2209de0107c250e4d9dd6507dec1eae826`。
8 个 adapter calibration symbols 与 8 个 formal symbols 完全不相交；正式分析前冻结仓库、EffectV5、
adapter、协议、符号绑定和 calibration summary。预注册上下文为 imgaug deterministic mode。

正式一次性结果：binding 8/8、decision 7/8、unsafe false accept=0、safe recall=4/5=80%、coarse
reason=7/8=87.5%、classified coverage=8/8，**H7F PASS**。四个普通随机算子在
`framework_specific(imgaug_deterministic)` mode obligation 下接纳；child/UDF 负例全部拒绝。

唯一错误 `LinearContrast` 是保守误拒绝。冻结后的来源审计证明其 `self.func` 固定绑定到模块函数
`adjust_contrast_linear`，而 `Lambda`/`AssertLambda` 分别来自 public user input / derived user input。
这提出 EffectV6 的两个明确增量：

```text
state_path_kind += delegated_mutation
callable_origin = module_bound | public_input | public_input_derived
                | child_operator | external_dynamic | unknown
```

posthoc counterfactual 会接纳 `LinearContrast` 并继续拒绝 Lambda family，但不回写正式 H7F。详细复盘见
`.research/semantics_safe_reconfiguration/h7f_imgaug_postmortem.zh-CN.md`。

## 17. EffectV6 calibration

EffectV6 新增 `delegated_mutation`、跨局部赋值和 `super().__init__` 的 callable-origin lattice，以及
framework-qualified mode obligation。在 TorchIO 11、audiomentations 7、imgaug 16 个已完成单元上，
decision/reason 均为 34/34；13 个单元含 delegated RNG mutation，19 个单元生成具名模式义务。

`LinearContrast.func` 被证明为 module-bound 并接纳；imgaug `Lambda` 与 `AssertLambda` 分别保持
public-input/public-input-derived 拒绝。EffectV6 达到 H7G 冻结条件。

## 18. H7G Albumentations holdout

H7G 使用 Albumentations 2.0.8，正式上下文限定为 stored-parameter replay，而不是 seeded sequence。
7 个校准符号与 8 个正式符号不相交。一次性结果为：binding 8/8、decision 7/8、预注册 unsafe
false accept=1、safe recall=5/5、coarse reason=7/8、coverage=8/8，正式 **H7G FAIL**。

唯一分歧 `HistogramMatching` 在 default/record path 中确实可能调用 public-input `read_fn`；冻结 adapter
因未沿 `_get_reference_image` helper 闭包而漏检。但在正式声明的 replay path 中，
`BasicTransform.__call__` 会在采样 helper 之前使用已保存的 `self.params` 返回，`read_fn` 不可达。
posthoc reachability audit 得到 replay=admit、record=reject。

因此 H7G 暴露的是 analyzer 与 oracle 的共同 schema 缺口，而不能简单描述成 replay 模式下放过了真实
unsafe callable。EffectV7 应建模：

```text
reachable_effect(mode, phase, path_condition)
```

并沿 self/super helper call graph 做分支敏感闭包。正式 H7G 结论仍为 FAIL；详细复盘见
`.research/semantics_safe_reconfiguration/h7g_albumentations_postmortem.zh-CN.md`。

## 19. EffectV7 calibration

EffectV7 将 effect 的判定键从 class-level 集合改为 `(public symbol, configuration, phase, reachable path)`，并从框架 entrypoint 闭包 self/super helper call graph。对已知 mode predicate 和 `params is None` 分支做裁剪；未知条件保守取并集。

在 EffectV6 的 34 个已完成单元上保持全部原判定，并加入 H7G 完成后的 HistogramMatching phase contrast：Albumentations replay 下 `read_fn` 不可达并接纳，record 下 helper closure 到达 public-input `read_fn` 并拒绝。合计 decision 36/36、reason 36/36，达到冻结条件。

## 20. H7H Kornia mode/phase holdout

H7H 使用 Kornia v0.8.3 commit `d6bb4bf0d8a043c2bb8cef0c346a1b006d100930`。正式协议以 `params_provided` 和 `params_absent` 标注同一算子的 replay_apply / sample_apply operation；校准与正式 symbols 不相交，并在正式方法体 effect analysis 前冻结 V7、adapter、协议、阈值、符号绑定、commit 与 source hashes。

一次性正式结果为：binding 5/5、operation decisions 9/9、unsafe false accepts=0、safe recall=4/4、coarse reason=9/9、coverage=9/9、phase contrast=4/4，**H7H PASS**。四个随机算子均在 supplied compatible params 下裁掉 `forward_parameters` 并接纳，在 `params=None` 下以 `reachable_sampling_rng` 拒绝；AugmentationSequential 因 child contracts 未合成而继续 fail closed。

这支持更窄的结论：adapter-assisted analyzer 可以基于框架公开 replay interface 生成 mode/phase-sensitive rewrite certificate。它不支持任意参数记录或任意 Python 的强主张；`params` 的完整性、版本/schema 兼容性和 sample lineage 仍是外部 proof obligation。下一步应实现 parameter-record lineage certificate 与 child-contract composition，并在真实 Kornia pipeline 上验证 rewrite 的 trace、RNG、梯度和性能。

## 21. H7I replay-lineage 与 child-contract composition

H7I 将 H7H 的 `params_provided` 布尔前提细化为 framework/version/commit、operator graph、input schema、sample identity、parameter digest 和 child sequence 的 lineage certificate。证书 self-test 7/7；在 RandomHorizontalFlip、RandomAffine、ColorJiggle 组成的真实 Kornia AugmentationSequential 上，重建 target instance 后输出、Torch RNG state 和输入梯度 trace 全部与 source record 一致。错 sample、版本、commit、算子配置、child 顺序、shape、参数篡改、缺失/重复/未知 child 等 17 个 runtime/adversarial test 全部通过。

child composition 将三个 H7H calibration 已接纳 leaf 的 `ParamItem` 与实际 module 逐一绑定，使此前保守拒绝的 container 在该封闭 policy 下接纳。这是 mechanism calibration，不是新 blind holdout。

多规模性能共 15 个 trial：replay 更快 10/15，总体中位 1.074×；小/中 workload 中位 1.166×/1.096×，大 workload 中位 0.961×。因此 replay 不能声称普遍加速。

posthoc TOCTOU audit 发现：证书验证后若共享 params 在 apply 前被修改，先前 admit 会失效并产生不同输出；使用验证时的 immutable snapshot 则保持一致。下一版安全条件必须加入 `validated bytes == consumed bytes`，通过 sealed buffer、copy-on-seal 或 atomic validate-and-apply 实现。详细复盘见 `.research/semantics_safe_reconfiguration/h7i_lineage_composition_postmortem.zh-CN.md`。

## 22. H7J sealed atomic replay

H7J 使用私有 immutable snapshot 和锁内原子边界实现 `copy -> validate -> child-proof compose -> apply -> post-use digest -> release output`。原始参数及 target 暴露 `_params` 的修改不会进入下一次调用；前置失败保证 operator 零调用，operator 内修改 working params 时输出不释放。

leaf policy 不再手写：三个 child 的 proof 由冻结 H7H EffectV7/Kornia adapter 自动生成，并绑定 source/binding、repository、EffectV7 与 adapter hashes。泛型 self-test 4/4，真实 Kornia 测试 12/12；4 worker 在外部线程持续修改原始 params 时完成 100/100 相同 replay、0 error、RNG state 不变，梯度 trace 与 direct replay 一致。

随机交错配对性能共 30 轮，atomic 30/30 更慢；B1×32、B4×64、B8×128 的中位 atomic/direct-copy 分别为 1.408×、1.259×、1.100×，总体中位 1.250×。因此当前安全闭环有效但成本明显。下一步应注册并私有持有 target，一次性缓存 operator graph 与 child proofs，每次调用只保留 working copy、sample check、apply 和 post-use check。详细复盘见 `.research/semantics_safe_reconfiguration/h7j_atomic_replay_postmortem.zh-CN.md`。

## 23. H7K registered/owned replay executor

H7K 把 framework/version/commit、operator graph、EffectV7 leaf proof、child composition 和 pool target 等静态事实移到注册阶段；每次调用只保留 sample/input schema check、private snapshot copy、exclusive target lease、apply、post-use params digest 和成功后输出释放。`minimal` receipt 不计算 output digest，`audit` receipt 额外绑定 output digest。

通用 self-test 5/5，真实 Kornia correctness/security 14/14。错 sample/schema 均在 operator 调用前拒绝，改配置 target 与缺 child proof 均在注册时拒绝，外部修改原始 params 被隔离，operator 内修改 working params 时输出不释放。4 worker×25 calls 在持续外部 mutation 下完成 100/100 相同输出、0 error、RNG 不变，且四个 target slot 均被实际使用；梯度 trace 与 direct replay 一致。

随机交错配对共 30 轮：H7K minimal/H7J 总体中位 0.860×，29/30 轮更快；H7K minimal/direct+copy 总体中位 1.053×；audit/minimal 中位 1.020×。三个 profile 的保守注册 break-even 为 1.4–4.1 calls。CPU pool scaling 的中位吞吐为 pool1=69.3、pool2=78.2、pool4=72.1 calls/s，说明 owned pool 是隔离机制，而 pool size 应由资源策略调优。

H7K 是依赖冻结 H7H policy 的 mechanism/runtime 实验，不是新 blind holdout，也不是针对 reflection/monkey patch 的 sandbox。当前下一关键缺口是 caller 可以伪报 `sample_id`；应在 H7L 研究由 dataset/sampler 签发、跨 worker 可验证并绑定 dataset revision、sample/partner、epoch、operator path 与 parameter record 的 provenance token。详细复盘见 `.research/semantics_safe_reconfiguration/h7k_registered_executor_postmortem.zh-CN.md`。

## 24. H7L signed provenance token 与 replay registry

H7L 使用主进程私有的 Ed25519 key 签发 per-invocation token，worker/executor 只持公钥。token 绑定 run、dataset revision/split/manifest、epoch、sampler context、ordered subjects、operator path、H7K registration、实际 input digest 和 nonce；SQLite registry 原子执行 `issued -> consumed`。输入先 clone，再验证 clone digest，并把同一个 clone 交给 H7K，满足 `validated bytes == consumed bytes`。

generic token/registry self-test 7/7；真实 Kornia correctness/security 21/21；错 run/sample/revision/manifest/epoch/sampler/subjects/operator/registration/input、duplicate/revoked/unknown-key/signature tamper 全部零 operator 调用拒绝。50 次外部线程输入改写压力最终复跑为 26 次安全成功、24 次前置拒绝、0 错误输出，RNG 不变；梯度与 direct replay 一致。4 个 Windows `spawn` worker 的独立 token 4/4 成功，竞争同一 token 时严格 1 成功、3 拒绝，spawn gate 5/5。

三 profile、30 轮随机配对中，H7L/H7K 总体中位 1.235×；B1×32、B4×64、B8×128 分别为 1.384×、1.127×、1.092×。组件中位显示 Ed25519 verify 约 0.32–0.37 ms、durable registry consume 约 3.48–3.75 ms、seal+digest 从 0.036 ms 增至大输入 2.325 ms。工作区与本机临时目录 consume 比值仅 1.072×，同步盘不是主要瓶颈。

当前 registry 只保证 token consumption exactly-once，不保证 optimizer/data side effect 端到端 exactly-once；consume 后 crash 会丢失工作，lease timeout 重开又可能导致重复。下一步 H7M 应研究 signed batch/Merkle root、worker nonce-range lease、fused decode hashing 与 `issued -> leased -> applied -> committed` crash state machine，并在真实多样本 transform 上验证 ordered partner lineage。详细复盘见 `.research/semantics_safe_reconfiguration/h7l_provenance_postmortem.zh-CN.md`。

## 25. H7M Merkle batch、fenced lease 与 buffered release

H7M 让每个 leaf 绑定独立 H7L expectation/H7K registration，以一个 Ed25519-signed Merkle root 绑定整批。registry 状态机为 `issued -> leased(generation) -> committed`；recover/abort 递增 generation，使 stale worker 不能 commit。所有 inputs/tickets/proofs 在 claim 前验证，outputs 在 batch commit 成功前不释放。root cache 仅在重算 statement+signature digest 并检查 schema/key 后命中，修复了开发中发现的 cached-ID alias 绕过风险。

generic 7/7，真实 heterogeneous-params Kornia batch 12/12；wrong input、ticket reorder、proof/alias tamper 均零调用拒绝，4 caller 竞争只产生一个 batch 的 N 次 invocation。独立进程在 claim 后 crash 与 commit 后 ack-loss 的 6 项测试全部通过：recover 后旧 generation 拒绝，相同 committed digest 重试幂等，不同 digest 冲突拒绝。

Kornia `RandomMixUpV2` 的 posthoc mechanism extension 8/8：冻结 EffectV7 生成 admit proof，token subjects 从 `mixup_pairs=[1,0,3,2]` 推导并逐输出槽绑定 primary/partner；wrong partner 与 input reorder 零调用拒绝，输出/RNG/梯度一致。该算子不在正式 H7H symbol set，不能写成新 blind PASS。

摊销微基准中，H7M/H7L consumer ratio 随 N=1/4/16/64 为 1.911×/0.488×/0.138×/0.053×；N=1 明确 no-go，N≥4 进入收益区。Merkle proof 令 bytes/sample 从 N1 的 1297 增至 N64 的 1317，而 H7L 约为 1021–1023，性能收益以更多 metadata 换取。真实 Kornia batch=4 中 H7K/H7L/H7M 中位分别为 31.216/48.321/41.070 ms，H7M/H7L=0.835×，10/10 round 更快；最低 tensor buffering 为 192 KiB input + 192 KiB output。

H7M 只保证 batch authorization/registry commit 与 stale-worker fencing，不保证 optimizer step exactly-once。下一步 H7N 应把 DataLoader position/worker RNG、batch ID、model state 和 optimizer state 纳入 checkpoint-coupled effect journal，并通过 crash injection 验证恢复后 digest 与无故障执行等价。详细复盘见 `.research/semantics_safe_reconfiguration/h7m_batch_lease_postmortem.zh-CN.md`。
