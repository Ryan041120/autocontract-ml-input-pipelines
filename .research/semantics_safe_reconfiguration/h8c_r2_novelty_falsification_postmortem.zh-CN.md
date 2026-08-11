# H8C-R2 novelty falsification 复盘

日期：2026-07-30
状态：synthetic internal calibration；不是 final benchmark evidence

## 1. 问题与预注册

H8C-R1 发现七次 stateful probe 在五个已知 H8C workload 上与 hybrid 持平。R2 因此不再比较弱 output-only baseline，而是预注册六档动态调用预算 `1/3/7/15/31/63`、固定 Van der Corput 输入序列、固定 worker schedule 和 18 个参数化 case，观察有限探针的 detection-budget frontier。

协议在运行前记录，SHA-256 为：

`5b27b3e151afdc7defa9f84fae44a815ee88e3b8a0eefc35b416b20e905edba2`

fixtures SHA-256：

`166a001bc0d1c2fdbe73ace6bbae4c7a69c19019714486a83dd0648695403285`

runner SHA-256：`51c7542c4cc9326ec30c35c4b3f3dd42f5e19251a235dcbee8316810b220ef3e`
result SHA-256：`e19623a502ac3cce06a3094e85ccc0ab90955530b9b7c6c584be6e7c001d5a0f`

## 2. 结果

| Policy | Budget | Unsafe detection | False accepts | Safe recall | Median ms/case |
|---|---:|---:|---:|---:|---:|
| EffectV7-style contract | 0 | 100.0% | 0 | 100.0% | 6.477 |
| stateful dynamic + bindings | 1 | 14.3% | 12 | 100.0% | 4.728 |
| stateful dynamic + bindings | 3 | 21.4% | 11 | 100.0% | 7.601 |
| stateful dynamic + bindings | 7 | 50.0% | 7 | 100.0% | 13.823 |
| stateful dynamic + bindings | 15 | 64.3% | 5 | 100.0% | 21.734 |
| stateful dynamic + bindings | 31 | 78.6% | 3 | 100.0% | 45.012 |
| stateful dynamic + bindings | 63 | 92.9% | 1 | 100.0% | 88.511 |

动态策略能立即发现 gradient detach 与 source binding mismatch；worker/mode RNG 在七次预算内全部暴露。rare-input RNG 和 periodic global state 随预算增加按预注册阶梯逐步暴露。未绑定 external-file read 在 63 次调用后仍没有运行时反例，因为文件在当前 probe context 中未变化。

EffectV7-style policy 使用真实 `reachable_nodes` 保守路径遍历和预注册的通用 effect patterns，在不执行 operator 的情况下拒绝 14 个 unsafe case，并通过 matching file digest discharge 保留 content-bound file safe control。9/9 registered checks 通过。

## 3. 可以支持的结论

1. 合理 stateful dynamic 的检测能力会随预算显著提升，不能再称其为天然弱基线；
2. 有限预算在未执行数据分支和长周期行为上存在明确 coverage/cost frontier；
3. source contract 的潜在增量是提前发现路径和依赖，并把它们绑定成可失效 artifact；
4. content binding 对减少静态分析的过度保守很重要，单纯“看到文件读取就拒绝”不是可接受设计。

## 4. 不能支持的结论

- 不能把 contract 的 100% 当成 EffectV7 真实跨框架准确率；
- threat fixtures 与通用 pattern 在同一研究轮设计，虽然 protocol 先记录，仍不是独立 holdout；
- `EffectV7-style` 只复用了 reachable path engine 和小型 threat adapter，不等于完整冻结 EffectV7 在真实框架上的结果；
- 动态策略未使用 source-guided/greybox input generation；不能据此声称优于所有动态测试；
- timing 是单轮小源码 calibration，不能作为系统 overhead headline；
- 没有 native extension、descriptor、并发、crash/timeout 或未知依赖。

## 5. 对创新定位的影响

论文不再把创新写成“hybrid 比动态检测更准确”。更稳健的表述是：

> AutoContract 将 ML-specific effect discovery、rewrite obligation 和 source/configuration/content invalidation binding 合成一个可审计 optimizer gate；动态测试作为反例搜索补充，但有限 probe evidence 本身不能携带未来 context 的完整失效条件。

准确率增量仍需要真实 source holdout 证明；即使强 greybox dynamic 最终检测率相近，contract-carrying invalidation、reason audit 和 annotation accounting 仍可能构成系统价值。

## 6. 下一轮 R3：真实源码 + greybox 强基线

下一轮不再增加 synthetic threat。使用已污染、因而不能当 final 的 H7 真实 framework sources 做方法校准：

1. `dynamic_stateful_bound`：当前黑盒状态探针；
2. `dynamic_source_guided`：允许读取 public source/branch constants 生成输入与 context，但不能读取 oracle；
3. `EffectV7`：冻结 analyzer/adapter；
4. `manual_full`：人工 effect hint 上界。

比较必须使用同一 wall-clock budget，而不只比较调用次数，并报告：unsafe FA、safe recall、Unknown、timeout、source-guidance/adapter LOC、运行时调用数与可审计 reason coverage。

若 greybox dynamic 在真实源码上以更低总成本达到 EffectV7 的安全/coverage，则 detection novelty no-go，论文转向 contract-carrying invalidation artifact；若 EffectV7 在未执行路径上仍有稳定增量，才保留 C1 的主要创新地位。
