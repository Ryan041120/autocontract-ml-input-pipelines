# H7K registered/owned replay executor 复盘

日期：2026-07-29

## 1. 本轮回答的问题

H7J 用每次调用都执行完整 `validate -> child composition -> apply` 的方式封住了 mutable-record TOCTOU，但随机配对中相对 direct+copy 的总体中位开销为 25%。H7K 检验一个更具体的问题：如果 executor 私有持有 operator target，能否把不会随调用变化的 proof 移到注册阶段，同时保留真正依赖动态输入和 operator 行为的安全检查？

本轮不是新的框架 blind holdout，而是基于已冻结 H7H EffectV7/Kornia proof 的机制与 runtime 优化实验。

## 2. 机制

注册阶段一次性完成并绑定：

- framework、version、repository commit 与 certificate integrity；
- source/target operator graph 等价；
- EffectV7 leaf proof set；
- container child 顺序、leaf binding 与 composite contract；
- 私有 parameter snapshot；
- target factory 产生的每个 pool instance；
- receipt level 与上述内容的 registration digest。

每次调用仍然完成：

```text
sample identity check
-> input schema check
-> private snapshot deep copy
-> exclusive target lease
-> replay apply
-> post-use params digest
-> release output and target
```

`minimal` receipt 不计算 output digest；`audit` receipt 额外绑定 output digest。二者都不省略 post-use params digest。

## 3. 正确性与安全结果

- generic executor self-test：5/5；
- 真实 Kornia correctness/security：14/14；
- wrong sample 与 wrong input schema 均在 operator invocation 前拒绝；
- changed target 和 missing child proof 均在注册阶段拒绝；
- 外部修改原始 params 不影响私有 snapshot；
- operator 修改 working params 时输出不释放；
- direct 与 registered replay 的输出和输入梯度 digest 相同；
- pool=4、4 worker、25 calls/worker：100/100 输出一致、0 error、RNG state 不变；
- 并发运行实际观察到 target slot 0、1、2、3，证明不是退化为单 target；
- executor 账本为 103 次成功、2 次前置拒绝、103 次 operator invocation，前置拒绝没有偷跑算子。

## 4. 随机配对性能

三个 profile 各 10 轮，每轮对 direct+copy、H7J atomic、H7K minimal 和 H7K audit 各取 10 次调用中位数，并随机打乱四条路径的顺序。

| Profile | H7K minimal/H7J | H7K audit/H7J | H7K minimal/direct | minimal 更快轮数 | 注册成本 | 对 H7J 摊平 |
|---|---:|---:|---:|---:|---:|---:|
| B1×3×32×32 | 0.819× | 0.834× | 1.139× | 10/10 | 8.337 ms | 2.7 calls |
| B4×3×64×64 | 0.819× | 0.825× | 1.053× | 9/10 | 10.194 ms | 4.1 calls |
| B8×3×128×128 | 0.905× | 0.913× | 1.026× | 10/10 | 8.181 ms | 1.4 calls |

总体中位 H7K-minimal/H7J 为 0.860×，29/30 轮更快，说明缓存静态 proof 有稳定收益。总体中位 H7K-minimal/direct+copy 为 1.053×，因此剩余动态安全税约为 5.3%，不能写成“零开销”。audit/minimal 总体中位为 1.020×；由于分 profile 仍受计时噪声影响，只能说本 workload 中 output digest 的增量较小，不能声称 audit 永远只增加 2%。

break-even 使用保守口径：向 H7K 收取完整注册成本，却没有向 H7J 收取 seal 成本。三个 profile 均在约 1.4–4.1 次调用后摊平。

## 5. Target pool scaling

在 B4×3×64×64、4 client threads、每线程 25 calls 上进行 5 轮随机顺序实验：

| Pool size | 中位 calls/s | 范围 | 相对 pool=1 | 正确轮数 |
|---:|---:|---:|---:|---:|
| 1 | 69.3 | 56.5–72.7 | 1.000× | 5/5 |
| 2 | 78.2 | 73.2–80.7 | 1.129× | 5/5 |
| 4 | 72.1 | 71.7–76.1 | 1.041× | 5/5 |

owned target 是并发隔离条件；pool 大小不是安全等级。CPU 上 pool=2 优于 pool=4，说明 executor 应把 pool size 交给资源/性能策略调优，而不能假设 target 越多吞吐越高。

## 6. 可以声称与不能声称

可以声称：在冻结 Kornia replay policy 和当前威胁模型下，registered/owned executor 保持 H7J 的关键安全端点，并把相对 H7J 的调用时间总体降低约 14%。

不能声称：

- 这不是新的 blind generalization 结果；
- 这不是针对恶意 Python reflection、class monkey patch 或 native memory corruption 的 sandbox；
- receipt 是完整性/审计记录，不是带密钥签名或不可抵赖证明；
- sample ID 仍由 caller 提供，当前机制不阻止 caller 冒充另一个 sample lineage；
- post-use digest 只直接检查 working params；未建模的 target hidden state 必须由 EffectV7 state-effect proof 排除；
- 当前只有 CPU、单 Kornia pipeline 和三个输入 profile，不能外推 GPU、多进程 DataLoader 或其他框架。

## 7. 下一步研究问题

H7K 后最有价值的下一问不是继续减少几微秒，而是解决 lineage 的可信来源：把 caller 声明的 `sample_id` 升级为由 dataset/sampler 产生、跨 DataLoader worker 可验证的 provenance token。该 token 需要绑定 dataset revision、sample index/partner samples、epoch、operator path 与 parameter record，才能把当前“内部完整性正确”推进到“输入来源也不可错配”。

建议下一阶段命名为 H7L：**worker-portable provenance token and replay registry**。
