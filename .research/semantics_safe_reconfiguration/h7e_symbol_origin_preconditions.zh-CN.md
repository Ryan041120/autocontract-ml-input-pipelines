# H7E 前置轮：可审计 Symbol-Origin Sealer

更新日期：2026-07-28

## 1. 目的

H7D 的正式失败来自 `Rearrange` 的源码路径被人工错绑，而非 EffectV4 对其函数体的语义分析错误。
本轮不修改、不重跑 H7D，而是新增独立的协议前置机制：在任何 holdout 函数或类 body 被用于 adapter
开发之前，把公开 API 符号解析到唯一的定义模块和精确源码哈希。

```text
public symbol
  -> explicit export chain
  -> defining module
  -> repository-relative source path + line
  -> source SHA-256
  -> portable binding SHA-256
```

## 2. 实现

实现文件：`experiments/autocontract_symbol_origin.py`

当前算法 `explicit-reexport-top-level-ast-v1`：

- 不 import、不执行目标 Python package；
- 仅使用模块级 `class`、`def` 和显式 `from ... import ...` 元数据；
- 支持递归 re-export 和 `as` 别名；
- 绑定 exact Git revision；
- 每个 binding 包含相对路径、定义行、源码哈希和 binding 哈希；
- manifest 总哈希排除本机绝对 checkout 路径，因此相同 revision/源码在不同机器上可复现。

保守边界：star re-export、多个显式候选、包外 re-export、动态 `__getattr__`、生成文件、C extension
和无法解析的模块都必须返回 `unresolved`，不得猜测路径。

## 3. 测试

`experiments/test_autocontract_symbol_origin.py` 覆盖七种情况：

1. 递归显式 re-export；
2. alias re-export；
3. 外部包 re-export 拒绝；
4. 缺失符号拒绝；
5. 歧义显式 re-export 拒绝；
6. star re-export 拒绝；
7. checkout 绝对路径变化不影响 portable manifest digest。

结果：**7/7 PASS**；两个脚本通过 `py_compile`。

## 4. TorchGeo 回归

在 TorchGeo v0.9.0、commit `120b8b1d477e8911ed052ec84a197dd545254e63` 上，五个 H7D
公开符号全部解析，revision 校验通过：

| Public symbol | Defining module | Source |
|---|---|---|
| `RandomGrayscale` | `torchgeo.transforms.color` | `color.py:10` |
| `AppendNormalizedDifferenceIndex` | `torchgeo.transforms.indices` | `indices.py:18` |
| `AppendTriBandNormalizedDifferenceIndex` | `torchgeo.transforms.indices` | `indices.py:292` |
| `Rearrange` | `torchgeo.transforms.temporal` | `temporal.py:13` |
| `SatSlideMix` | `torchgeo.transforms.spatial` | `spatial.py:14` |

portable manifest digest：`a95affe19f2e57ff2baae8f4ef117e5d467bb9215f34db6dd7796484a2ceff6d`。

这证明新 sealer 能阻止 H7D 的 `Rearrange -> spatial.py` 路径错误，但它是事后机制回归，**不改变
H7D=FAIL 的正式结论**。

## 5. H7E 硬前置门槛

H7E 只有在以下条件全部满足后才能打开 operator body 并执行一次性测试：

1. release tag 与 exact commit 已冻结；
2. holdout 单元由公开 API/docs 预先选择；
3. 每个 public symbol 的 origin status 均为 `resolved`；
4. revision verification 为 true；
5. defining source 相对路径、行号、source hash、binding hash 与 manifest hash 已冻结；
6. adapter、Effect schema、reason taxonomy、阈值均已冻结；
7. 任一 binding unresolved 时在运行前终止协议，不得计为 analyzer false reject。

正式指标拆成三层：

- **binding integrity gate**：协议与样本定位是否有效；
- **safety gate**：unsafe false accept、safe recall、coarse safety reason；
- **diagnostic quality**：细粒度 subtype，单独报告，不与核心安全 gate 混淆。

## 6. 当前判断

symbol-origin 的已知失败模式已被修复并完成针对性回归，H7E 可以进入候选框架筛选阶段。但 sealer
当前只覆盖常见的纯 Python 显式导出模型；选择 H7E 框架时，要么预先排除动态导出/compiled extension，
要么在校准阶段扩展 sealer 后重新冻结，不能在正式 holdout 后修补。
