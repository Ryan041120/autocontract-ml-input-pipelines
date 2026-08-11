# P5B cedar 固定版本 API 一致性复盘

## 结论

P5B 在 cedar commit `f062305fcdab196e871c5d09b4c82ab788b4da79` 上完成源码级公共 API 绑定，最终 12/12 PASS。验证对象包括 `MapperPipe(tag=..., is_random=...)`、fluent `fix()`、`depends_on(...)`、公开示例的真实用法，以及 AutoContract contract/source digest 只留在 sidecar、不写 cedar 私有字段。

该结果把 P5A 的“cedar-shaped JSON”提升为“与一个固定官方提交的源码 API 一致”，但没有导入 cedar、运行 optimizer 或测性能。

## 被保留的无效尝试

attempt 0 名义 12/12 PASS，但 P5A example recipe 没有任何 `fix`/`depends_on` 调用，导致“只使用公共方法”门槛对空集合成立。结果保存为 `outputs/autocontract_p5b_cedar_api_conformance_attempt0_vacuous.json`，判定为 invalid vacuous test。

v1 protocol 要求 recipe 的实际方法集合精确等于 `{fix, depends_on}`。修正后 recipe 用构造参数设置 `tag/is_random`，用公开 fluent 方法设置一个 fix 和一个 dependency；最终结果为 `outputs/autocontract_p5b_cedar_api_conformance.json`，SHA-256 `217a4060fbe16326365102611968bf8ecbc9a4fa2697ebb5ea18c85b577766d9`。

## 范围边界

- 这是 commit-bound source/API conformance，不是 runtime conformance。
- cedar 不接收 AutoContract contract/source digest；它们必须作为 sidecar 与 plan/receipt 一起携带。
- 该测试只证明 API recipe 的形状，不证明 P5A 的安全授权政策正确；后者在 P5F 被单独证伪并于 P5G 修复。
