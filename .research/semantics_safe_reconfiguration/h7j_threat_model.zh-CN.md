# H7J sealed atomic replay：威胁模型与成功判据

日期：2026-07-29

## 威胁模型

H7J 处理的是非恶意或半可信同进程环境中的 stale/mutable replay record，而不是抵御能够任意反射、patch Python 对象或伪造摘要的恶意代码。

允许的攻击/故障包括：

- seal 后继续持有并修改原始 params；
- 其他线程在 validate 与 apply 之间持续修改原始 params；
- 调用者在一次 apply 后修改 operator 暴露的 `_params`；
- target operator 配置、版本、commit、输入 schema 或 sample identity 不匹配；
- child 缺失、重排、重复或缺少 EffectV7 replay proof；
- operator 在 apply 内原地修改收到的 working params。

不覆盖：

- 直接通过 Python reflection 访问并修改 sealed object 私有字段；
- monkey patch digest/validator/operator implementation；
- 恶意进程内存修改；
- 未隔离的 C++/CUDA kernel 越界写。

## 原子边界

```text
seal:
  deepcopy(original params) -> private snapshot -> lineage certificate

atomic apply (one lock scope):
  deepcopy(private snapshot) -> working record
  -> validate lineage against working record
  -> compose child EffectV7 proofs
  -> call operator(params=working record)
  -> re-hash working record
  -> release output only if post-use digest still matches
```

私有 snapshot 永不直接传给 operator；每次调用使用新的 working copy。锁覆盖验证、child composition、apply 和 post-use check，以序列化共享 target operator 的 `_params` / transform state。

## 成功判据

1. 原始 params 在 seal 后发生串行或并发突变，所有 atomic replay 输出仍与 seal 时记录一致。
2. 同一个 sealed record 在共享 target 上并发调用至少 100 次，输出、RNG state 和 receipt 均一致。
3. 错 sample/version/commit/operator/schema 与 child proof 失败时，operator call count 为 0。
4. operator 若原地修改 working params，post-use check 必须拒绝且不返回输出。
5. 每次成功调用产生 receipt，绑定 certificate、pre/post parameter digest、child proof digest 和 output digest。
6. leaf policy 不再手写；由冻结 H7H EffectV7/adapter 对 target child 的 `params_provided/replay_apply` 分析自动生成。
