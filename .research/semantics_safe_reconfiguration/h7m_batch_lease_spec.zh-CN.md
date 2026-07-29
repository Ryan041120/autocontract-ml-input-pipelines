# H7M amortized crash-aware provenance 预注册设计

日期：2026-07-29

## 1. 问题

H7L 对每个 replay invocation 分别签名、注册和原子消费。正确性已通过，但 H7L/H7K 总体中位为 1.235×，单 token durable consume 约 3.5–3.7 ms。另一方面，H7L 的 `consumed` 只说明 token 已被 registry 接受，并不说明 augmentation output、batch delivery 或 optimizer state 已经产生一次效果。

相关系统给出三条边界：

- [Flink fault tolerance](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault_tolerance/) 明确指出 exactly-once operator state 不等于每条记录只执行一次；端到端 exactly-once 需要 replayable source 和 transactional/idempotent sink；
- [Flink Sink API](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/sinks/) 用 precommit/committer 两阶段协作外部 sink；
- [TorchData StatefulDataLoader](https://github.com/pytorch/data) 能保存 mid-epoch DataLoader 与 worker 自定义状态，但不自动提供 augmentation provenance 或 optimizer 副作用原子性；
- [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html) 的 domain-separated Merkle tree 证明一个 leaf 属于签名 root，可把 N 次签名摊销成一次 root 签名加 O(log N) inclusion proof。

## 2. 候选协议

| 协议 | Registry transactions | Duplicate safety | Crash 行为 | 结论 |
|---|---:|---|---|---|
| per-token consume | N | 强 | consume 后 crash 丢工作 | H7L baseline |
| range 预消费后逐条释放 | 1 | worker crash/restart 后依赖本地 bitmap | 未处理项丢失，已处理项可能难区分 | 拒绝 |
| timeout lease 后逐条释放 | 2/batch | stale worker 可能晚到 | timeout 重开会重复释放 | 拒绝 |
| fenced lease + batch buffered release | 3/batch（register/claim/commit） | stale generation 不能 commit | commit 前可恢复；commit 后 delivery 仍需幂等 sink | H7M 选择 |

## 3. Batch attestation

每个 leaf 包含 H7L `ProvenanceExpectation`、batch 内 index 和随机 nonce。leaf 使用 `H(0x00 || canonical_leaf)`，内部节点使用 `H(0x01 || left || right)`，不足 2 的幂时用固定 empty leaf 填充；signed root statement 绑定：

```text
schema + key_id + batch_id + tree_size + merkle_root
+ run/dataset/epoch/sampler/operator batch context
```

每个 leaf 分别绑定自己的 H7K registration digest，因此同一 batch 可以包含不同样本、不同 parameter record；Merkle root 整体绑定这些 leaf。每个 ticket 携带 leaf、index、inclusion path 与同一 signed root。worker 可缓存一次 root signature 验证，但每个 leaf 仍验证 inclusion proof、实际 input content 和调用 policy。

## 4. Registry 状态机

```text
issued --claim--> leased(generation, lease_id, worker_id)
leased --commit(output_digest)--> committed
leased --coordinator_recover--> issued(generation+1)
issued/leased --revoke--> revoked
```

- claim 是原子事务，同一 batch 同时只能有一个 current lease；
- recover 必须匹配原 lease 与 generation，并递增 fencing generation；
- stale worker 的 commit 因 generation/lease mismatch 拒绝；
- 相同 lease、generation 和 output digest 的重复 commit 幂等成功，用于 acknowledgement 丢失；
- 不同 output digest 的重复 commit 拒绝；
- outputs 在 commit 成功前只保存在 executor 内部，不对 caller 释放。

## 5. 威胁模型和不能解决的窗口

覆盖 ticket/leaf/root 篡改、ticket reorder、wrong input、重复 batch、并发 claim、worker 在 commit 前 crash、recover 后 stale commit、commit acknowledgement 丢失。

不覆盖 issuer key/registry/OS 被控制。更重要的是：若 worker 在 registry commit 后、把 output 交给 trainer 前 crash，registry 只有 output digest、没有 output bytes；若 output 已到 trainer 但 acknowledgement 丢失，单靠 registry 也不知道 optimizer step 是否发生。真正端到端 exactly-once 仍需要：

1. durable output buffer；或
2. trainer 按 batch ID 幂等提交；或
3. DataLoader position、model/optimizer state 和 batch commit 的一致 checkpoint。

因此 H7M 只声称 **exactly-once batch authorization/commit 与 stale-worker fencing**，不声称 optimizer side effect exactly-once。

## 6. 可证伪假设与门槛

**H7M：** 对大小 N 的 replay batch，只签名一个 Merkle root，并使用 fenced batch lease 与 buffered release，可以在保持 H7L misbinding/duplicate 安全端点的同时，将 registry/signature 固定成本按 N 摊销。

门槛：

1. Merkle/root/registry generic tests 全部通过；
2. wrong proof/root/index/reorder/input 在 operator 前拒绝；
3. 4 个 caller 竞争一个 batch，恰好 1 个 claim 并只产生 N 次 operator invocation；
4. 实际 crash 后 coordinator recovery 成功，旧 generation commit 拒绝；
5. acknowledgement 丢失后的相同 commit 幂等，不同 digest 拒绝；
6. 真实 Kornia batch 输出/RNG/梯度与逐条 H7K 一致；
7. batch size 1/4/16/64 的每样本认证+registry 成本随 N 下降；N≥4 时优于 H7L per-token baseline；
8. 单独报告额外 proof bytes、batch latency 和 buffered memory；
9. 本轮是 mechanism/runtime study，不是 framework blind holdout。
