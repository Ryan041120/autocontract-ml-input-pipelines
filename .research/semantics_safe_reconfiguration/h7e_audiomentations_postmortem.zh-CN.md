# H7E audiomentations 零 operator-body holdout 复盘

更新日期：2026-07-28

## 1. 目的与框架选择

H7E 使用此前未进入 AutoContract corpus 的 `iver56/audiomentations` v0.43.1，commit
`19609e6d6624ef9e4933412ccda78fb6221f77e1`。它将验证域从视觉/医学影像扩到 CPU NumPy 音频，
并同时提供普通 waveform transform、组合器、用户 callable、外部文件 operand 与可冻结随机参数。

正式 evaluation context 固定为默认/unfrozen parameter mode。`admit` 表示 effect 足够完整，可以进入
后续具体 rewrite checking，不表示任意两个被接受的 operator 都可交换。

## 2. 冻结纪律

1. 根据官方 API/docs 选择七个 public symbols、oracle 与阈值；
2. 在不执行 package 的情况下运行 symbol-origin sealer；
3. 7/7 binding 唯一解析，revision verification=true；
4. 仅依据公开文档与 binding metadata 编写结构化 adapter；
5. 冻结 EffectV4、sealer、adapter、adapter manifest、protocol、symbol manifest 和 release commit；
6. 冻结后执行唯一一次正式 evaluator。

symbol manifest portable digest：
`dddf71eb188383b517cacd02b071b9f8f7f24226f83085f3a6c2a1edaac19c46`。

冻结前发现 `resolved coverage` 与正确的 fail-closed `Lambda`/`Compose` 存在逻辑冲突，因此在 adapter
冻结和 body inspection 前留下时间戳，将指标改为 `classified coverage`。样本、oracle 和数值阈值未变。

## 3. 正式结果

| 指标 | 门槛 | 结果 | 判定 |
|---|---:|---:|---|
| Binding integrity | 100% | 7/7 | PASS |
| Known-unsafe false accepts | 0 | 0 | PASS |
| Supported-safe recall | ≥75% | 4/4 (100%) | PASS |
| Coarse-reason accuracy | ≥90% | 7/7 (100%) | PASS |
| Classified coverage | ≥85% | 7/7 (100%) | PASS |

因此正式 **H7E blind gate：PASS**。

- `Normalize`、`PolarityInversion`、`AddGaussianNoise`、`Clip` 被正确接受；
- `Lambda` 以 `unresolved_user_callable` 拒绝；
- `Compose` 以 `unresolved_child_effect` 拒绝；
- `AddBackgroundNoise` 同时识别 user callable 与 filesystem-backed external operand 并拒绝。

所有六个冻结文件在正式运行后重新计算哈希，6/6 保持一致。

## 4. Posthoc state audit（不计入 gate）

正式结果显示所有 state attrs 为 `none`，但公开文档说明 transform 会保留 `parameters`。打开源码后的诊断
确认，旧 detector 只捕获 `self.attr = ...` 和容器 method mutation，漏掉：

```python
self.parameters["should_apply"] = ...
self.parameters["amplitude"] = ...
```

同时，冻结 adapter 的 call graph 没有完整跟随 `super().randomize_parameters()`。扩展的 posthoc audit
在 6/7 单元中检测到 replayable parameter state；`AddBackgroundNoise` 还写 `self.time_info_arr`。

这不推翻正式 H7E：oracle 明确限定 default/unfrozen mode，在该模式中每次调用会在消费参数前重新随机化。
但它限制了可声称的范围：当前系统没有自动生成或运行时强制执行 `parameters_unfrozen` guard，因此不能把
H7E 描述为对 frozen/replay mode 也成立的端到端安全证明。

## 5. EffectV5 候选

H7E 转入 calibration 后，下一版至少需要：

```text
state_path_kind = attribute | subscript | container_mutation
state_semantics = none | call_local | replayable | cache | persistent_control | unknown
required_mode = none | parameters_unfrozen | framework_specific | unknown
super_resolution = complete | partial | unknown
```

对应 proof obligation：

1. 所有 state subscript write 与容器 mutation 都进入 effect；
2. `super()` 沿跨模块 class graph 解析，否则 fail closed；
3. replayable state 只有在“本次调用写入先于读取”且 runtime mode guard 被验证时才能 admit；
4. frozen/replay mode 必须将 parameter buffer 当作 future-output control state；
5. cache 和其他持久状态仍需独立拒绝或生成 invalidation/migration obligation。

下一次独立测试应称为 H7F，不能在 H7E 样本上修改后重跑并升级结论。
