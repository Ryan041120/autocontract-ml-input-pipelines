# R3-P3c：递归常量规范化 SourceIndexV1 复盘

日期：2026-07-30
证据等级：P3b 反例上的 targeted posthoc repair；不是 blind holdout

## 1. 协议管理事件

P3c protocol v0 在候选实验执行前被 freeze check 拦截：P3b runner SHA 手抄时漏了一个十六进制
字符 `f`。v0 保留为 `fail_before_candidate_execution`；protocol v1 只修正该字段，继承 v0 的全部
研究问题、测试、门槛和 falsification rules，没有看过候选结果后改门槛。

- protocol v0：`9acf791daf9a32c5d94e35fdc1c96386f80d02c470ca4d747f755d6f488fc682`
- protocol v1：`bec7be39dda3640c106a11aef38a4d167df765db8f114f6dc39a6236d8518dd4`
- SourceIndexV1 candidate：`7e6251c0388fce23c115919258ac43fb9d620ea38f8902082fe6da7cfbb5238c`
- runner：`2e63e7fb26f4a8f5e82f7fc3259cf0a22b364b1098d5b43ba7e5c0a3a4b245f8`
- result JSON：`d66a3ef26bf9e9874c023dbbceb5e4ed197587217c038c1f73f3ff2bf63232ca`

## 2. 结果：7/7 gates，PASS

V1 不再使用 `repr(code.co_consts)`，而是递归编码 typed constants：

- int/string/bool/None；
- float hex、NaN/inf、complex；
- bytes length + SHA-256；
- ordered tuple；
- 按 canonical JSON 排序的 frozenset；
- nested code object 的 bytecode、arguments/flags、names/vars/freevars/cellvars 和递归 constants；
- docstring marker 被忽略；line table、first line number、memory address 被排除；
- 未支持常量不回退到 `repr`，而是令 index 为 Unknown。

核心结果：

| Metric | V0 | V1 |
|---|---:|---:|
| same-process stable | 11/11 | 11/11 |
| fresh-process/hash-seed stable | 3/11 | 11/11 |
| Supported | 11/11 | 11/11 |
| registered entries dropped | — | 0 |
| serialized bytes, 11 bundles | 474,337 | 504,588 |
| per-unit cold median 的中位数 | 125.297 ms | 130.512 ms |

V1 为确定性付出约 6.4% bytes 和约 4.2% median-of-medians cold time；deployment-time index 仍然远高于
hot sentinel，不能移回每次调用路径。

## 3. 安全回归

三类 portable reindex attacks 共 33 次：

- class delegating wrapper：11/11 Reject；
- instance delegating wrapper：11/11 Reject；
- instance native override：11/11 Unknown；
- Admit：0；
- baseline restoration：33/33。

9/9 synthetic source fixtures 通过，包括 nested code、frozenset hash-seed、format/comment、docstring、
AST、default、closure、referenced global、wrapper、origin 和 native Unknown；两个显式 constant fixtures 在
parent、`PYTHONHASHSEED=1`、`PYTHONHASHSEED=2` 三进程摘要一致。

## 4. 可以恢复与不能恢复的主张

现在可以恢复的窄主张：

> 对已注册、phase-reachable、纯 Python 且常量类型受支持的 callable bundle，SourceIndexV1 可在固定
> Python/framework/runtime 下生成跨新进程稳定的 deployment artifact，并在 cold reindex 时拒绝已测
> Python wrapper replacement；native override 保持 Unknown。

仍不能声称：

- Python/ABI/framework 跨版本 digest 相同；
- native internals 被绑定；
- 并发 validate/apply TOCTOU 已解决；
- 自动发现了完整框架调用边界；P3b 的 slot policy 仍是人工 adapter；
- `HistogramMatching` 已可公开 replay；P3c 明确不修该失败；
- final-blind 已完成。

## 5. 下一步

P3d/EffectV8 candidate 应只处理剩余的 capability-composition 缺口：

```text
final rewrite eligibility
  = semantic effect decision
  ∧ recordable
  ∧ serializable/restorable
  ∧ target-dependency compatible
  ∧ SourceIndexV1 deployment binding
```

该层必须能把 P3b 的 `HistogramMatching` 从 EffectV7 的条件化 semantic Admit 降为
`Unsupported(capability)`，同时保持另外 10 个 replay 单元可部署。它不能修改 P3b/P3c 的既有结果。
