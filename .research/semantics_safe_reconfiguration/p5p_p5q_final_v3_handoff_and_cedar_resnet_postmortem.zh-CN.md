# P5P–P5Q：final-v3 正式交接工具与 cedar→ResNet18 workload harness

日期：2026-08-01
P5P：25/25 PASS，结果 SHA-256 `a100a54395fc1281a817003603c6cd3d4c01770e7413b1ac828a9372e0e8a4a8`
P5Q：19/19 PASS，结果 SHA-256 `8b77cd9fdfbd569a26bc72fb29045b017889b742febcef7eea88599471d645b2`

## 1. P5P 做了什么

P5O 只证明 final-v3 schema、guard 和污染 dry-run 能工作；P5P 将其补成可交给独立人员的行政链：

1. `validate-public`：检查 label leakage、framework/pair/family quota、contamination、premise profile、native policy 和 analyzer artifact；
2. `validate-private`：检查 primary/reviewer/adjudicator、三分类标签、四类 observation 和 counterexample mismatch dimension；
3. `validate-prediction`：检查 domain guard、native decision、receipt、observational relation 和 prospective burden；
4. `commit-oracle`：以 v1 domain separator 绑定 salted private oracle；
5. `freeze-public`：冻结 public manifest、oracle commitment、analyzer artifacts 和 reporting plan，不写入 private path/content；
6. `seal-prediction`：在 reveal 前冻结 prediction；
7. `reveal-score`：先报告 unsafe/unresolved Supported，再报告 completion、family/RNG Wilson interval、non-identity Supported、supported frameworks 和 burden。

普通 validate/commit/freeze/seal/reveal 路径只依赖 Python + `jsonschema`，不加载 torch；只有内部 self-test 为复用 P5O 的 8-pair fixture 才加载固定 PyTorch runtime。`requirements.txt` 已补 `jsonschema==4.26.0`。

## 2. P5P 自测与攻击结果

P5P byte-freeze P5O runner/result、final-v3 三套 schema、worksheet 和 canonical admin。8-pair fixture 继续标记 contaminated、`scientific_evidence=false`。25 项检查全部通过，包括：

- commitment/seal 后 oracle/prediction 篡改拒绝；
- 8-pair fixture 不能把 mode 改成 `independent_final`；
- public answer-bearing key 拒绝；
- Commutes 存在 unresolved observation、Noncommutes 没有 violated dimension 均拒绝；
- opaque native Supported、runtime premise violation Supported 拒绝；
- missing/reordered predictions、burden arithmetic drift、analyzer artifact drift 拒绝；
- reveal 保持 safety-first，并产出 family/RNG/Wilson 与 burden。

这完成的是 final-v3 administrative readiness。只有真实 20–40 pair、至少三框架/两领域/四 family、独立 selector/annotators、无污染且 reporting plan 在 selection 前冻结，`scientific_evidence_eligible` 才可能为 true。

## 3. P5Q workload 设计

P5Q 不读取任何未来 private oracle，而是在已污染的 P5M torchvision chain 上校准 prediction-seal 后的 workload 测量：

- real cedar commit `f062305fcdab196e871c5d09b4c82ab788b4da79`；
- Python 3.11.9、torch 2.0.1+cpu、torchvision 0.15.2+cpu、单线程；
- 24 个 synthetic probe images；
- pipeline：Normalize → RandomCrop(23×25) → Identity；
- baseline：无 receipt、全 fix、不开 optimizer；
- guarded：三张 V2 pair receipt 全部本地重放，cedar 自己从六个 candidate 选 plan；
- 下游：ResNet18、10 类、SGD、batch 8、三个 training steps；
- semantic endpoints：tensor、definedness、RNG、loss、logit、gradient、model state；
- performance：一次预热，preprocessing 三次；training 三次并交替 AB/BA 顺序；只报告中位数/P95，不设 5% gate。

## 4. P5Q 语义结果

Fail-closed 只有一个 candidate，path 为 `[3,2,1,0]`；三张 receipt 恢复六个 candidate，cedar 选择 `[3,0,1,2]`。两个 arm 内部重复稳定。

24/24 preprocessing outputs 逐 tensor 相等，shape 相同，Python/NumPy/torch RNG post-state 相同。进入 ResNet18 后：三步 loss 的 hex 表示完全一致，logits digest、最后一步 gradients digest 和最终 model state digest 全部一致。因此 current workload harness 已把 pair-level observation 贯通到下游训练语义，而不是只比较 JSON 或单个 tensor delta。

这仍不是形式证明：三个 torchvision operator 均被 P5O 分类为 `known_versioned_native`，只绑定固定 runtime identity 和 Python dispatch/source tree，不是 native binary/kernel/hardware attestation。

## 5. P5Q 性能结果与负结论

预热后的三次 preprocessing：

| Arm | 时间（ms，排序后） | Median | Throughput |
|---|---:|---:|---:|
| fail-closed | 4.636, 6.214, 8.245 | 6.214 ms | 约 3862 samples/s |
| receipt-guarded cedar | 5.426, 6.569, 7.284 | 6.569 ms | 约 3653 samples/s |

guarded/baseline preprocessing ratio 为 **1.057×**，即 guarded 在这个小 workload 上约慢 5.7%。cedar planning median 约 4.474 ms。

交替顺序的 ResNet18 training median 为 baseline 732.647 ms、guarded 707.164 ms；由此算出的 warm/cold end-to-end ratio 表面为 0.966×/0.972×。但两臂的输入、模型初始化、loss、logit、gradient 和 model state 完全相同，所以这 3% 差异只能解释为 CPU timing noise，不能归因于 plan。首轮未预热单次运行曾表面显示约 22% end-to-end 改善，已被更严格的预热/交替复跑否定，没有保留为结论。

因此 P5Q 的诚实结论是：**真实 cedar 重排可贯通保持训练语义，但当前小型污染 workload 没有证明可重复的性能收益。** 这正是 full-paper blocker 仍未解除的原因。

## 6. 下一步决策

不应根据本轮结果事后挑一个更容易加速的 crop/normalize 尺寸并把它叫 final。下一步必须在未来独立 manifest seal 后，从真实 workload/task 选择固定输入尺寸、算子 cost profile、模型和样本规模；先冻结 workload，再运行 receipt-guarded/no-constraint/manual baselines。Benefit 与 safety 分表，任何 semantic mismatch 一票否决；无 benefit 则如实收缩为 audit gate/negative systems result。

在等待外部 selector 时，内部只可完善 workload execution manifest、trace schema 和一键运行说明，不再调当前 P5Q workload 来追求正向数字。
