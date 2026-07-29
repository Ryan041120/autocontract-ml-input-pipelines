# H7M Merkle batch、fenced lease 与 buffered release 复盘

日期：2026-07-29

## 1. 本轮结论

H7M 用一个 Ed25519-signed Merkle root 绑定 N 个 per-sample provenance leaf，并以 batch 为单位执行 `register -> claim -> apply(buffered) -> commit -> release`。lease 带单调递增 generation；coordinator recovery 后，旧 worker 即使恢复执行也不能 commit。相同 lease/generation/output digest 的重复 commit 幂等，用于 acknowledgement 丢失。

正式结论是：**mechanism/runtime PASS；batch size ≥4 时 performance PASS；N=1 no-go；非 blind；不等于 optimizer side effect exactly-once。**

## 2. 相关工作与研究边界

- [Flink fault tolerance](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault_tolerance/) 区分“事件被执行一次”和“事件对受管状态产生一次效果”，并指出端到端 exactly-once 需要 replayable source 与 transactional/idempotent sink；
- [Flink Sink API](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/sinks/) 通过 writer precommit 与 committer 协作外部 sink；
- [TorchData StatefulDataLoader](https://github.com/pytorch/data) 提供 mid-epoch `state_dict/load_state_dict` 与 worker 自定义状态保存；
- [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) 的 domain-separated Merkle tree 和 inclusion proof 支持以一个 signed root 绑定多个 leaf；
- Gray–Cheriton [Leases](https://www.cs.cmu.edu/afs/cs.cmu.edu/academic/class/15712-s12/www/papers/gray89.pdf) 提供 failure 下自动失效/恢复的经典 lease 思路。

H7M 不声称发明 Merkle tree、lease、two-phase commit 或 exactly-once。窄增量是把 batch attestation、fencing generation 和 buffered output release 与 EffectV7/H7K/H7L 的 ML augmentation replay proof 合成，并量化 batch size、事务、通信和内存之间的权衡。

## 3. 协议

### 3.1 Signed Merkle batch

每个 leaf 分别绑定自己的 H7L expectation，包括 sample/partner lineage、input digest 和 H7K registration；因此同一 batch 可以包含不同 parameter record。leaf hash 使用 `H(0x00 || leaf)`，内部节点使用 `H(0x01 || left || right)`。root statement 绑定 batch ID、tree size、Merkle root 和公共 run/dataset/epoch/sampler/operator context，并由 Ed25519 签名。

root signature 只需每 batch 验证一次；每 leaf 验证 inclusion proof。开发中发现并修复一个 cache-order bug：若先按自报 attestation ID 命中 cache，再检查 statement+signature digest，攻击者可能复用 cached ID。最终实现始终先重算 digest、检查 schema/key，之后才允许跳过 Ed25519 运算；对应 alias 攻击在真实 Kornia 测试中被拒绝。

### 3.2 Fenced state machine

```text
issued --claim--> leased(generation, lease_id, worker_id)
leased --commit(output_digest)--> committed
leased --recover/abort--> issued(generation+1)
```

所有 input snapshot、ticket、Merkle proof 与 policy 在 claim 前验证；错误批次保证 operator 零调用。claim 后 outputs 仅存于 executor；全部 H7K apply 和 postcheck 通过，再提交 output batch digest；commit 成功后才向 caller 释放整批 output。任何 apply 失败都会丢弃 outputs 并把 lease 退回新的 issued generation。

## 4. 正确性、安全与故障结果

- generic Merkle/root/registry：7/7；
- 真实 Kornia heterogeneous params batch：12/12；
- 独立进程 crash/ack-loss：6/6；
- Kornia MixUp ordered partner lineage：8/8（posthoc mechanism extension）。

Kornia batch=4 中，每个样本拥有不同 parameter certificate。输出、Torch RNG 和输入梯度均与逐条 replay 一致；wrong input、ticket reorder、proof tamper 和 cached-attestation alias 全部在 operator 前拒绝。四个 caller 竞争同一 batch 时恰好一个成功，operator invocation 增量为 4 而不是 16。算子在 batch 中途修改 working params 时，H7K 拒绝，registry 回到 `issued` generation 2，caller 得不到部分 output。

真实子进程在 claim 后以退出码 17 终止，registry 保持 leased；coordinator recover 后 replacement generation 成功提交，stale generation 被拒绝。另一子进程在 commit 后、ack 前以退出码 23 终止；相同 output digest 重试幂等成功，不同 digest 以 `committed_batch_conflict` 拒绝。

## 5. MixUp 多样本 lineage

冻结 Kornia 0.8.3 中 `RandomMixUpV2` 的 replay params 包含 `mixup_pairs` 和 `mixup_lambdas`。冻结 EffectV7 对该 leaf 的 posthoc analysis 为 admit，并绑定 source/binding/EffectV7/adapter hashes。记录的正式 pilot 配对为 `[1,0,3,2]`；subjects 按输出槽编码为：

```text
primary[0]=0, partner[0]=1,
primary[1]=1, partner[1]=0,
primary[2]=2, partner[2]=3,
primary[3]=3, partner[3]=2
```

8/8 测试中，输出/RNG/梯度一致，wrong partner mapping 和 input batch reorder 均零调用拒绝，外部修改原始 `mixup_pairs` 被 H7K private snapshot 隔离。`RandomMixUpV2` 不在正式 H7H symbol set，因此这是冻结分析器的 posthoc mechanism extension，不是新的 blind PASS。

## 6. 摊销性能

H7L 每样本签名、注册、消费；H7M 每 batch 签一个 root，并各执行一次 register、claim、commit。每个 N 独立运行 10 轮。

| N | H7L issue/sample | H7M issue/sample | H7L consume/sample | H7M consume/sample | H7M/H7L consumer | H7L bytes/sample | H7M bytes/sample |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3.695 ms | 3.668 ms | 3.657 ms | 7.068 ms | 1.911× | 1021 | 1297 |
| 4 | 3.749 ms | 0.970 ms | 3.838 ms | 1.852 ms | 0.488× | 1021 | 1072 |
| 16 | 3.971 ms | 0.299 ms | 4.171 ms | 0.564 ms | 0.138× | 1022 | 1156 |
| 64 | 4.088 ms | 0.116 ms | 4.217 ms | 0.217 ms | 0.053× | 1023 | 1317 |

N=1 因 consumer 端需要 claim+commit 两次 durable transition，明确比 H7L 差。N=4 开始摊销获益，之后固定事务成本快速下降。代价是 Merkle inclusion proof 使每样本 wire bytes 随 `log N` 增长；N=64 时约 1.3 KB，高于 H7L 的约 1.0 KB。

## 7. 真实 Kornia 端到端性能

batch=4，10 个随机交错 round，每 round 对 H7K、H7L、H7M 各取 10 次 batch 调用中位数。issuer signing/registration 均预计算，不进入 consumer path。

- H7K：31.216 ms；
- H7L：48.321 ms，H7L/H7K=1.538×；
- H7M：41.070 ms，H7M/H7K=1.285×；
- H7M/H7L=0.835×，H7M 10/10 round 更快。

因此 H7M 把该 workload 的 H7L consumer latency 降低约 16.5%，但相对 H7K 仍有约 28.5% 的 batch authorization/commit 开销。buffered release 的最低 tensor 内存为 196,608 input snapshot bytes + 196,608 output bytes，尚未计 framework intermediate、params copy 和 Python object 开销。

## 8. 不能声称的内容

- H7M commit 证明一个 batch authorization/output digest 被 registry 接纳，不证明 optimizer step 已产生一次效果；
- commit 后、delivery 前 crash 仍可能丢 batch；delivery 已到 trainer 但 ack 丢失仍可能导致重复 optimizer step；
- 真正端到端 exactly-once 需要 durable output、trainer batch-ID idempotency，或 DataLoader/model/optimizer 的一致 checkpoint；
- coordinator recover 是显式可信操作；自动 timeout recovery 必须依赖 generation fencing，但仍需解决已提交外部副作用；
- 当前 SQLite 是单机 durable baseline，不覆盖 registry rollback、replication/consensus 或 Byzantine coordinator；
- batch buffering 增加 latency 和 memory；N=1 明确不应使用 H7M；
- Merkle proof 节省签名/事务，不节省 input content hashing；
- 除 MixUp posthoc extension 外，本轮依赖正式 H7H/H7K Kornia policy，不是新 blind framework evaluation。

## 9. 下一步：H7N checkpoint-coupled trainer commit

下一阶段应把安全边界从 DataLoader output 推进到训练状态：

```text
batch provenance commit
+ DataLoader position/worker RNG state
+ model state
+ optimizer state
+ batch-id effect journal
```

需要分别注入 crash-before-step、crash-during-step、step-after-journal-before-ack 和 checkpoint torn-write，比较三种方案：每 batch write-ahead checkpoint、周期 checkpoint+replay、trainer idempotency journal。H7N 的核心问题是：**在可接受的 checkpoint/日志开销下，能否使恢复后的 model/optimizer digest 等价于无故障执行，并让每个 committed provenance batch 对训练状态恰好产生一次逻辑效果？**
