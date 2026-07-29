# H7L signed provenance token 与 replay registry 复盘

日期：2026-07-29

## 1. 本轮结论

H7L 将 H7K 中由 caller 自行声明的 `sample_id` 替换为 Ed25519 签名的调用级 provenance token，并用跨进程 SQLite registry 原子执行 `issued -> consumed`。在当前 Kornia replay pilot 中，dataset revision、epoch、sampler context、ordered subjects、operator path、H7K registration 和实际输入内容均进入签名声明；输入先 clone，再对被实际消费的 clone 求 digest，避免重演 params TOCTOU。

结论是 **mechanism/runtime PASS，非 blind**：generic 7/7、真实 Kornia 21/21、Windows spawn 5/5。代价是相对 H7K minimal 的总体中位调用时间增加 23.5%，其中 durable registry transaction 是主要固定成本，大输入的 seal+digest 是第二个增长项。

## 2. 与相关工作的边界

- [ML Metadata](https://www.tensorflow.org/tfx/guide/mlmd) 用 artifact、execution、event 和 context 表达 pipeline-level lineage；
- [Hopsworks time-travel provenance](https://www.usenix.org/conference/opml20/presentation/ormenisan) 绑定 code/data/environment version，服务于 pipeline reproducibility；
- [Smoke](https://arxiv.org/abs/1801.07237) 以及 [fine-grained data-science provenance](https://arxiv.org/abs/2310.18079) 捕获 record/element 输入输出依赖，服务 lineage query、解释和调试；
- [in-toto Attestation Framework](https://github.com/in-toto/attestation/blob/main/spec/README.md) 将 subject、predicate、statement 和 authenticated envelope 分层，服务可验证供应链声明。

H7L 不声称发明 provenance、数字签名或 exactly-once registry。窄增量是把 authenticated per-invocation provenance 与 EffectV7 replay proof、H7K registered executor 和 `validated bytes == consumed bytes` 边界合成，并测量其在 ML input replay 热路径上的安全与成本。

## 3. Token 与执行边界

签名 token 绑定：

```text
run + dataset revision + split + manifest
+ epoch + sampler context
+ ordered[(role, sample key, content digest)]
+ operator path + H7K registration digest
+ input content digest + random nonce
```

H7K registration digest 又绑定 certificate、params digest、operator graph、leaf proofs、child composition、pool size 与 receipt level。worker 只取得公钥；issuer 私钥不发送给 worker。

执行路径为：

```text
clone input
-> hash consumed clone
-> verify Ed25519 signature and semantic claims
-> atomic registry consume
-> H7K sample/schema/copy/lease/apply/postcheck
-> release output
```

token 在 H7K apply 前消费。apply 失败时必须签发新 nonce 的 retry token；旧 token 不重新开放。

## 4. 安全与正确性结果

### Generic token/registry

7/7：JSON 往返、duplicate、claim mismatch 不误消费、攻击者重算普通 checksum 仍无法伪造签名、revocation、unknown key，以及四线程抢同一 token 恰好一个成功。

### 真实 Kornia

21/21：

- 正确 token 的输出、RNG 和输入梯度与 H7K/direct replay 一致；
- token 与 H7K registration receipt 绑定；
- duplicate、wrong run/sample/dataset revision/manifest/epoch/sampler/subjects/operator/registration/input claim、实际 input bytes 篡改、revoked token、unknown key、signature tamper 全部在 operator invocation 前拒绝；
- 外部线程持续修改输入的 50 次压力尝试中，最终复跑得到 26 次一致快照安全成功、24 次前置拒绝、0 次错误输出释放；所有成功输出 digest 相同，Torch RNG 不变。

### Windows spawn

4 个 `spawn` worker 分别消费 4 个 token 时 4/4 成功；4 worker 竞争同一 token 时严格为 1 成功、3 个 `token_consumed`。私钥未传给 worker，所有 registry state 与进程返回一致，5/5 gate 通过。

## 5. 性能结果

三个 profile 各 10 个随机交错 round，每个 round 对 H7K minimal 与 H7L consumer path 各取 10 次调用中位数。token issuance 预先完成，不计入 consumer path，但单独报告。

| Profile | H7L/H7K | 范围 | 中位绝对开销 | H7L 更快轮数 |
|---|---:|---:|---:|---:|
| B1×3×32×32 | 1.384× | 1.301–1.556× | 3.655 ms | 0/10 |
| B4×3×64×64 | 1.127× | 0.879–1.307× | 1.974 ms | 3/10 |
| B8×3×128×128 | 1.092× | 1.025–1.269× | 5.131 ms | 0/10 |

总体中位 H7L/H7K 为 1.235×，H7L 仅在受噪声影响的 3/30 round 更快。因此可信 provenance 不是免费功能。

| Profile | Issue+register | Verify claims | Registry consume | Seal input+digest |
|---|---:|---:|---:|---:|
| B1×3×32×32 | 3.909 ms | 0.324 ms | 3.549 ms | 0.036 ms |
| B4×3×64×64 | 3.980 ms | 0.357 ms | 3.477 ms | 0.219 ms |
| B8×3×128×128 | 4.083 ms | 0.374 ms | 3.749 ms | 2.325 ms |

Ed25519 验签不是主瓶颈；每 token durable registry transaction 是主要固定成本，input sealing/content hashing 随输入大小增长。

持久连接优化前，错误的逐调用开关连接实现使 H7L/H7K 达到约 2.3×，registry 操作约 21–23 ms。修复后降到上述结果。该旧数字不得作为机制结论。

工作区 OneDrive 与本机临时目录的 10 轮随机存储消融得到：workspace issue/consume 为 5.265/4.588 ms，local 为 4.846/4.279 ms，consume 比值 1.072×。不同运行的绝对数有 OS/filesystem 噪声，但 OneDrive 只解释小部分开销，不能把 transaction 成本完全归因于同步盘。

## 6. 不能声称的内容

- 本轮依赖 H7H/H7K 已冻结 Kornia policy，不是新的 framework blind holdout；
- 当前真实 pipeline 是 unary augmentation；`subjects` 的 partner 顺序已进入 schema 和拒绝测试，但尚未在真实 MixUp/Mosaic 等多样本 runtime 中验证；
- registry 保证 token consumption 恰好一次，不保证训练副作用端到端 exactly once。token 消费后、optimizer step 或输出提交前 crash 会造成“已消费但未生效”；
- 如果用 timeout 把 lease 重新开放，又可能在 worker 已执行但 acknowledgement 丢失时造成重复训练副作用；
- issuer key storage/rotation、registry rollback protection、远程 worker 身份、manifest 构建可信度和 metadata privacy 尚未实现；
- verifier/executor 进程完全被控制、私钥泄露、OS/native memory compromise 不在威胁模型内；
- SQLite 是 durable baseline，不是最优 registry 架构。

## 7. 下一步：H7M amortized crash-aware provenance

下一阶段应同时处理性能与 crash window，而不是简单关闭 durability：

1. 每个 batch/epoch 签一个 Merkle root，单样本携带短 Merkle proof，摊销签名与 token metadata；
2. registry 一次原子分配一段 nonce/sequence lease 给 worker，摊销 commit；
3. 明确 `issued -> leased -> applied -> committed` 状态机和 crash recovery；
4. 将 content digest 融合进 decode/read，而不是对 tensor 额外扫描一遍；
5. 在真实 partner-sampling transform 中验证 ordered multi-sample lineage；
6. 分别评估 at-most-once、at-least-once 和 idempotent downstream commit 的语义/性能边界。

H7M 的核心科学问题是：**能否在不重新打开 duplicate/misbinding 风险的前提下，把 per-sample durable provenance 的固定事务成本按 batch 或 worker lease 摊销？**
