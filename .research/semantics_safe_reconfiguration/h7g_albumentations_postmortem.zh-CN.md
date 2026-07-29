# H7G Albumentations / EffectV6 复盘

日期：2026-07-29

## 1. EffectV6 calibration

EffectV6 在 TorchIO、audiomentations、imgaug 共 34 个已完成单元上达到 decision 34/34、reason
34/34；识别 13 个 `delegated_mutation` 单元和 19 个具名 mode obligation。H7F 的唯一保守误拒绝
`LinearContrast` 被识别为 `func=module_bound` 并恢复接纳，Lambda/AssertLambda 仍因
`public_input/public_input_derived` 拒绝。

## 2. H7G 设置

选择归档的 MIT Albumentations 2.0.8，commit
`4d2cf04b6635663275a747333754410ef255e54c`。7 个 adapter calibration symbols 与 8 个 formal
symbols 完全不相交；repository、EffectV6、adapter、协议、阈值、symbol binding、source hash 和
calibration summary 在正式运行前冻结。

active context 明确限定为：

```text
albumentations.replay =
  replay_mode=True
  + applied_in_replay restored
  + self.params restored from a compatible per-sample replay record
```

`Compose(seed)` 只保证相同调用条件下的随机序列复现，不属于上述 replay proof。

## 3. 正式结果

- binding integrity：8/8；
- decisions：7/8；
- preregistered known-unsafe false accepts：1；
- supported-safe recall：5/5 = 100%；
- coarse reason accuracy：7/8 = 87.5%；
- classified coverage：8/8；
- **H7G blind gate：FAIL**。

五个普通 transforms 全部在 `albumentations.replay` obligation 下接纳；`OneOf` 与 `Sequential`
因 child delegation 拒绝。唯一分歧是 `HistogramMatching`：oracle 预注册为 user-callable reject，
analyzer 实际 admit。

## 4. `HistogramMatching` 同时暴露 analyzer 与 oracle 的问题

2.0.8 源码中，`BaseDomainAdaptation` 仍保留 deprecated public constructor 参数
`read_fn: Callable`，并在 record/default path 的 `_get_reference_image` 中调用：

```text
BasicTransform.__call__
  -> get_params_dependent_on_data
  -> _get_reference_image
  -> self.read_fn(ref_source)
```

冻结 adapter 只收集预定义 execution hook，没有沿 `self._get_reference_image` helper call graph
闭包，因此在 **record/default mode** 下确实存在 callable 漏检。

但正式协议声明的是 **replay mode**。在该模式下，`BasicTransform.__call__` 在采样之前走早返回：

```text
if self.replay_mode:
    if self.applied_in_replay:
        return self.apply_with_params(self.params, **kwargs)
    return kwargs
```

非 gating 的 mode-conditioned reachability audit 得到：

| 模式 | `read_fn` 来源 | 可达性 | 来源敏感反事实 |
|---|---|---|---|
| replay | public input | 不可达 | admit |
| record/default | public input | 可达 | reject |

因此正式 FAIL 必须保留，但“1 个真实 unsafe false accept”的语义解释不成立：它混合了一个真实的
default-path analyzer 漏检和一个 replay-context oracle 过度拒绝。更准确的结论是 **protocol/oracle
failed to condition callable reachability on the declared mode**。

## 5. EffectV7 缺口

EffectV6 只有全局 `callable_origin` 与 `mode obligation`，缺少两者的乘积：

```text
reachable_effect(mode, phase, path_condition)
```

下一版至少需要：

1. 从 framework entrypoint 建立 self/super helper call-graph closure；
2. 对已知 mode predicates 做分支裁剪，如 `self.replay_mode`；
3. 分离 record/sampling phase 与 replay/apply phase；
4. 将 callable、external operand、RNG mutation 附着到可达 path，而不是 class 全局集合；
5. oracle 也必须标注 `(configuration, phase, operation)`，不能只给 class-level safe/unsafe 标签。

候选 IR：

```text
EffectV7 = {
  paths: [
    guard,
    phase,
    reachable_state_effects,
    reachable_callable_origins,
    reachable_external_effects
  ],
  obligations: required | ensured,
  unresolved_dynamic_dispatch
}
```

## 6. 研究判断

H7G 没有推翻 adapter-assisted 主线，但再次说明“识别到某个 effect”还不够；必须证明 effect 在目标
rewrite 的配置和阶段中可达。这个问题与编译器的 path-sensitive effect analysis、typestate 和
phase distinction 直接相连，理论上比继续添加框架关键词更有价值。

当前仍为 **conditional go**。H7G 正式 FAIL；posthoc 只用于定义 EffectV7，不回写 gate。下一次正式
holdout 必须称为 H7H，并使用同时标注 mode/phase 的 oracle。
