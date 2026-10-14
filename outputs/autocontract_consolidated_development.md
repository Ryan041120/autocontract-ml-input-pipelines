# AutoContract 主线：统一 CPU 比较与 Cedar 规划

2026-10-13。已知开发案例，`scientific_evidence=false`。

四个公开案例采用普通 CPU float32、3×4×4、[0,1] 输入域和 pair_exit_strict 边界。主方法与强静态共享关系知识及运行条件；差分方法共享三种合成输入、种子、重复模式和 96 次调用／30 秒上限。
output-only 是显式去掉状态根的消融，仍比较精确输出 bytes／metadata 与异常；stateful 保留输入、RNG、对象和 Tensor 别名观察。源码引导只按事前固定的源码规则选择探针，不是完整自适应 greybox fuzzing。

| 案例 | 方法 | 建议／证据 | 候选调用 | 有效计划数 | Cedar 选择 |
|---|---|---|---:|---:|---|
| half_normalize_hflip | autocontract | unknown/none | 0 | 1 | left → right |
| half_normalize_hflip | strong_static | unknown/none | 0 | 1 | left → right |
| half_normalize_hflip | fail_closed | unknown/none | 0 | 1 | left → right |
| half_normalize_hflip | manual_hints | 未提供人工预测 | — | 1 | left → right |
| half_normalize_hflip | fixed_output | accept/finite_probe | 96 | 2 | right → left |
| half_normalize_hflip | fixed_stateful | accept/finite_probe | 96 | 2 | right → left |
| half_normalize_hflip | source_guided_stateful | accept/finite_probe | 96 | 2 | right → left |
| other_mean_hflip | autocontract | unknown/none | 0 | 1 | left → right |
| other_mean_hflip | strong_static | unknown/none | 0 | 1 | left → right |
| other_mean_hflip | fail_closed | unknown/none | 0 | 1 | left → right |
| other_mean_hflip | manual_hints | 未提供人工预测 | — | 1 | left → right |
| other_mean_hflip | fixed_output | accept/finite_probe | 96 | 2 | right → left |
| other_mean_hflip | fixed_stateful | accept/finite_probe | 96 | 2 | right → left |
| other_mean_hflip | source_guided_stateful | accept/finite_probe | 96 | 2 | right → left |
| half_normalize_center_crop | autocontract | unknown/none | 0 | 1 | left → right |
| half_normalize_center_crop | strong_static | unknown/none | 0 | 1 | left → right |
| half_normalize_center_crop | fail_closed | unknown/none | 0 | 1 | left → right |
| half_normalize_center_crop | manual_hints | 未提供人工预测 | — | 1 | left → right |
| half_normalize_center_crop | fixed_output | reject/counterexample | 4 | 1 | left → right |
| half_normalize_center_crop | fixed_stateful | reject/counterexample | 4 | 1 | left → right |
| half_normalize_center_crop | source_guided_stateful | reject/counterexample | 4 | 1 | left → right |
| half_normalize_resize | autocontract | unknown/none | 0 | 1 | left → right |
| half_normalize_resize | strong_static | unknown/none | 0 | 1 | left → right |
| half_normalize_resize | fail_closed | unknown/none | 0 | 1 | left → right |
| half_normalize_resize | manual_hints | 未提供人工预测 | — | 1 | left → right |
| half_normalize_resize | fixed_output | reject/counterexample | 52 | 1 | left → right |
| half_normalize_resize | fixed_stateful | reject/counterexample | 52 | 1 | left → right |
| half_normalize_resize | source_guided_stateful | reject/counterexample | 4 | 1 | left → right |

## 这轮能得出的结论

AutoContract 的真实旧 verifier 已通过 strict bridge 接入，但不满足新严格观察证明的建议保持 Unknown。强静态使用同一受限关系前提，也没有完整严格证明；本轮没有显示主方法相对强静态的接受优势。

动态 Accept 仅表示有限计划没有观察到差异；Reject 附逐探针记录和反例维度。它们进入规划的只是方法建议，不授予候选管线的执行权限。不能把 Unknown 当错误、有限 Accept 当真值，或用这些开发案例计算独立准确率。

人工 hints 未提供，保留 prediction_present=false；human oracle 未解封也未读取。两项都是未完成基线，不纳入已完成比较或准确率分母。

Cedar 使用固定提交的真实枚举／成本／选优源码，先筛候选再排序，最终验证选择属于方法请求。所有方法共享人工 profile；成本与选择用于检查接入，不表示真实收益。完整 Feature／PhysicalPlan API 仍未验证。

## 接下来的研究缺口

1. 把条件关系论证转为在明示受信边界下可检查的证据与验证器，并让强静态共享同一知识；否则主方法与强静态都只会保守拒绝重排。
2. 独立人员准备未见案例与标注、提供 manual hints；锁定正式预算后再解封 oracle。源码引导动态方法还需要真正自适应策略，当前固定选探针版本不能代表所有 greybox 方法。
3. 验证完整 Cedar API；另行获授权并确认瓶颈后，再研究净收益。当前未恢复 profiling 或训练。

产物核对：150/150；27 份既有文件 hash 不变。逐探针、真实 verifier 审计与规划记录见同名 JSON。
