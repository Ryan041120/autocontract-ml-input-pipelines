# H7F imgaug / EffectV5 复盘

日期：2026-07-29

## 1. 正式设置

H7F 使用独立视觉增强框架 `aleju/imgaug` tag `0.4.0`，checkout commit
`14b85e2209de0107c250e4d9dd6507dec1eae826`。本轮先将 H7E 转为 calibration，完成
EffectV5 的状态下标、状态角色、运行模式与跨模块 `super` 解析校准；TorchIO 与
audiomentations 合计 18 个单元达到 decision 18/18、reason 18/18、state oracle 7/7、
super resolution 18/18。

imgaug adapter 使用 8 个已查看单元校准；正式 H7F 使用另外 8 个不相交 public symbols。
正式运行前冻结 repository commit、EffectV5、symbol sealer、adapter、adapter manifest、
protocol、symbol manifest 与 calibration summary。正式上下文限定为 imgaug deterministic
mode，background multiprocessing 不在声明范围内。

## 2. 正式结果

- binding integrity：8/8；
- decisions：7/8；
- known-unsafe false accepts：0；
- supported-safe recall：4/5 = 80%；
- coarse reason accuracy：7/8 = 87.5%；
- classified coverage：8/8；
- **H7F blind gate：PASS**。

PASS 正好达到预注册的 safe recall 0.8 与 coarse reason 0.875 门槛，因此应解释为“保守安全性
继续成立，但机会恢复仍接近边界”，不能描述成接近完美的跨框架泛化。

## 3. EffectV5 学到了什么

四个普通随机算子 `Multiply`、`AverageBlur`、`Affine`、`CropToFixedSize` 均被识别为：

```text
state_role = replayable
required_mode = framework_specific(imgaug_deterministic)
per-call condition = RNG state restored by _maybe_deterministic_ctx
```

这比 H7E 的外部 default/unfrozen 假设更强：模式前提已经进入 contract/validator，并且缺少模式时
会产生 `unsatisfied_mode_guard`。`SomeOf`、`WithChannels` 仍因 child delegation fail-closed，
`AssertLambda` 因用户回调 fail-closed，没有危险误接纳。

需要保留一个边界：EffectV5 当前把 RNG 对象的方法调用编码成既有
`container_mutation:self.random_state`，这是 adapter 的保守映射，不是 IR 对 delegated object
mutation 的原生表达。下一版应增加独立的 `delegated_mutation` path kind。

## 4. 唯一错误：callable 的来源，而不是 callable 的存在

`LinearContrast` 被预期接纳但实际拒绝。冻结 adapter 看到
`_ContrastFuncWrapper.__init__(func, ...) -> self.func = func`，执行时调用 `self.func(...)`，因而报
`unresolved_user_callable`。

正式运行后的非 gating 来源审计沿 `super().__init__` 反向传播构造参数，得到：

| 符号 | callable origin | 来源敏感判定 |
|---|---|---|
| `LinearContrast.func` | `module_symbol` (`adjust_contrast_linear`) | admit |
| `Lambda.func_*` | `user_input` | reject |
| `AssertLambda.func_*` | `user_derived` | reject |

因此旧规则“构造参数写入 `self.func` 并在执行时调用 => user callable”过粗。真正需要的 effect 是：

```text
callable_origin =
    module_bound
  | public_input
  | public_input_derived
  | child_operator
  | external_dynamic
  | unknown
```

只有 `module_bound` 且其 defining source 已封存、函数体 effect 可解析时，才可继续分析；其它动态
来源保持 fail-closed。这个结论来自 posthoc audit，不回写 H7F 的正式 7/8 与 PASS。

## 5. 对研究主线的影响

当前证据支持：

> AutoContract 的核心不是给算子贴 pure/impure 标签，而是让 rewrite 携带可审计的状态角色、模式
> 义务、委托来源和符号来源证明。

H7F 将状态模式从“实验说明中的隐含上下文”推进为 validator 的显式义务，属于实质进展；同时它说明
symbol-origin 不能只用于绑定 public class，还要继续传播到 execution callable。

总体仍是 **adapter-assisted prototype: conditional go**。暂时不能声称任意 Python callable 自动可解，
也不能将 deterministic-mode 条件下的 PASS 外推到默认 stochastic mode 或 background workers。

## 6. 下一轮

先把 H7F 转为 calibration，设计 EffectV6：

1. 新增 `delegated_mutation`；
2. 新增跨 `super().__init__` 的 callable-origin lattice；
3. 将 `framework_specific` 细化为具名 mode obligation，并区分 required / ensured；
4. 在现有 H7F 集上只做 mechanism calibration；
5. 再选择未参与开发的新框架执行 H7G，一次性检验安全误接纳、safe recall 与来源理由。

首选 H7G 不应只是另一个 imgaug 版本。可优先比较 `tsaug`（跨时间序列、组合与 cardinality）和
`torch-audiomentations`（强 mode/freeze 语义但与 H7E 同谱系），按“实现独立性 × EffectV6 挑战强度”
决定。
