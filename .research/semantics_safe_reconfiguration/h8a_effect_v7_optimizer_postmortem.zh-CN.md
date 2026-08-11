# H8A EffectV7 → optimizer integration 复盘

日期：2026-07-29

## 1. 研究问题

冻结的 EffectV7 contract 能否不经过人工重写，直接成为 optimizer 的 semantic gate，并与真实 profiler、一次性注册成本和预期调用 horizon 共同产生 plan decision？

H8A 选择的候选不是 `fresh sampling → parameter replay`。二者随机语义不同，不能仅凭 replay 更快就宣称等价。正式候选定义为：

```text
H7J per-call sealed atomic replay
        ->
H7K registered replay with cached static proofs
```

两侧都处于 `kornia.params_provided / replay_apply`，使用相同参数 lineage、child contracts 和动态输入检查。变化的是静态 proof 在注册期完成并跨调用摊销。

## 2. Contract adapter

H8A 为每个 leaf 重新运行冻结的 H7H `AnalysisV7` 和 `validator_v7`，并把以下内容绑定进 `analysis_sha256`：

- public symbol、source/binding hash 与 repository commit；
- EffectV7 与 Kornia adapter hash；
- configuration、phase、reachable methods 与 evaluated guards；
- reachable state/callable/RNG/delegation effect；
- validator reasons 与 H7J leaf-proof digest。

三个 leaf 为 `RandomHorizontalFlip`、`RandomAffine` 和 `ColorJiggle`。在 `params_provided/replay_apply` 下 3/3 admit；切换到 `params_absent/sample_apply` 后 0/3 admit，均出现 `reachable_sampling_rng`，而且 supplied-params leaf proof 产生 configuration/decision mismatch。

组合 contract digest 为：

```text
c838d8468d22bf0700eb38681262d31a65de65e5ad794788403df83366a5f476
```

篡改单个 leaf proof digest 会拒绝整个 leaf，说明 optimizer 接收的不是未绑定布尔值。

## 3. 真实 cost model

Profiler 直接读取已有 H7K 随机交错配对实验，不把跨实验 ratio 拼在一起。对每个 profile 使用配对轮次的 H7J/H7K median，并计入 H7K registration cost：

```text
net_benefit(H) = H × (median_H7J - median_H7K) - registration_ms
select = semantic_admit AND net_benefit(H) > 0
```

| Profile | Saving/call | Registration | Measured break-even | H=1 | H=10 |
|---|---:|---:|---:|---|---|
| B1×3×32×32 | 3.112 ms | 8.337 ms | 2.68 calls | REJECT | SELECT |
| B4×3×64×64 | 2.492 ms | 10.194 ms | 4.09 calls | REJECT | SELECT |
| B8×3×128×128 | 5.740 ms | 8.181 ms | 1.43 calls | REJECT | SELECT |

短 horizon 全部因无法摊销注册成本而拒绝；10-call horizon 全部选择。人工构造的巨大正收益也不能绕过 semantic reject。

## 4. 结论

H8A 第一次闭合了真实路径：

```text
EffectV7 reachable contract
  -> bound leaf proofs
  -> composite ContractVerdict
  -> measured profiler + horizon
  -> optimizer select/reject
```

14/14 integration checks 通过。它支持“AutoContract contract 可以作为 optimizer candidate gate”这一机制结论，但仍不是新 blind holdout，也不支持端到端 input throughput 主张。

## 5. 限制与下一步

- 使用 H7H calibration leaves 和既有 H7K profile，是 mechanism integration，不增加 EffectV7 外部有效性；
- 当前优化是安全执行路径的 proof amortization，不是 cache placement/reorder 带来的训练吞吐收益；
- profile 来自 CPU 三种 shape/batch，尚无 CUDA、I/O 或多 worker workload；
- horizon 由调用方提供，尚未从 optimizer workload model 自动推断；
- human-oracle benefit 指标仍缺真实 `cache_prefix` 候选。

下一项独立实验应实现 `cache_prefix`：把 H5 的 deterministic-prefix contract、cache build cost、warm/cold horizon、trace/model oracle 接到同一 boundary，并与 human oracle 对比性能收益，而不是继续扩展 replay protocol。
