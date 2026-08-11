# Final-v1 baseline 与 horizon 修订规范

日期：2026-07-30
状态：评审后前置修订；必须在接触 final unit 和 private oracle 前冻结实现与配置

## 1. 目的

本修订解决两个可导致 final-v1 结论失真的风险：output-only dynamic baseline 过弱，以及 optimizer horizon 可由实验者手工选择。它不修改 H8A–H8C 的历史协议、输出或 headline。

## 2. Dynamic baselines

### `dynamic_output_only`

只在同一公开上下文和固定输入上做有限输出差分。它是历史 `dynamic_only` 的明确重命名，用于量化单点输出检查的局限，不用于代表动态测试的最佳能力。

### `dynamic_stateful`

每个 unit 使用相同、预注册、与 oracle 标签无关的探针计划：

- 同一实例连续调用；
- 新实例同 seed 调用；
- 相邻 epoch/context 调用；
- 调用前后 Python、NumPy、Torch RNG state digest；
- 调用前后可序列化对象状态 digest；
- 对 public manifest 声明的 environment/configuration keys 做固定扰动；
- 对 stochastic unit 记录重复输出 diversity，而非要求逐次相等。

探针结果只能产生 `evidence / conflict / unknown`。未观察到差异不构成语义证明；`dynamic_stateful` 不得读取 private oracle、gold reason 或 unit-specific threat tag。

### 公平性约束

- 两个 dynamic baseline 使用相同 candidate set、公开输入、wall-clock/调用次数预算和失败 taxonomy；
- 探针配置及实现 hash 在 corpus 解封前写入 commitment；
- crash、timeout、unserializable state 不能从分母删除；
- 报告 output-only 到 stateful 的增量，同时将 hybrid 与两者分别比较。

## 3. Horizon derivation

workload manifest 至少声明：

- `dataset_cardinality`；
- `epochs` 或 `planned_full_scans`；
- `batch_size`、`drop_last`；
- `worker_count`、`replica_count`；
- `candidate_invocations_per_sample` 或 `per_batch`；
- `reuse_scope`：call / epoch / run / cross-run；
- `invalidation_events` 与 cache/configuration validity scope。

runner 只从 manifest 和公开 execution plan 推导有效 horizon。概念上：

```text
effective_horizon = planned_invocations_within_validity_scope
net_benefit = effective_horizon * measured_saving_per_invocation
              - registration_or_build_cost
              - validation_and_storage_cost
```

不同 rewrite kind 可以有不同的 invocation unit，但必须在预测前冻结。主结果使用 manifest-derived planned horizon；另行报告保守下界与上界。若三档导致不同决策，标为 `horizon_unstable`，不得只选择收益为正的一档作为 headline。

## 4. 必须写入 prediction artifact 的字段

- `dynamic_probe_spec_sha256`；
- `dynamic_probe_budget`；
- `horizon_source = workload_manifest`；
- `horizon_inputs` 与 `effective_horizon`；
- `horizon_low / horizon_planned / horizon_high`；
- `decision_stability`；
- profiler measurement artifact hash；
- contract、candidate、environment 和 execution-plan hashes。

## 5. 冻结门槛

只有在以下条件全部通过后，才能交付独立 corpus curator：

1. synthetic safe/unsafe unit 上的 baseline self-test；
2. 标签不可见性与 fixed-budget 检查；
3. manifest 缺字段、负数、溢出、scope 冲突均 fail closed；
4. 同一 manifest 重跑得到相同 horizon；
5. 改变 manifest 会改变 digest 并留下 append-only event；
6. runner、schema、probe plan 和统计代码 hash 已冻结。
