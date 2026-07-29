# EffectV7：配置与阶段敏感的可达效应

日期：2026-07-29

## 核心变化

EffectV6 将 callable provenance 和 mode obligation 放进了同一个 contract，但仍然按 class 汇总效应。EffectV7 将判定键改为：

```text
(public symbol, configuration, phase, reachable path)
```

IR 的最小形式为：

```text
ReachableSlice = {
  context: configuration × phase,
  reachable_methods,
  evaluated_guards,
  reachable_state_accesses,
  reachable_callable_origins,
  reachable_rng_paths,
  sampling_rng,
  delegation,
  unresolved_dispatch
}
```

当前实现从框架 entrypoint 出发，闭包 `self.method()` 和 `super().method()` 调用；对上下文已知的布尔 mode predicate，以及 `params is None` / `params is not None` 做分支裁剪。未知条件取并集，安全相关的未知动态分派继续 fail closed。

## 校准结果

EffectV7 在 34 个 EffectV6 已完成单元上保持全部原判定，并加入 H7G 已完成后的两条 phase oracle：

| Operation | 预期 | 实际 | 关键路径 |
|---|---|---|---|
| HistogramMatching × Albumentations replay | admit | admit | `__call__ -> apply_with_params -> apply`；`read_fn` 不可达 |
| HistogramMatching × Albumentations record | reject | reject | `__call__ -> get_params_dependent_on_data -> _get_reference_image -> read_fn` |

总计 decision 36/36、reason category 36/36，达到 H7H 冻结条件。

## 仍然保守或未解决的部分

- 当前方法解析使用源码级保守 MRO 近似，尚不是完整 Python C3 与 descriptor dispatch。
- 未知 path condition 只做并集，没有 SMT、range analysis 或关联约束。
- `params_provided` 仍是外部 proof obligation：必须证明记录完整、与算子版本及输入 schema 兼容，并属于正确 sample lineage。
- child operator 仍然整体拒绝；下一步需要 contract composition，而不是继续添加容器白名单。
- 构造期与执行期已经区分，但异步 I/O、C++/CUDA 扩展和运行时 monkey patch 仍不在当前 source analyzer 的支持范围。
