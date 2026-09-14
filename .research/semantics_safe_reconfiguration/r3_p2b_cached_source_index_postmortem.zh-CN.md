# R3-P2b：cached measured-source index 复盘

日期：2026-07-30
证据等级：已知 H7I Kornia replay pipeline 与 synthetic source fixtures 上的 posthoc mechanism calibration；不是 blind evidence

## 1. 研究问题与冻结

R3-P2 的 measured-source v2 能阻止 same-commit callable replacement，但每次验证都执行 Git、读取源码并解析 AST，最终复跑中位约 252.8 ms。P2b 将安全边界拆为三层：

1. registration：构建 portable canonical executable index，并测量实际 repository identity；
2. deployment：重新构建 portable index 作一次性比较，然后建立 process-local sentinel；
3. hot path：只比较 resolved function/code identity，以及 defaults、closure 和 referenced-global dependency fingerprint，不执行 Git、源码读取或 AST 解析。

协议在正式 runner 前冻结。工件 SHA-256：

- protocol：`12449c5735794285f5b8d2bc4312c8509da52183419fe6532f127ed1adc41242`
- source-index engine：`02a10103e26cb4a55f646428d7e24f14bdf73b133149e29c220a78f38829ab2b`
- runner：`a989de03342eb9ba0027cf89687d1067998e358a6ab03239e897315e6886f7d5`
- result JSON：`2ee08d6568f6d5e944e0c64423177319036b293140bfdadb94479c6039793f56`

## 2. 开发中暴露的边界

首个 indiscriminate index 把真实 pipeline 判为 Unknown，原因有二：

- `typing.Dict/Union` 被误当作不受支持的可变运行时依赖；
- ColorJiggle parameter generator 中的 native `randperm` 被纳入索引，尽管 supplied-params replay 根本不执行采样路径。

最终实现没有给 native sampling 开白名单，而是让 source index 继承 EffectV7 的 phase/reachability boundary，只索引 replay path 的预声明 executable slots。这说明 measured source binding 不是独立于语义分析的通用文件哈希；它依赖“当前 rewrite 实际会执行哪些路径”的契约。

## 3. 结果

真实 Kornia 共 6 个 case：2 个 benign controls、3 个 supported post-deployment mutations，以及 1 个 native override Unknown control。

| Policy | Benign preservation | Supported mutation rejection | Unknown accuracy | False accepts | Median ms/case |
|---|---:|---:|---:|---:|---:|
| cached digest only | 100% | 0% | 0% | 4 | 2.049 |
| hot callable sentinel | 100% | 100% | 100% | 0 | 2.591 |
| cold reindex | 100% | 100% | 100% | 0 | 401.077 |

只缓存 deployment digest 的策略放过 class callable replacement、同一 function object 的 `__code__` replacement、instance `forward` override，并错误接纳 native override。hot sentinel 对三类受支持修改全部拒绝，对 native override 返回 Unknown；两个 benign controls 均接纳。

9 个 source-index fixture 全部满足冻结预期：comments/format 与 docstring-only 改动保持 canonical digest；executable AST、default argument、closure cell、referenced global、decorator wrapper 和 resolved origin 改变均改变绑定；uninspectable native callable 返回 Unknown。

## 4. 成本

| Boundary | 本轮中位/单次成本 |
|---|---:|
| registration index | 363.062 ms |
| deployment revalidation | 481.822 ms |
| sentinel creation | 0.938 ms |
| sentinel-only hot check，200 repeats | 0.669 ms |
| lineage-v1 validation，100 repeats | 1.439 ms |
| cold reindex reference，5 repeats | 407.357 ms |

真实 per-case 中，lineage v1 + sentinel 的中位为 2.591 ms，而只做 v1/cached digest 为 2.049 ms。portable index 当前为 130,493 bytes、27 entries；其中只有 17 个 unique callable definitions。离线诊断显示将重复定义改为 content-addressed references 可把大小估算降至约 87,956 bytes，减少 32.6%，但尚未作为冻结结果实现。

同步盘环境下一次 Git subprocess 约占百毫秒量级，因此把 Git/source/AST 完全移出热路径是主要收益；本轮自动检查也验证 hot call graph 不包含这些 cold operations。

## 5. 当前能支持的结论

> 在受支持、phase-reachable 的 Python Kornia replay graph 上，portable measured-source index 可以在 registration/deployment 时建立；process-local callable sentinel 能以亚毫秒级独立开销发现检查前发生的 class、code-object 与 instance mutation，并对不受支持的 native replacement fail closed。

这使“contract-carrying reconfiguration safety”比 P2 时更具体：contract 不只携带调用方声明的版本字符串，还可以携带实际 executable slice 的 portable measurement，并在部署后用轻量 runtime witness 维护同进程有效性。

## 6. 不能支持的结论

- sentinel 的 `id(function/code)` 是 process-local，不可序列化成跨进程 proof；
- 它只发现 hot check 前已经发生的 mutation，不解决 check 与执行之间的并发 TOCTOU；
- native extension 内部、custom descriptor、动态 `__getattribute__`、JIT/compiled graph 尚未覆盖；
- referenced globals 当前只支持可稳定记录的值；复杂可变对象会导致 Unknown；
- synthetic fixtures 不是跨框架实证；
- cold cost 受 Windows/OneDrive/Git cache 明显影响，不应写成通用性能 headline；
- 0 observed false accept 不等于 soundness。

## 7. 下一步决策

P2c 是可选工程优化：用 content-addressed callable definitions 和 function-layer memoization 减少 portable index 的 32.6% 重复与 cold parse 时间。它不应先于更重要的外部效度问题。

主线下一步进入 R3-P3 cross-framework transfer calibration：

1. 冻结同一 source-guided greybox 与 source-index slot policy；
2. 在已有但已知的 TorchIO、imgaug、Albumentations corpus 上作 posthoc transfer；
3. 分开报告 decision accuracy、Unknown、需要新增的 framework rules、portable-index support 与 hot-sentinel support；
4. 任何规则修改进入新版本并累计 burden；
5. 如果跨框架规则迅速膨胀或 Unknown 过高，则将论文范围明确限制为 supported replay APIs，而不是继续追求通用 Python 主张。

在 P3 前仍不接触 final-blind oracle。
