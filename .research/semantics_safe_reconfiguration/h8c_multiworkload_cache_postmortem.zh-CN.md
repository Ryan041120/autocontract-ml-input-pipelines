# H8C multi-workload cache benchmark 复盘

日期：2026-07-29

## 1. Protocol status

H8C 在正式完成运行前冻结了 runner、protocol、stateless helper 与运行时版本：

```text
runner_sha256   = 6848690c1b57b5e989ca5f48388bb0f7206c8ded40f1d4fa29c9c961e9a3ff6c
protocol_sha256 = 66f0f35a405f65ccb8e3d6771bbb055fe5d608d6e8840384445a878ad22938e4
```

冻结后的第一次启动被编排器的短 timeout 中止，未写出正式结果；runner、protocol 和 thresholds 没有修改。随后完成一次完整 registered run。严格意义上这是一次 aborted launch 加一次 completed run，因此不能包装成 one-shot blind evidence；H8C 本来也只注册为 internal calibration。

## 2. Workloads

| Workload | Domain | Oracle | Threat |
|---|---|---|---|
| `cv_safe_prefix` | CV | admit | deterministic prefix + operator-keyed suffix RNG |
| `audio_safe_prefix` | audio | admit | content-bound WAV read + deterministic spectral prefix |
| `cv_hidden_rng_prefix` | CV | reject | 输出看似确定但 prefix 推进 global RNG |
| `cv_external_state_prefix` | CV | reject | cache build 与 use 之间环境变量变化 |
| `cv_full_cache` | CV | reject | cache 跨过 epoch-varying suffix，冻结 augmentation diversity |

每个 workload 使用 48 samples、4 epochs、3 次交错顺序配对测量。两个 safe candidates 与三个 unsafe candidates 的 cold-cache 净收益均为正，因此安全结果不是由 cost gate 碰巧拒绝危险候选造成的。

## 3. Registered results

| Policy | Safe recall | Unsafe FA | Unsafe plan selections | Benefit-positive safe workloads | Mean oracle benefit coverage |
|---|---:|---:|---:|---:|---:|
| fail-closed | 0% | 0 | 0 | 2 | 0% |
| registry-only | 50% | 0 | 0 | 2 | 50% |
| static-only | 100% | 0 | 0 | 2 | 100% |
| dynamic-only | 100% | 3 | 3 | 2 | 100% |
| hybrid | 100% | 0 | 0 | 2 | 100% |
| manual hint | 100% | 0 | 0 | 2 | 100% |
| human oracle | 100% | 0 | 0 | 2 | 100% |

Dynamic-only 在 safe opportunity 和 benefit 上看起来与 oracle 一样好，但同时把三个有正收益的 unsafe candidate 全部选入计划。这说明仅报告 performance opportunity recall 会掩盖严重 soundness 问题。

Hybrid 保留 2/2 safe candidates、拒绝 3/3 unsafe candidates、unsafe plan selection=0，并在两个 benefit-positive workloads 上达到 100% oracle benefit。12/12 registered checks 通过。

## 4. Semantic observations

- safe CV/audio 的 raw 与 cached trace 完全一致，且每个 sample 在四个 epoch 均保持 4 个不同输出；
- hidden-RNG prefix 的 cache hit 改变后续 global-RNG suffix trace；
- external-state prefix 在 build/use 环境漂移后产生 stale cached value；
- full cache 的 per-sample diversity 从 4 降为 1；
- 三个 unsafe candidates 的实测净收益分别为 0.322 s、0.481 s 和 1.146 s，证明 cost model 会主动偏爱它们。

## 5. 仍然不能作为 final result 的原因

1. source bodies 与 oracle 由同一研究过程产生，没有独立 annotator；
2. static-only/hybrid 的 H8C decision 是按注册 threat class 编码的 calibration policy，不是 EffectV7 对全新源码的一次性推断；
3. 数据规模小，audio 为确定性合成 WAV，CV 为生成 tensor；
4. 只有五个 candidates 和两个 benefit-positive safe workloads；
5. CPU-only，没有 DataLoader、GPU training 或多框架真实 pipeline；
6. 冻结后存在一次无输出的 aborted launch。

## 6. 主线下一步

H8C 已经证明 benchmark schema、cost accounting、semantic oracle 与 baseline summary 能工作。下一步不再增加 H8D 机制，而是准备 final benchmark handoff pack：

- 公共 candidate manifest，不含标签；
- 私有 oracle 文件与 commitment hash；
- 学长/第二标注者的 annotation guide；
- EffectV7/static/dynamic/manual adapter 接口；
- 至少一个未见框架或未见 release 的真实 pipeline corpus；
- freeze、unseal、disagreement adjudication 和 one-shot run checklist。

完成独立 oracle 之前，H8C 只作为 calibration/ablation design evidence。
