# P5I–P5J：ReorderCapabilityV1 本地证明重放与单调性修复

日期：2026-07-30

## 结论

P5H 发现的“调用方可伪造 Supported receipt”在一个明确受限的证明语言内已经闭合。严格 V1 不信任调用方填写的 status 或 proof hash，而是本地重新索引当前 callable、重新提取仿射 IR、重新计算两个复合顺序并比较精确等式。P5I 在固定 cedar commit `f062305fcdab196e871c5d09b4c82ab788b4da79` 上 23/23 PASS。

这不是一般 Python 或真实 ML operator 的交换性证明器。当前 Supported 仅覆盖单参数、单 return、无调用/分支/状态/I/O 的整数仿射表达式：变量、整数常量、正负号、加减和常数乘法。其余语法一律 Unknown/full fix。

## 信任根与证明对象

V1 receipt 增加：

- `assurance_level=locally_replayed_restricted_static`；
- verifier id、语义版本和 verifier closure SHA-256；closure 同时绑定 V1 verifier、SourceIndexV1 与 SourceIndexV0 实现；
- exact affine proof artifact：左右 IR、`right(left(x))`、`left(right(x))` 与 equality；
- canonical proof digest、固定 domain 和固定 proof scope；
- operation context、input schema、两侧 contract 与 SourceIndexV1 binding。

SourceIndexV1 绑定源码 AST 之外的 bytecode、constants、defaults、closure、globals、wrapper chain 与 origin。因此 receipt 签发后替换 callable 会在本地重放前失效。revoked verifier closure digest 也会使全部对应 receipt 失效。签名没有被当成首选修复，因为签名只能证明 issuer 身份，不能单独证明交换律为真。

## P5I Cedar 结果

- P5H 风格三张 V0 伪造 receipt：全部拒绝，1 个候选，保持原顺序；
- 非交换链 `x+1 -> 2x -> x-3`：只有平移对可证明，无法获得完整 pair cover，1 个候选，输出 `[-1,1,3,5,7]`；
- 可交换链 `x+1 -> x+2 -> x+3`：3/3 pair 本地证明，恢复 6 个候选；cedar 选择 `[3,0,1,2]`，输出与固定顺序同为 `[6,7,8,9,10]`；
- artifact 重算伪造、stale digest、verifier version/source tamper、SourceIndex drift、revocation、duplicate 和不支持的 call expression 均 fail closed；
- 公开 JSON schema 对实际生成的三张 receipt 验证通过；输出不含 cost/placement 决策。

## P5J 失败、修复与回归

P5J attempt 0 保留为 5/6 FAIL。55/55 receipt mutations 均被拒绝，但 19 个 receipt-subset 包含关系中出现一个证据单调性反例：只有 `crop↔normalize` 时 V0 贪心分区开放后两项；再增加 `decode↔crop` 后却改为开放前两项。该问题不造成未经证明的重排，但会让“增加有效证据”撤销既有权限，且使 optimizer opportunity 不稳定。

V1 修复不改写冻结的 V0：对每个由旧 barrier 划分的 maximal base-flexible segment，只有所有无序 pair 都通过本地重放才激活整个 segment；不再选择重叠的局部 clique。修复后：

- P5I 回归仍为 23/23 PASS；
- P5J attempt 1 为 6/6 PASS；
- 55/55 隔离变异 fail closed；
- post-issue callable replacement 被拒绝；
- 19/19 subset monotonicity comparisons 通过；
- 8 个 receipt 子集中只有 mask 7，即 3/3 完整覆盖，开放三算子 region。

## 可以与不可以主张的内容

可以主张：P5H 的无验证 receipt 接纳问题在受限整数仿射语言中由本地重放关闭；严格合成是 fail-closed、SourceIndexV1-bound、可撤销且证据单调的；真实 cedar optimizer 能消费通过验证的约束并在正例保持输出。

不可以主张：一般 ML preprocessing operator 已可自动证明；有限差分可签发 strict Supported；V1 是 Python sound verifier；签名 issuer 已实现；真实训练收益或跨框架覆盖已建立。

## 下一主线

停止继续扩 synthetic affine 语法。下一轮建立 20–40 个真实 operator-pair 的公开候选清单与双人 oracle，逐对写清 input domain、dtype/overflow、shape/channel assumptions、exception behavior、RNG/state/I/O 和 order context。restricted-static、manual-reviewed 与 bounded differential 作为不同 producer 分层比较；bounded differential 只能提供反例或辅助证据，不能单独签发 strict Supported。只有通过 V1/受信可撤销 verifier 的 pair 才进入 cedar one-shot execution，并单独报告 coverage、Unknown、candidate reduction、output/trace/RNG/model metric。
