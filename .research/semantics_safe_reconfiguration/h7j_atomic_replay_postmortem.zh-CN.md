# H7J sealed atomic replay 复盘

日期：2026-07-29

## 1. 目标

H7I 证明了 lineage certificate 和 child composition 的机制可行性，但 validate 与 apply 分离时存在 mutable-record TOCTOU。H7J 将安全条件实现为一个锁内原子边界：

```text
private snapshot copy
-> lineage validation
-> child EffectV7 proof composition
-> operator apply on a per-call working copy
-> post-use parameter digest
-> release output + receipt
```

原始 record 与 target 暴露的 `_params` 永远不会成为下一次调用的输入。若前置检查失败，operator 不得被调用；若 operator 内修改 working record，输出不得返回。

## 2. 自动 leaf proofs

H7I 的手写 leaf policy 已移除。H7J 对 container 的三个 child 调用冻结的 H7H Kornia adapter 与 EffectV7，在 `kornia.params_provided/replay_apply` 下重新生成 proof。每条 proof 绑定：

- public defining symbol；
- symbol binding SHA-256 与 source SHA-256；
- Kornia repository commit；
- EffectV7 与 adapter SHA-256；
- reachable method set、decision 和 reasons；
- proof 自身摘要。

RandomHorizontalFlip、RandomAffine、ColorJiggle 三条 proof 均为 admit，proof set 校验通过。H7H 冻结文件与 commit 未修改。

## 3. 基础与真实运行结果

泛型 atomic executor self-test 4/4：正常 apply、receipt/output 绑定、前置失败零调用、operator 修改 params 时不释放输出。

真实 Kornia H7J 测试 12/12：

- source/target output trace 一致；
- receipt 同时绑定 certificate、pre/post params、child contract、leaf proof set 与 output；
- seal 后串行修改原始 params 不影响输出；
- 修改 target 暴露的 `_params` 不污染下一次调用；
- wrong sample 与缺 child proof 均在 operator 调用前拒绝；
- 恶意测试 operator 修改 working params 后，post-use check 拒绝且无输出返回；
- atomic replay 输入梯度与 direct replay 完全一致；
- 4 worker 共享 target 共 100 次调用，在另一线程持续修改原始 params 时得到 100/100 相同 output/receipt、0 error；
- 并发 replay 前后 Torch RNG state 不变。

这满足 H7J 预先定义的成功判据，但作用域仍是同进程非恶意/半可信环境。直接反射私有 snapshot、monkey patch validator 或恶意内存修改不在威胁模型内。

## 4. 性能

早期两个顺序固定的单次结果互相矛盾（一次显示 +33.8% 开销，另一次显示 -10.9%），不能采信。随机交错配对实验使用三个输入规模，每个规模 10 轮，每轮分别取 10 次调用的中位数；atomic 在 30/30 轮都更慢：

| Profile | Median atomic/direct-copy | Range | Atomic faster |
|---|---:|---:|---:|
| B1×3×32×32 | 1.408× | 1.231–1.527× | 0/10 |
| B4×3×64×64 | 1.259× | 1.100–1.323× | 0/10 |
| B8×3×128×128 | 1.100× | 1.063–1.149× | 0/10 |

总体中位 atomic/direct-copy 为 1.250×。固定 bookkeeping 成本随 workload 增大而相对下降。

单项 ablation 的中位成本约为：deepcopy 1.89 ms、full validation 1.15 ms、child composition 0.64 ms、params digest 0.51 ms、output digest 0.20 ms。它们存在重复哈希，不能简单相加作为精确开销，但明确指出优化方向。

## 5. 科学判断

H7J 为 **mechanism/runtime PASS，非 blind**。主要贡献不是“一个锁”，而是把静态 EffectV7 proof、参数 lineage、容器组合、运行时原子使用和可审计 receipt 串成一个闭环，并用并发 mutation 反例验证其边界。

不能声称：

- 任意 Python 反射或恶意代码下安全；
- 共享 operator 在没有该 executor 锁的外部访问下线程安全；
- atomic replay 没有性能成本；
- 当前 `repr`-based operator graph digest 是稳定的跨版本语义 IR。

## 6. 下一步 H7K

最值得做的是 registered/owned executor：

1. 注册 target 时一次性验证 operator graph、EffectV7 child proofs、framework/version/commit 和固定 input schema；
2. 私有持有 target 或 target pool，消除外部并发修改；
3. 每次调用只做 sample identity、working-copy、apply 和 post-use mutation check；
4. output digest 改为可配置 receipt level，避免每次完整复制输出到 CPU；
5. 使用结构化 constructor/config IR 替代 `repr` digest；
6. 评估单 target 锁与 per-worker target pool 的吞吐差异。
