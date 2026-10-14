# AutoContract reorder-final 独立选对与标注指南（P5N v0）

## 1. 这份指南解决什么问题

本轮只评估 **operator reorder**，不评估 cache 或 registered parameter replay。每个评测单元是一个精确绑定的命题：在固定框架版本、源码、两侧配置、输入域、异常语义和 RNG assignment 下，各调用一次 `left→right` 与 `right→left` 是否观测等价。

“算子通常可以交换”“文档说是 pure”“有限测试没发现差异”都不是 strict `Commutes` 证据。

## 2. 角色与信息隔离

| 角色 | 可以看到 | 预测密封前不得看到 |
|---|---|---|
| selector | 本指南、污染登记表、候选框架公开源码/文档 | AutoContract predictions、receipts、private oracle、P5K–P5M pair labels |
| primary/reviewer | sealed public manifest、精确源码/配置/输入域、自己制作的证据 | analyzer predictions 与 receipts |
| adjudicator | 两份独立标签及证据 | analyzer predictions 与 receipts |
| oracle custodian | private oracle、salt、public manifest | 不向 analyzer 泄漏任何 label/rationale/witness |
| analyzer operator | sealed public manifest、公开源码、oracle commitment、冻结 analyzer bundle | private oracle 与 adjudication record |
| evaluator | sealed predictions、commitments；reveal 后读取 oracle | 不得在评分时修改 prediction、oracle 或 metric gate |

参与 P5K–P5M 规则设计、调试或阅读私有标签的人不能声明为独立 selector/annotator。内部 AI 角色扮演只能做工具自测。

## 3. 选对要求

1. 选择 20–40 个 pair，至少 3 个框架、2 个数据领域。
2. 框架和 exact symbols 必须按 `benchmark/final_v1/contamination_registry.json` 检查；开发期已见对象不能计入 novel final。
3. 每个 pair 固定 release、40 位 commit SHA、framework source-tree SHA-256、operator type、完整 configuration 和 SourceIndex digest。
4. 固定 input domain：representation、layout、channel、dtype、device、finite/value/shape 范围及 schema artifact hash。
5. 固定 operation context：每侧调用一次；global sequential 或 operator-keyed RNG；两种顺序从同一 pre-pair state 开始；比较 output、definedness/exception 和 RNG post-state。
6. inclusion reason 只能说明覆盖目的，例如领域、随机性组合或 API 类型，不能写入预期 label、反例或安全结论。
7. selector 在 public manifest 中声明 `selection_independent_of_analyzer=true`；若做不到，必须停止使用“independent”措辞。

## 4. 私有三分类 oracle

### Commutes

对声明输入域中的所有输入，两种顺序均有相同 definedness；若成功则 exact output 相同；若异常则异常语义相同；执行后 Python/NumPy/framework RNG state 相同。必须提供 formal proof 或逐源码 manual proof、明确 premises 和 evidence anchors。有限差分阴性不能单独支持该标签。

### Noncommutes

存在至少一个域内输入使 output、definedness/exception 或 RNG post-state 不同。必须保存一个可复现 witness：seed、输入 digest、两种结果 digest 和 reproduction-command digest。一个有效 witness 即足够推翻交换性。

### Unknown

既没有足够的通用证明，也没有可复现反例；包括 native/boundary/rounding 语义不清、输入域过宽或证据冲突。Unknown 不是失败标签，也不得为了提高 coverage 强行二分类。

primary 与 reviewer 独立给标签；不一致由 adjudicator 处理。oracle 中保留原始两票、adjudicated label、confidence、rationale、premises/witness、reviewed_by 和 disagreement count。

## 5. 密封顺序

1. selector 完成并 seal public manifest；此后不得增删 pair。
2. primary/reviewer 完成 private oracle，custodian 生成随机 32-byte salt 和 oracle commitment；只向 analyzer 发布 commitment。
3. `freeze-public` 重新验证 analyzer artifacts 的真实文件 SHA，生成不含 private oracle instance path 的 public freeze。
4. analyzer 一次性生成所有 pair predictions，包含 Supported/Unknown/Unsupported、assurance、reason、receipt digest、generation time 和 prospective adapter minutes。
5. `seal-prediction` 绑定 public manifest、producer bundle 和完整 prediction artifact。
6. 只有 prediction seal 完成后才 reveal private oracle；先验证 oracle commitment 与 prediction seal，再评分。

## 6. 固定报告顺序

1. unsafe Supported：oracle=`Noncommutes` 但 prediction=`Supported`，门槛必须为 0；
2. unresolved Supported：oracle=`Unknown` 但 prediction=`Supported`，final 强主张门槛为 0，需独立复核；
3. Unknown/Unsupported 数量及完整分母；
4. 在 oracle=`Commutes` 上的 strict Supported coverage，最低 30%；
5. prediction completion；
6. adapter wall-clock、proof generation/verification latency、receipt size 和失败原因；
7. cedar plan/output/RNG/benefit 另表报告，不能用 coverage 替代系统收益。

任何 unsafe Supported 都使当前 verifier version no-go。Reveal 后不得新增 lemma 再把同一 corpus 当 final 重跑。
