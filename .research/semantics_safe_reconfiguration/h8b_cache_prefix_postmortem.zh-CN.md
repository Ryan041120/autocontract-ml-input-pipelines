# H8B contract-carrying cache prefix 复盘

日期：2026-07-29

## 1. 结果

H8B 将 H5 的真实 JPEG/DataLoader/ResNet 路径接入统一 optimizer boundary，并补上旧实验缺失的 cache invalidation contract。

- prefix source analysis 解析出 `F.gaussian_blur` 与 `F.resize`，两者位于冻结的 deterministic/pure registry；
- prefix 无 RNG、external read、state write，cardinality 为 one-to-one，sample identity 保持；
- suffix RNG 地址冻结为 `(base_seed, epoch, sample_id, stable_operator_id, draw_index)`；
- dataset manifest 绑定 600 个 JPEG 的 sample ID、相对路径、label、大小和内容 SHA-256；
- cache artifact 绑定 17,971,200 bytes 的完整 SHA-256；
- 24 个分散 sample 的 cache entry 与从 JPEG 重算的 prefix 逐字节一致；
- dataset/prefix/suffix/cache/schema/entry-key 六种 drift 均 fail closed；
- 14/14 mechanism checks 通过。

新 cache contract digest：

```text
f545cdbe367fc96307b8f5e561b7bf3e2ce1b4e324974e273e1435c352c30338
```

## 2. 发现的 soundness 缺口

旧 H5 sidecar 只有 sample count、shape、dtype、build time 和 worker count。它缺少八类安全绑定：

- dataset manifest；
- prefix contract；
- suffix RNG contract；
- cache content；
- entry key；
- Torch version；
- Torchvision version；
- proof digest。

因此旧实验的 `trace_match=1.0` 只能说明当前 paired run 一致，不能证明未来数据、代码或依赖变化后仍能安全复用 cache。这给论文提供了一个很清楚的反例：**dynamic equivalence testing 不能替代 cache-key/invalidation contract。**

## 3. H5b optimizer decision

H5a workers=2 profile 预测每 epoch 节省 1.106 s。对 H5b 的 4-epoch horizon：

| 状态 | 预测净收益 | AutoContract | 实测 oracle | 实测结果 |
|---|---:|---|---|---|
| cold cache | -7.084 s | NO CACHE | NO CACHE | build+cached=25.113 s > raw=18.794 s |
| warm cache | +4.422 s | CACHE | CACHE | cached=13.608 s < raw=18.794 s |

H5a profile 没有使用 H5b runtime 作为 optimizer score，但正确预测两种选择。Warm workload 的 AutoContract runtime 与 human-oracle runtime 相同，因此该单元 benefit coverage=100%。Cold workload 的 oracle 没有正收益，只计 decision correctness，不进入 coverage。

## 4. 不能过度解释的部分

- benefit-positive training workload 只有 1 个，100% 不能作为论文 RQ3 headline；
- H5 cache 内容 digest 是 H8B 事后记录，历史 H5b 执行前没有 sealed proof；
- 当前环境没有 CUDA，未能在本轮用新 contract 重跑训练；
- 数据来自 7 张图片的 600 个确定性 crop，只是 systems workload；
- trusted functional registry 仍是小型人工校准边界，不是任意 Torchvision source inference。

## 5. 主线下一步

下一工作包应是预注册的 multi-workload cache benchmark：

1. 在 profiling 和运行前写入并冻结 cache contract；
2. 至少包含 CV 与另一数据域；
3. 包含 safe prefix、RNG-consuming deterministic-looking prefix、external-state prefix、full-cache diversity 四类边界；
4. 同一候选集运行 fail-closed、manual hint、static-only、dynamic-only、hybrid 与 human oracle；
5. 对每个 benefit-positive workload 计算真实性能 benefit coverage。

在这个 benchmark 完成前，不再扩展 H7L/H7M/H7N 一类分布式协议。
