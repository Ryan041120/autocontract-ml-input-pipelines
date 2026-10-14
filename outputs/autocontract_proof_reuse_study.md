# 共享证明：证据复用与失效离线消融

2026-10-14。仅纯符号模型与保存声明检查，未重新运行完整 adapters／live guards。

| 开发变化 | 旧证书通过 | 新模型推导通过 | 保存声明匹配 | 旧检查／新推导的 derive 次数 |
|---|---|---|---|---|
| unchanged | True | True | True | 1／2 |
| case_name_only | False | True | True | 1／2 |
| probability_zero | False | True | True | 1／2 |
| probability_one | False | True | True | 1／2 |
| larger_legal_dimension_domain | False | True | True | 1／2 |
| unsupported_mean | False | False | True | 1／1 |
| changed_observation_boundary | False | False | True | 1／1 |
| concurrent_history | False | False | True | 1／1 |
| missing_resource_assumption | False | False | True | 1／1 |
| changed_source_declaration | False | True | False | 1／2 |
| changed_runtime_declaration | False | True | False | 1／2 |
| changed_public_pool_declaration | False | True | False | 1／2 |
| tampered_certificate_same_context | False | True | True | 1／2 |

旧证书验证仍调用一次完整 derive；适用 context 的新推导加验证调用两次。这是符号调用计数，不是耗时、缓存速度或主方法独有收益。原 analyze 两种方法共用同一关系路径，均允许传入 certificate。

参数概率与合法尺寸变化可以在模型内重新推导，但旧证书因全 context 绑定失效；名称变化也失效，属于保守绑定成本，不是语义变坏。

源码／runtime／pool 声明变化时，单独的新模型推导仍可通过，保存绑定检查拒绝。因此关系模型定理不能独自授权实际程序；完整 guards 与可信映射仍不可省略。

不支持的参数、消费边界、并发历史或缺失资源假设不获证明；不等于已有反例。篡改证书拒绝且不能只检查 context hash。

没有新的主方法／静态预测或独立参考标签，没有证据证明方法优势。人工可选，profiling 暂停。
