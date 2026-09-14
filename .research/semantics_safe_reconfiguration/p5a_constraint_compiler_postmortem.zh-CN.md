# P5A：optimizer constraint compiler 复盘

## 研究目的

P5A 不创建新的 cost optimizer，而是验证冻结的 AutoContract contract 能否变成三类现有系统需要的安全提示：cedar 的 random/fix/depends-on、HyCache 的 online-only/cache boundary、Cachew 的 autocache boundary。输出只含约束与 contract/source/context digests，不含 cost、placement、tier、capacity、worker 或 ILP 决策。

该选择来自 P4 文献压力测试：cedar 已经完成联合优化但依赖用户 randomness/dependency hints；HyCache 已经完成混合部分缓存和 ILP，但依赖用户 online-only/cache_steps；Cachew 的安全 autocache 位置也由用户指定。因此 AutoContract 的合理角色是 constraint compiler/gate，而不是重复这些系统的性能优化器。

## 两次被保留的无效尝试

attempt 0 名义上 12/12 PASS，但 posthoc 检查发现组合漏洞：`decode -> random crop -> normalize` 的 safe prefix 虽然停在 decode，逐 step 输出却把 normalize 标为 HyCache `online_only=false`。normalize 本身是纯函数，但其输入继承了 random crop 的随机 lineage，缓存它同样会冻结增强随机性。该结果因此标为 `posthoc_invalid`，不能作为 PASS。

protocol v1 将 cache materialization eligibility 改为前缀闭包：某一点可缓存，当且仅当从源到该点的每个执行算子都满足严格条件。一旦遇到 sampling RNG、replay-only、state、external I/O、Unknown 或其他非一对一 effect，所有下游普通 materialization point 都保持禁用，除非未来另有显式 keyed-lineage backend protocol。

attempt 1 的 15/15 行为测试通过，但结果仍绑定 protocol v0 hash，而不是 v1 修正，故被标为 `invalid_protocol_binding`。protocol v2 只修复结果绑定，不改任何规则或 fixture。

## 最终结果

最终结果 **15/15、PASS**，并正确绑定 protocol v2。覆盖：纯三步 pipeline、sampling RNG、replay-only 参数键义务、semantic/source Unknown、external I/O、state write、显式 dependency、同 symbol 的 sample/replay operation contrast、Unknown 单调性、无 cost/placement 字段、冻结输入，以及 sampling/replay/Unknown 的三类下游祖先传播。

示例中 `decode -> crop(random) -> normalize` 只暴露 decode 作为 HyCache/Cachew cache boundary；crop 标为 cedar random；normalize 也因 `upstream_noncacheable:crop` 被标为 HyCache online-only。replay-only 即使 ReplayCapability Supported，也不会自动成为普通 cacheable：它要求 parameter-record cache key，而当前三种 backend interface 没有被冻结的 keyed replay cache protocol。

## 能写与不能写的结论

可以写：AutoContract contract 可以被机械翻译为多个已发表 optimizer 的 interface-shaped、fail-closed safety constraints；祖先 effect、operation context 和 source digest 被携带。不能写：已与 cedar/HyCache/Cachew 实际集成、能提升性能、提示完全匹配其当前代码 API、或已解决任意 cache/reorder capability。

下一步真实 integration experiment 必须在公开 backend release 上验证生成提示的可消费性，并把 backend optimizer 产生的 plan 再送入 rewrite-specific verifier；P5A synthetic PASS 不能替代它。

## 证据哈希

- protocol v0: `5643d71cf426915d2b44b39ff71741b1e51db52394b906f804dd667c25f7a3df`
- protocol v1: `528f76066ad3d435ac6e92ee6da3c4ec235f4a8123f51debcfd0284b280525d1`
- protocol v2: `e40d40a0d788d2bdc6926dd10b3121c0bc2278177ac655d219347f0e478cc5cb`
- schema: `640ead1cef3085daf1000d70fdb9240ea2c63a2bb1890d235a754d3696ad910b`
- runner: `c96ed767f97ecd82d6ea7bc574d4a0211bb530464ec42c9960d9459598f5d0ab`
- attempt 0 posthoc invalid: `d000a028951bb7f30ac382d524e35dc9aa44c238515c8c23c3ce8dbfd7972ef7`
- attempt 1 protocol mismatch: `403bfb5d1293c7cd3b756553f6a2929e235c7ed9b234b9441ff214cc76a7d243`
- final PASS: `59d75486cc547277616ad99361a01d3aa66a1e9991091329ebcb4bf4b470ee7a`
