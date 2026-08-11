# H8B contract-carrying cache prefix 规范

日期：2026-07-29
状态：主线 mechanism pilot；使用 H5 历史性能结果，不能替代未来预注册重跑。

## 1. 候选定义

```text
uncached:
JPEG bytes -> decode -> GaussianBlur -> Resize -> stateless stochastic suffix

cached:
content-addressed prefix cache ---------> stateless stochastic suffix
```

候选是 `cache_prefix`，cache boundary 位于 deterministic prefix 与 epoch-varying suffix 之间。缓存 full pipeline 会冻结 augmentation diversity，因此不在支持范围内。

## 2. Semantic obligations

候选只有同时满足以下条件才可进入 cost optimizer：

1. prefix source closure 只包含已解析的 deterministic/pure operators；
2. prefix 不读取 RNG、epoch、worker state 或未绑定 external state；
3. prefix 保持 sample identity 和 one-to-one cardinality；
4. cache entry key 绑定 sample ID 与 dataset manifest；
5. dataset manifest 绑定每个 JPEG 的相对路径、label、大小和内容 SHA-256；
6. cache key 绑定 prefix source/config、Torch/Torchvision 版本与输出 schema；
7. cache artifact 绑定完整内容 digest，抽样重算与 prefix 输出逐字节一致；
8. suffix randomness 由 `(epoch, sample_id, stable_operator_id, draw_index)` 寻址，cache hit 不改变随机选择；
9. cache dtype/shape 与 consumer contract 一致；
10. 任一 binding 缺失或变化均 fail closed。

旧 H5 metadata 只有 `sample_count/shape/dtype/build_time/workers`，不满足 4–8，因此只能算同一次运行内的性能记录，不能作为可复用 cache certificate。

## 3. Cost decision

H5a profiler 为每个 worker profile 提供 uncached/cached steady samples/s 和 cache build time：

```text
saving_per_epoch = samples / uncached_rate - samples / cached_rate
cold_net(H) = H * saving_per_epoch - build_time
warm_net(H) = H * saving_per_epoch
select = semantic_admit AND net(H) > 0
```

H5a 只负责预测，H5b 的 ResNet-18 paired training runtime 作为独立 workload oracle。对于最小化 runtime 的 workload：

```text
benefit_coverage = (raw_runtime - AutoContract_runtime)
                 / (raw_runtime - human_oracle_runtime)
```

若 oracle 相对 raw 没有正收益，则该 workload 只计 decision correctness，不进入 benefit coverage。

## 4. Claim boundary

- H8B 可以支持 cache contract/interface、invalidation 负例和 retrospective H5 optimizer integration；
- 不把旧 H5 性能数据改写成预注册 H8B result；cache digest 当时没有记录，只能事后绑定当前 artifact；
- 当前机器没有 CUDA，H5b 不在本轮重跑；
- 一个 pipeline/一个 benefit-positive workload 不足以通过论文 RQ3；final benchmark 至少需要新的预注册 workload suite 与 human-oracle plan。
