# R3-P2：Kornia contract invalidation 复盘

日期：2026-07-30
证据等级：已知 H7I pipeline 上的 posthoc/adversarial calibration，不是 blind evidence

## 1. 为什么做这一轮

R3-P1 已表明，source-guided greybox 在 H7H 的 9 个决策单元上能以一条容器规则追平 EffectV7。P2 因此不再比较谁更会做初始 admit/reject，而是固定一个真实 Kornia parameter-replay pipeline，比较四种策略在部署上下文发生漂移时能否让旧结论准确失效：

- repeated dynamic reprobe；
- fixed-witness output snapshot；
- 现有 H7I `ReplayLineageCertificate` v1；
- 新的 measured-source v2 candidate。

协议在 runner 运行前冻结，SHA-256 为：

`2a3d60162afe06fb2bb9210d22f0f9d7d19da9cc43e4b484b37731f5096ae28c`

runner SHA-256：`ce7613fc8b0fba63b7ea249ffd0fdbc699d1c4936c64b53bcc242478046b4dc0`
最终复跑 JSON SHA-256：`0a2bf7362318c680dc3afb9cf0a182a1735192ed265b43444466d60273b7db99`

13 个 case 包含 2 个 benign controls 和 11 个 required invalidations，覆盖 framework/version、commit、sample lineage、operator configuration、child order、input schema、parameter record、child completeness、unsupported child、certificate integrity 和 same-commit executable callable replacement。

## 2. 结果

| Policy | Required invalidation recall | Benign preservation | False accepts | Median ms | Runtime calls |
|---|---:|---:|---:|---:|---:|
| dynamic reprobe | 9.1% | 100% | 10 | 40.896 | 48 |
| output snapshot guard | 45.5% | 100% | 6 | 41.490 | 48 |
| lineage v1 | 90.9% | 100% | 1 | 1.922 | 0 |
| measured-source v2 candidate | 100% | 100% | 0 | 252.764 | 0 |

dynamic reprobe 只在一个会导致执行异常或不稳定的 case 上拒绝；它无法从稳定执行中推断 version、commit、sample、configuration 等旧证明是否仍有效。固定 witness 的 output snapshot 能发现部分输出变化，但仍放过纯 metadata/lineage drift、某些 parameter/record drift、certificate tamper 等 6 个 case。

lineage v1 发现 10/11 required invalidations，但放过了最关键的攻击：在 repository commit 字符串保持不变时替换 `RandomAffine.forward`，operator type、MRO、repr 和 child graph 均未变化，因此 v1 仍接纳。

## 3. 必须修正的主张

现有 v1 certificate 只能称为：

> metadata、operator graph representation、parameter record 与 sample lineage bound。

它**不能**再被称为 measured-source-bound 或 executable-code-bound。`repository_commit` 在 v1 中是调用方提供并做字符串相等比较的声明，不等同于对当前 checkout 或内存中 resolved callable 的测量。H7I–H7M 历史结果仍证明各自测试过的完整性、lineage、TOCTOU 和 crash-state 机制，但其 threat boundary 不包含未检测的 same-commit monkeypatch。

## 4. v2 candidate 做了什么

候选修复在 v1 之外加入：

1. 从实际 checkout 读取的 Git HEAD；
2. operator 与 children 的 path/type/MRO；
3. resolved `forward`、parameter generation 与 transform callables 的 canonical AST digest；
4. 对无法读取源码的 callable 使用 code-object fallback，完全无法解释时应进入 unsupported/unknown。

在本轮中，v2 对 11 个 required invalidations 全拒绝并保留 2 个 benign controls；synthetic canonicalization control 也确认 comments/formatting 不改变摘要，而可执行表达式改变会改变摘要。

但 v2 尚未冻结，且最终复跑中逐次重新解析源码的中位成本约 252.8 ms，明显高于 v1 的 1.9 ms。合理实现应把 source index 放在 registration/deployment boundary 一次性计算并缓存，热路径只比较已测 digest；在完成跨进程、native callable、descriptor、decorator 和 cache invalidation 测试前，不能把本轮结果升级为正式贡献。

## 5. 下一步

R3-P2b 应实现 measured source index 的注册时缓存，并明确三类成本：cold source indexing、deployment revalidation、per-invocation hot check。必须加入：

- cache key 绑定 repository worktree state，而不只 HEAD；
- dirty tracked file、untracked import shadow、class/instance monkeypatch；
- decorated/bound/descriptors 与无法 inspect 的 native callable；
- equivalent reconstruction、comment/format-only change、docstring-only change等 benign controls；
- fail-closed Unknown，而不是把 unsupported 当安全。

随后 R3-P3 才做跨框架 transfer。若 source index 规则迅速膨胀或高 Unknown 导致 coverage 不可接受，应如实把贡献边界收缩为受支持 Python/Kornia replay graph，而不是继续扩展声称。
