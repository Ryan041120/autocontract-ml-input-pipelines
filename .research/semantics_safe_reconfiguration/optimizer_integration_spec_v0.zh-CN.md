# AutoContract optimizer integration v0

日期：2026-07-29
状态：MVP 接口冻结；这是 optimizer 边界实验，不是新的 EffectV7 blind result。

## 1. 为什么这是下一步

H6–H7H 回答的是“能否恢复 operator/context effect”，H7I–H7K 回答的是“已注册 replay 如何安全执行”。两者之间仍缺一个论文级闭环：**cost optimizer 提出什么候选，AutoContract 如何把 effect contract 变成候选级 proof obligation，以及被拒绝的候选如何保证不会因收益很高而重新进入计划。**

因此这一步不改 cost model，也不增加 EffectV8。AutoContract 被实现为 optimizer candidate boundary 上的 fail-closed semantic gate：

```text
logical pipeline
      |
      v
candidate generator -----> profiler / cost score
      |                            |
      v                            |
AutoContract contract gate        |
      |                            |
      +-----------> plan selector <+
                         |
                         v
              registered executor
```

## 2. 接口对象

### RewriteCandidate

- `candidate_id`：稳定的 pipeline/position/rewrite identity；
- `rewrite_kind`：MVP 为 `adjacent_swap`，后续扩展 `cache_prefix`、`parameter_replay`；
- `pipeline_id`、`position`、`operators`：候选作用域；
- `optimizer_score`：由外部 profiler/cost model 提供；AutoContract 不修改该值；
- `context_id`：未来绑定 configuration、phase、worker/data/version assumptions。

### ContractVerdict

- `policy`：registry/static/dynamic/hybrid/manual/oracle；
- `admitted`：是否已满足该 rewrite 的语义义务；
- `reasons`：fail-closed 的稳定理由类别；
- `contract_sha256`：绑定参与判定的 operator contracts 和 validator evidence；
- `evidence_class`：自动分析、人工 hint 或 oracle upper bound。

### CandidateAssessment

最终候选只能在下式为真时进入 plan selector：

```text
eligible = contract.admitted AND optimizer_score > 0
```

cost model 没有覆盖 semantic reject 的权限。缺失 contract、未知 effect、未满足 mode/phase obligation、外部 effect、cardinality/lineage 不兼容都必须在进入 plan search 前拒绝。

### PlanDecision

MVP 对相邻 swap 使用 interval-safe selector：共享 operator 的两个 swap 不能同时选择。未来接 cedar/其他 optimizer 时，这一层可替换为其既有 plan search；`ContractVerdict` 的语义保持不变。

## 3. Rewrite obligations

MVP 的 `adjacent_swap(A,B)` 需要：

1. A/B contract 都 resolved；
2. construction effect 已经完成或与实例生命周期绑定；
3. execution 不依赖未绑定 external state；
4. state role 为 immutable 或具有当前 phase 的 replay proof；
5. record scope、input/output cardinality、sample identity 与 target signature 兼容；
6. RNG source 已知且能按 stable operator identity 虚拟化；
7. A/B 的具体交换关系通过规则、可信 registry 或 candidate-level semantic check 证明。

注意：operator contract 被 admit 不等于任意两个 operator commute；第 7 条始终是 candidate-specific obligation。

## 4. 统一 baseline

| Policy | 可使用的信息 | 作用 |
|---|---|---|
| `fail_closed` | 无 | 安全性/机会下界 |
| `registry_only` | 小型可信人工 registry | cedar-style sparse manual hints |
| `static_only` | source/bytecode | 静态分析消融 |
| `dynamic_only` | finite runtime probes | 展示 finite-test false accept 风险 |
| `hybrid` | registry + static + dynamic，冲突时保守 | AutoContract 机制原型 |
| `manual_full` | 每个 operator 的完整人工 effect hint + 同一 validator | 人工标注基线 |
| `human_oracle` | sealed candidate oracle | 安全机会与 plan 上界，不是可部署方法 |

所有 policy 必须接收相同 candidates、optimizer scores 和 non-overlap constraints。

## 5. MVP 指标

- candidate-level `TP/FP/FN/TN`；
- known-unsafe false accepts（硬门槛 0）；
- safe candidate recall（工作门槛 80%）；
- plan-level selected safe/unsafe；
- 相对 human oracle 的 safe opportunity coverage；
- proof/reason coverage；
- 自动 policy 相对 manual-full 的 annotation accounting。

MVP 把每个正分候选记为一个“opportunity unit”，所以 opportunity coverage 只能验证计划接口和冲突处理，**不能当端到端性能收益**。RQ3 的 `human-oracle benefit` 必须在接入真实 profiler 后用吞吐或延迟测量。

## 6. MVP 成功与停止条件

成功条件：

- semantic reject 不受任意高 optimizer score 影响；
- plan 中没有重叠 swap；
- hybrid 在 H3 pilot 上 unsafe FA=0、safe recall≥80%；
- dynamic-only 的已知 false accept 被完整保留，不能通过事后修补隐藏；
- 每个决定都有稳定 reason 和 contract digest。

完成本 MVP 后，下一步不是继续调 H3。应把同一接口适配到 EffectV7 `AnalysisV7/validator_v7`，再将真实 cache/replay profiler 接入 `optimizer_score`，最后封存 final blind corpus。
