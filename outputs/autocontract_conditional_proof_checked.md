# 共享条件证明：Normalize／Flip 与 Cedar 规划开发结果

2026-10-13。scientific_evidence=false。机器检查的是声明抽象语义的条件关系定理；原生实现与源码到模型映射仍为受信假设。
没有执行 Normalize／Flip 或其他候选 forward，没有数据集、profiling、训练或性能计时。

| 案例 | 方法 | 建议／证据 | 规划选择 |
|---|---|---|---|
| half_normalize_hflip | autocontract | accept/proof | right → left |
| half_normalize_hflip | shared_static | accept/proof | right → left |
| other_mean_hflip | autocontract | unknown/none | left → right |
| other_mean_hflip | shared_static | unknown/none | left → right |
| half_normalize_center_crop | autocontract | unknown/none | left → right |
| half_normalize_center_crop | shared_static | unknown/none | left → right |
| half_normalize_resize | autocontract | unknown/none | left → right |
| half_normalize_resize | shared_static | unknown/none | left → right |
| half_normalize_hflip_p0 | autocontract | accept/proof | right → left |
| half_normalize_hflip_p0 | shared_static | accept/proof | right → left |
| half_normalize_hflip_p1 | autocontract | accept/proof | right → left |
| half_normalize_hflip_p1 | shared_static | accept/proof | right → left |

Normalize(mean=std=0.5, inplace=False)／RandomHorizontalFlip 在 p=0、0.5、1 三种配置上，两种方法均条件 Accept；mean=0.4、Crop、Resize 不在该证明规则内，均 Unknown。Unknown 不表示它们已被证明不安全。

每份证明在两个符号分支中比较任意合法坐标的原始 binary32 运算表达式，并覆盖声明的输出 metadata、受保护输入、对象状态、Tensor 别名与 RNG 状态转移；有界 totality 和有限串行历史归纳均依赖显式原生／资源假设。没有把有限测试相同升级成证明。

两个方法共用证明和相同运行条件，接受结果一致；本轮没有主方法独有优势。新 context 明示 entry／history／trust policy 和检查器源码，不能把旧动态报告的证据搬到新 context；旧 strict bridge、旧预测与源码论证保留原样。

Accept 为在声明受信模型下的离线建议，execution_authorized=false；尚未验证完整 Cedar API、运行锁或任意 native／并发语义。人工成本 profile 只检查规划接入，不是实测收益。

初版针对性检查发现证书 metadata 与内部布局对象共享可变列表，导致篡改形状／stride 时可能连带改变检查依据。现已用独立副本修复，两种篡改均被拒绝；初版源码快照、初版报告及失败日志保留，不把初版当作当前检查器结果。

运行内一致性核对 81/81；47 份既有文件 hash 不变。9 项证明／上下文检查及 1 项 metadata 隔离检查通过（含两个篡改子例），候选调用为 0。
