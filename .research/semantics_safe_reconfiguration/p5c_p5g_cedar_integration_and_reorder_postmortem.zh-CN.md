# P5C–P5G cedar 集成、反例与 ReorderCapability 复盘

## 一句话结论

AutoContract 已经从 synthetic JSON mapping 推进到固定 cedar 提交的真实 import、对象构造、数据路径和 optimizer plan consumption；同时真实执行发现 P5A 把“effect-safe/pure”误当成“可交换”的安全漏洞。P5G 通过独立、source-bound 的 ReorderCapabilityV0 fail-closed 修复该反例，但 capability receipt 仍是人工/外部提供，尚无真实算子自动推断或独立 final 证据。

## P5C：真实 runtime/API smoke

隔离环境固定为 Python 3.11.9、PyTorch 2.0.1+cpu、TensorFlow 2.14.0、Ray 2.7.0、NumPy 1.26.0、torchvision 0.15.2+cpu 和 torchdata 0.6.1。环境解析为 70 个 distribution records，占约 2.38 GiB；这说明 cedar 的最小 in-process 接入仍有显著环境负担。

安装/运行阶段保留了三类失败：主环境缺 TensorFlow/Ray/torchdata；Ray 2.7.0 与 setuptools 83 的 `pkg_resources` 不兼容，需固定 setuptools 70.3.0；cedar 顶层导入还隐式需要 PIL、Pympler、torchvision/torchdata。未修改 cedar 源码。

P5C attempt 0 为 13/14 FAIL：Windows `core.autocrlf=true` 让工作树文件为 CRLF，而 Git blob 是 LF。v1 改成同时验证 Git object 原始 SHA、干净工作树和 CRLF→LF 规范化等价。attempt 1 又因差量 protocol 未合并 v0 fixture，在 cedar 执行前行政失败。v2 修复 loader 后 15/15 PASS：三个 Mapper 对象真实构造，random/fix/depends 状态与 recipe 一致，optimizer-disabled 输出为 `[-1,1,3,5,7]`。

最终结果：`outputs/autocontract_p5c_cedar_runtime_smoke.json`，SHA-256 `776f62f171d84d87d87e5fb56367cd00db8cb36d59494b3ecbff5b5dec881cdc`。

## P5D：cedar cache optimizer 消费 randomness hint

P5D 使用 cedar 官方 `test_cache_optimizer_stats.yml` 和真实 optimizer。AutoContract arm 将 crop 标为 random，cedar 计划为：

```text
source(6) -> decode(5) -> cache(7) -> crop/random(4) -> ...
```

只移除该单一 hint 后，cache 向下游移动到 later-random 前：

```text
source(6) -> decode(5) -> crop(4) -> normalize(3) -> noop(2) -> cache(7) -> random(1)
```

17/17 PASS。它证明 cedar 的真实 cache planner 消费 `is_random`；不证明 cache 在 Windows 执行、性能提高或 AutoContract 对新语料判定正确。

## P5E：cedar reorder optimizer 消费 fix/depends_on

P5E 使用 P5A 编译出的真实 hints：

- semantic Unknown 的中间 op 发出 `fix=true`，将候选数从 hint-removed 的 6 降至 1；
- `normalize.depends_on=[decode]` 将候选数从 6 降至 3，并让所选 plan 保持 decode 在 normalize 前。

17/17 PASS。它只证明 cedar 机械消费 constraints，不能证明这些 constraints 足够。

## P5F：pure 不等于 commutative

三段函数为 `x+1`、`2x`、`x-3`。它们全是 deterministic、无外部状态、one-to-one，但不交换。P5A 原策略发出 `random=false, fix=false, depends_on=[]`；cedar 根据官方 profile 把路径从 `[3,2,1,0]` 重排为 `[3,0,1,2]`。真实执行输出从：

```text
[-1, 1, 3, 5, 7]
```

变成：

```text
[-5, -3, -1, 1, 3]
```

P5F counterexample reproduction 11/11 PASS，但系统 verdict 为 `fail_unsafe_reorder_authorization`。应撤销“P5A 可凭 effect purity 和显式 dependency 安全授权 adjacent reorder”的主张。责任边界在 AutoContract mapping：cedar 公开设计本来就要求用户提供顺序约束。

## P5G：ReorderCapabilityV0

修复不再扩张 EffectV7，也不把 cache/replay capability 混在一起。ReorderCapabilityV0 receipt 绑定：

- operation context 与 input schema；
- 两侧 operator ID；
- 两侧 contract SHA-256 和 SourceIndex SHA-256；
- `commutes` relation、proof method、proof SHA-256 和 proof scope。

默认所有 op 都 `fix()`。一个连续区域只有在以下条件全部满足时才取消 fix：区域至少含两个 op、没有 P5A barrier、区域内每个无序算子对都有且只有一个 exact-bound Supported receipt。原因是 cedar 会枚举区域内任意排列；仅证明相邻一对不足以授权三算子全排列。

P5G 20/20 PASS：

- P5F 非交换反例在无 receipt 时只剩 1 个 plan，顺序和输出恢复；
- 三个加常数函数在 3 个两两 receipt 完整时恢复 6 个候选，cedar 重排但输出仍为 `[6,7,8,9,10]`；
- 缺一个 pair、source drift、Unsupported、重复 receipt 均不能形成三算子 unrestricted region；
- P5A 原 barrier 不会被清除，显式 dependency 保留；
- 输出不含 cost/placement/tier 决策。

最终结果：`outputs/autocontract_p5g_reorder_capability.json`，SHA-256 `0922f625d24880719aa4d1e148b5288297bea0759d41eff6be81114685c6d060`。

## P5H：receipt 绑定不等于 proof verification

P5H 为 P5F 非交换函数伪造三张 exact-bound、status=Supported 的 V0 receipt；`proof_sha256` 只是任意字符串的合法 SHA，并无 proof artifact 或 verifier 执行。V0 接纳完整 pair set，cedar 恢复 6 个候选并再次产生错误输出。攻击 8/8 复现，系统 verdict 为 `fail_unverified_receipt_trust_boundary`；结果 SHA-256 `057fda1f173f4f94dce50dc37c17798a3ffa0d5702f09faef0b08ab220390419`。

因此 P5G 的安全条件必须显式写成“receipt 来自受信且可审计的 producer”。V0 是 transport/composition schema，不是 proof checker。严格模式在 V1 完成前只能拒绝任意外部 Supported assertion。V1 至少需要 verifier identity/version/source digest、proof artifact、可重放验证或签名/allowlist、source-to-proof-IR 绑定、assurance tier 与撤销机制；有限 differential testing 只能作为 falsifier/empirical evidence，不能单独充当严格证明。

## 研究含义与下一步

当前最合理的系统分层是：

```text
EffectV7 semantic contract
  + SourceIndexV1 validity
  + rewrite-specific capability
      - ReplayCapabilityV1 for registered parameter replay
      - ReorderCapabilityV0 for pairwise commutativity
      - cache-specific randomness/state/external/cardinality boundary
  -> backend constraints
  -> backend cost optimizer
```

接下来不应继续用 synthetic receipt 自证。先完成 ReorderCapabilityV1 trust root/proof verification，再为真实 torchvision/Kornia/Albumentations 算子对建立可审核的 commutativity oracle；比较 restricted-static/formal、manual-reviewed 与 bounded differential 的 coverage、false accept 和 assurance tier；然后在独立 corpus 中 one-shot 评估。若无法获得受信且可验证的 pair receipts，reorder 分支必须默认全 fix，并作为安全但零收益的负结果报告。
