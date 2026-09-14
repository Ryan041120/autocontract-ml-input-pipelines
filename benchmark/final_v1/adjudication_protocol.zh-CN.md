# Final v1 标注复核与仲裁协议

## 独立性要求

- 至少一名 primary 和一名 reviewer，二者都不能参与 AutoContract analyzer、optimizer policy 或阈值开发。
- primary 在提交带时间戳的初稿哈希前，不得看到 reviewer 的标签；reviewer 同理。
- 全部 `known_unsafe`、全部低置信度 unit 和随机抽取至少 30% 的其余 unit 必须双人复核。
- 语料策展者可以解释 manifest 字段，但不能暗示期望判断。项目开发者不能担任最终仲裁人。

## 仲裁流程

1. 两份独立记录冻结后，由 oracle 保管人比较 decision、known_unsafe、coarse reason 和五类 semantic oracle。
2. 一致项直接合并，保留双方 evidence anchors。
3. 不一致项先交换证据而非结论；双方各自说明哪条可观察语义和哪个源码事实决定判断。
4. 仍不一致时交给第三名独立 adjudicator。adjudicator 只能使用封存源码和预注册检查，不得查看 analyzer 预测。
5. 若证据仍不足，最终标签为保守拒绝、`known_unsafe=false`、`unsupported_or_ambiguous`，并降低 confidence。
6. 每次修改记录原判断、最终判断、原因和人员 ID；`disagreement_count` 是初始不一致 unit 数，不能改成仲裁后剩余数。

## 完成门槛

private oracle 只有同时满足以下条件才可 commitment：

- unit ID 与 public manifest 完全一一对应；
- 每个 unit 至少一个有效 reviewer；
- `admit` 必须对应 `known_unsafe=false` 且 reason 为 `none`；
- `known_unsafe=true` 必须对应 `reject`；
- 所有低置信度与争议项已处理；
- adjudication status 为 `complete`；
- 至少两名独立标注者的身份和利益冲突披露完整。

commitment 之后只能修正传输或格式错误。任何语义标签变化都必须废弃整个 benchmark ID，重新选择版本、重新承诺；不能静默覆盖。
