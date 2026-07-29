# H7I 参数 lineage、child composition 与运行时重配置复盘

日期：2026-07-29

## 1. 研究问题

H7H 的 `params_provided` 仍然是一个过强的布尔前提。H7I 将它拆成可检查的 replay-record obligations：

```text
framework + version + repository commit
+ operator graph digest
+ input schema digest
+ sample identity
+ parameter-record digest
+ child sequence
+ record/replay phase relation
```

证书用于发现错误、过期或被意外修改的记录，不是抵御恶意参与方的数字签名。

第二个问题是能否不再整体拒绝容器。H7I 将 Kornia `ParamItem.name` 绑定到实际 child module，逐 child 检查参数摘要与 replay contract；只有结构完整、顺序正确且所有 child 都接纳时才合成容器接纳。

## 2. 实现

新增：

- `experiments/autocontract_h7i_lineage_certificate.py`：canonical digest、lineage certificate、验证器与递归 child-contract composition。
- `experiments/autocontract_h7i_kornia_reconfiguration.py`：真实 Kornia pipeline 重建、trace/RNG/gradient 与攻击实验。
- `experiments/autocontract_h7i_scaling.py`：三种输入规模、五个随机种子的计时稳健性实验。
- `experiments/autocontract_h7i_posthoc_toctou.py`：验证与使用之间的 mutable-record TOCTOU 审计。

证书基础 self-test 为 7/7。真实运行环境为 Python 3.12.4、Torch 2.4.0、Kornia 0.8.3、CPU。

## 3. 真实重配置结果

pipeline 为 RandomHorizontalFlip、RandomAffine、ColorJiggle 的 AugmentationSequential。先在 source instance 采样参数，再重建配置等价的 target instance，验证 lineage certificate 和 child contracts 后应用原参数。

17/17 正确性与攻击测试通过：

- 重建 target 的输出 digest 与 source record 完全一致；
- replay 前后 Torch RNG state 不变；
- 两个 instance 的输入梯度 digest 完全一致；
- wrong sample、framework version、commit、operator config、child order、input shape 全部拒绝；
- 参数篡改、child 缺失、child 重排、重复 child、证书字段篡改全部拒绝；
- 未认证的 `torch.nn.Identity` child 以 `unsupported_child_effect` 拒绝；
- 三个已由 H7H calibration policy 接纳的 child 成功合成为 container admit。

这是第一个将“静态 phase certificate”连接到真实容器重建和运行时 trace 的原型结果，但不是新的 blind holdout；leaf policy 来自已完成的 H7H calibration。

## 4. 性能稳健性

15 个多 seed trial 的总体中位 replay speedup 为 1.074×，但只有 10/15 trial 更快：

| Profile | Median speedup | Faster trials | Certificate validation / replay |
|---|---:|---:|---:|
| B1×3×32×32 | 1.166× | 4/5 | 14.1% |
| B4×3×64×64 | 1.096× | 5/5 | 7.2% |
| B8×3×128×128 | 0.961× | 1/5 | 1.6% |

因此不能声称 replay 普遍加速。小/中输入中省掉 parameter sampling 有可见收益；大输入由 transform compute 主导，replay 的差异落入计时波动甚至略慢。证书验证的绝对成本较稳定，其相对比例随 workload 增大而下降。

## 5. Posthoc TOCTOU 反例

证书验证通过后，如果共享 parameter record 在 apply 前被修改，先前的 admit 会过期：

```text
validate(shared params) -> admit
mutate affine angle
apply(shared params)    -> output mismatch
```

再次验证会以 `parameter_record_mismatch` 拒绝，但无法挽回已经分离的 check/use。复制验证时的 immutable snapshot，再修改原记录并应用 snapshot，输出仍完全一致。

这将下一版的安全条件收紧为：

```text
certificate valid
AND validated parameter bytes == bytes consumed by apply
```

实现上需要 sealed immutable buffer、copy-on-seal，或把验证和 apply 放入同一原子边界。还需要处理跨线程共享、异步 device transfer 和 apply 内部是否会原地修改参数。

## 6. 当前判断与下一步

H7I 证明了 lineage certificate 与 child composition 的机制可行性，并把 H7H 的 container false reject 转化成了可接纳原型；同时主动发现了 TOCTOU 缺口。当前仍为 **non-blind mechanism PASS / runtime pilot PASS**，不能升级为独立泛化证据。

下一步 H7J 应优先实现：

1. sealed replay record 与 atomic validate-and-apply；
2. 从 V7 analyzer 输出自动生成 leaf proof，而不是手写 leaf policy；
3. 规范化 constructor/config IR，替代当前较脆弱的 `repr`-based operator digest；
4. 跨 CPU/GPU transfer 与并发 mutation 压力测试；
5. 再选择一个带显式 parameter record 的新框架做冻结 holdout。
