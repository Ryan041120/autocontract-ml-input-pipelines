# H6 EffectV2 一次性 blind holdout 复盘

更新日期：2026-07-28

## 1. 协议完整性

- EffectV2 在 20 个 calibration 单元、300 个 effect cell 上达到 100%，关键漏检为 0。
- analyzer 在打开 blind source 前固定：`f61827919715ff11119b352dc473c4481c41b44ac8b0880f3b28c7a719535061`。
- 人工 oracle 在运行 analyzer 前固定：`f0f4799978de14c03b53fddc1fed971f012c7f735fccfe2e62c7a2f808beb1dc`。
- blind 来源为 MONAI、MMDetection 和 NVIDIA DALI 的密封 commit；评估后未修改分析器并在同一批上重试。

## 2. 一次性结果

| 指标 | 预先门槛 | 实测 | 判定 |
|---|---:|---:|---|
| Effect-cell accuracy | ≥95% | 76.1% (137/180) | FAIL |
| Critical false negatives | 0 | 9 | FAIL |
| Known-unsafe false accepts | 0 | 2 | FAIL |

误接受为：

1. MMDetection `CachedMosaic`；
2. NVIDIA DALI `Pipeline`。

当前 validator 总共接受 4 个单元：其中 `RandomFlip` 和 `RandomCrop` 是可进入 unary
optimizer 的 safe 单元，另两个则是上述 unsafe false accepts。

43 个错误 cell 主要分布为：RNG source 9、execution read/write 各 8、target coupling 3、
input cardinality 3、execution external read/write 各 2，其余来自基类状态、delegation、target signature、
output cardinality 与 sample identity。

## 3. 根因不是“token 还不够多”

| 真实模式 | 冻结分析器的假设 | 失败结果 |
|---|---|---|
| MONAI `self.R` | 只识别 `random.*`/`np.random.*`/`torch.*` | 4 个组合容器全部漏掉 NumPy RNG |
| MMDetection `transform` entrypoint | 主要从 `__call__`/`forward`/`apply_*` 建可达图 | 多 target read/write 和 helper RNG 没有进入 execution effect |
| 跨模块基类 | 只合成当前文件内可见基类 | MMDetection RandomFlip 的构造状态和随机委托丢失 |
| `CachedMosaic.results_cache` | schema 只有 construction state write | 执行期缓存状态、`k->1` lineage 和 combine identity 漏掉 |
| DALI backend graph | 一元/`k->1` Python transform 模型 | many-to-many batch graph、backend read/write 与参数化 output 无法表达 |

这些都需要语言/框架级信息，无法靠同一个浅层 Python AST rule 通用恢复。

## 4. unknown-reject 反事实

如果对“外部基类未解析”或“找不到已知 execution entrypoint”的类统一输出 `Unknown`，并在
validator 中保守拒绝，两个 unsafe false accept 都会消失。但同时，blind 中两个 safe 单元
`RandomFlip`/`RandomCrop` 也都会被拒绝，safe recall 从 2/2 降为 0/2。

这个反事实给出了清晰的系统边界：

```text
generic analyzer + reject unknown
    => safety, but almost no optimization opportunity across frameworks

framework semantics/adapters
    => recover recall without silently treating unknown as pure unary code
```

## 5. go/no-go 修正

### No-go

**对“用一套浅层 Python 静态/动态规则，自动支持任意 GitHub ML input pipeline”的强声称判定 no-go。**

### 仍可继续的窄版本

> **Adapter-assisted AutoContract: a framework-neutral contract IR with conservative generic analysis and amortized framework adapters.**

每个 framework adapter 只提供结构语义，不逐算子人工标注：

- execution entrypoints（`transform`/`__call__`/`forward`）；
- RNG alias/type（例如 MONAI `self.R -> NumPy RandomState`）；
- 外部基类 effect summary；
- record/target schema 及 coupling group；
- cardinality/sample-lineage convention；
- construction/execution state lifecycle。

未安装 adapter 的框架必须返回 `Unknown(reason)` 并拒绝改写。

## 6. H7 建议门槛

1. unsupported framework 的 known-unsafe false accept = 0，且 100% 给出明确 unknown reason；
2. 对已支持 adapter 的一次性 project holdout：known-unsafe false accept = 0；
3. supported safe recall ≥70%；
4. adapter 成本按“每 framework 人工规则数 / 自动解析算子数”摊销，相比逐算子标注减少 ≥70%；
5. 只有通过上述门槛，才将 adapter 输出接入 rewrite validator。

## 7. H7A follow-up（post-blind calibration）

H7A 已实现 `EffectV3 = EffectV2 + execution_state_writes`、`Unknown(reason)` fail-closed gate，以及
MONAI/MMDetection 两个框架 adapter。冻结的 H6 EffectV2 analyzer 未被修改。

在本文件所复盘的同一批 12 个单元上，H7A 得到 12/12 正确决策、0 unsafe false accept、2/2
supported safe recall 和 2/2 unsupported reason coverage。`CachedMosaic` 现在因 many-to-one、
combine lineage 与执行期 `results_cache` 写入被拒绝；DALI 因 backend graph/entrypoint 语义未支持而
返回 `Unknown`。

这个结果只说明失败模式存在一个可行的 adapter-assisted 修复，不是新的 blind 证据。H7 总体仍为
INCOMPLETE：当前规则必须先冻结，再在未见项目或版本上一次性测试；adapter 人工成本也必须用时间或
等价标注单位实际测量，不能只用 93.8% 的 effect-cell-equivalent 数字替代。

## 8. H7B frozen release-version holdout

在 H7A 之后，先将 framework namespace selection、analyzer、adapter manifest、oracle、release commits、
样本与阈值全部冻结，再下载 MONAI 1.6.0、MMDetection v3.3.0 和 DALI v1.53.0 源码。

一次性结果为 14/14 决策正确、0 unsafe false accept、3/3 supported safe recall、2/2 unsupported
reason coverage，reason category 也为 14/14。H7B 的预注册门槛全部通过。

该结果将结论从“只在失败集上可修复”推进为“冻结 adapter 可迁移到未下载的 release 与两个未评估
算子”。但旧版本同路径源码在 H6 复盘中已经打开，因此不能称为完全独立 project transfer；同时
adapter annotation-time 摊销仍未测量。总体判断仍是 adapter-assisted conditional go。
