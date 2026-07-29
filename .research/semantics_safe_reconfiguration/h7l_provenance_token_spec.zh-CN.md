# H7L worker-portable provenance token 预注册设计

日期：2026-07-29

## 1. 研究缺口

H7K 已绑定 replay parameter snapshot、operator graph、EffectV7 leaf proofs 和动态 input schema，但 `sample_id` 仍由 caller 以字符串声明。错误或恶意 caller 可以把属于 sample A/epoch 0 的参数记录声称为 sample B/epoch 1；如果 shape/dtype 相同，H7K 本身无法识别。

现有相关工作覆盖三个邻近层次：

- [TensorFlow ML Metadata](https://www.tensorflow.org/tfx/guide/mlmd) 记录 artifact、execution、event 与 context 的 pipeline-level lineage；
- [Smoke](https://arxiv.org/abs/1801.07237) 和 [fine-grained data-science provenance](https://arxiv.org/abs/2310.18079) 捕获 record/element 级输入输出依赖，重点是 lineage query 与解释；
- [in-toto Attestation Framework](https://github.com/in-toto/attestation/blob/main/spec/README.md) 将 subject、predicate、statement 与 authenticated envelope 分层，重点是可验证供应链声明；
- [Hopsworks time-travel provenance](https://www.usenix.org/conference/opml20/presentation/ormenisan) 绑定 code/data/environment version，支持 pipeline reproducibility。

H7L 的窄增量是：把 authenticated attestation 结构下沉到 ML input pipeline 的单次 replay invocation，并把它与 H7K 的语义证书、安全执行边界及 exactly-once registry 合成。

## 2. 候选设计与选择

| 方案 | 能检测字段篡改 | worker 能否伪造 | 能否检测重复消费 | 结论 |
|---|---:|---:|---:|---|
| 普通 SHA-256 token | 是 | 能 | 否 | 仅 checksum，不足 |
| HMAC token | 是 | 持验证密钥的 worker 能 | 可另加 registry | 不适合 verifier-only worker |
| Ed25519 + 无状态验证 | 是 | 不能签发 | 否 | 不能阻止 stale/duplicate reuse |
| Ed25519 + 原子 registry | 是 | 不能签发 | 是 | H7L 选择 |

私钥只留在可信 issuer；worker/executor 只获得公钥。registry 使用 token digest 作为主键并执行原子 `issued -> consumed` 转移。失败后的 retry 必须由 issuer 签发具有新 nonce 的 token，避免把“可能已经执行过”的 token 重新开放。

## 3. Token schema

```text
ProvenancePayloadV1 = {
  key_id,
  run_id,
  replay_sample_id,
  dataset_id,
  dataset_revision,
  split,
  dataset_manifest_sha256,
  epoch,
  sampler_context_sha256,
  subjects: ordered[(role, sample_key, content_sha256)],
  operator_path,
  registration_sha256,
  input_content_sha256,
  nonce
}
```

`subjects` 是有序列表，因此 primary/partner 的角色、数量和顺序都被签名。`registration_sha256` 间接绑定 H7K certificate、params digest、operator graph、leaf proofs、child composition、pool size 和 receipt level。`input_content_sha256` 补上 H7K 只检查 schema、不检查内容的缺口。

签名对象采用确定性 canonical JSON；token ID 为 payload bytes 与 signature 的联合 SHA-256。该原型借鉴 in-toto 的 statement/envelope 分离思想，但不是兼容 in-toto predicate 的实现。

## 4. 威胁模型

覆盖：

- caller 篡改或错配 sample、epoch、dataset revision、partner、operator、registration 或 input content；
- token 序列化后跨 `spawn` worker 传输；
- 多 worker 同时提交同一个 token；
- token 被撤销、未知 issuer key 或 signature 被修改；
- 普通 checksum 被攻击者重算。

不覆盖：

- issuer 私钥泄露；
- verifier/executor 进程本身被完全控制并绕过验证代码；
- registry rollback、磁盘/OS 被恶意管理员控制；
- 隐私保护：sample key 和 digest 仍可能形成可关联元数据；
- 内容 digest 到真实磁盘对象之间的可信测量，当前由 dataset manifest 构建过程承担。

## 5. 可证伪假设与验收门槛

**H7L：** signed provenance token 与原子 replay registry 能在跨 worker 传输后，把 H7K 的 replay 调用绑定到正确 dataset revision、epoch、ordered subjects、input content 与 parameter registration，同时使所有前置错配在 operator invocation 前拒绝。

验收门槛：

1. generic token/registry 自检全部通过，包括 checksum-forgery、signature tamper、revoke 和 duplicate race；
2. 真实 Kornia 正确 token 的输出/RNG/梯度保持 H7K 一致；
3. 至少 10 类 provenance 错配全部拒绝，并证明 operator invocation 增量为 0；
4. 4 个 `spawn` worker 使用各自 token 均成功；4 worker 竞争同一个 token 时恰好 1 个成功；
5. 单独报告 issuance、signature verification、registry consume 与端到端开销；
6. 不把本轮写成新的 framework blind holdout。
