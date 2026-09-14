# AutoContract 研究导航

当前入口：[CURRENT_STATE](../CURRENT_STATE.md)。阶段字母与版本号保持原样，历史说明不代表当前执行授权。

## 当前主线

| 阶段 | 设计 | 协议与产物 | 状态 |
|---|---|---|---|
| P5U | [瓶颈门控设计](../.research/semantics_safe_reconfiguration/p5u_bottleneck_gated_safe_reorder_design.zh-CN.md) | [静态协议](../benchmark/final_v1/p5u_bottleneck_gated_safe_reorder_protocol.json) | 新一轮研究设计 |
| P5V | [DTD 划分设计](../.research/semantics_safe_reconfiguration/p5v_dtd_dataset_split_design.zh-CN.md) | [manifest](../benchmark/final_v1/p5v_dtd_split_manifest.json)、[隔离修订](../benchmark/final_v1/p5v_dtd_duplicate_quarantine_amendment_v1.json)、[环境](../benchmark/final_v1/p5v_runtime_environment_manifest.json)、[收据](../benchmark/final_v1/p5v_dtd_manifest_attempt1_receipt.json) | 数据与环境准备完成；profiling 未运行 |
| P5W | 后续任务级评价，约束见 P5U 设计 | 尚未在此建立执行入口 | non-inferiority margin 待固定 |

[manifest 生成器](../experiments/autocontract_p5v_dtd_split_manifest.py) 已完成获准的单次 fresh 生成，本导航不授权重跑。

## 历史研究地图

| 阶段 | 主要问题 | 阅读入口 |
|---|---|---|
| 早期探索 | 成本与在线适应 | [Cachew/Pecan 备忘录](background/cachew_pecan_选题备忘录.md)、[早期选题档案](../.research/topic_dossier.md) |
| H 系列 | 语义、随机状态、重放与缓存 | [阶段汇总](../.research/semantics_safe_reconfiguration/current_experiment_summary.zh-CN.md)、[EffectV7](../.research/semantics_safe_reconfiguration/effect_v7_spec.zh-CN.md) |
| R3 / P4 | 强基线、跨框架能力与适配成本 | [R3-P3d](../.research/semantics_safe_reconfiguration/r3_p3d_replay_capability_postmortem.zh-CN.md)、[P4A](../.research/semantics_safe_reconfiguration/p4a_adapter_burden_postmortem.zh-CN.md) |
| P5A–P5J | Cedar 接入、反例与证明可信性 | [P5C–G](../.research/semantics_safe_reconfiguration/p5c_p5g_cedar_integration_and_reorder_postmortem.zh-CN.md)、[P5I–J](../.research/semantics_safe_reconfiguration/p5i_p5j_reorder_capability_v1_postmortem.zh-CN.md) |
| P5K–P5M | 真实操作对、关系代数与边界 | [P5K](../.research/semantics_safe_reconfiguration/p5k_torchvision_real_pair_coverage_postmortem.zh-CN.md)、[P5L](../.research/semantics_safe_reconfiguration/p5l_torchvision_relation_algebra_postmortem.zh-CN.md)、[P5M](../.research/semantics_safe_reconfiguration/p5m_relation_boundary_falsification_postmortem.zh-CN.md) |
| P5N–P5Q | 独立评估交接与训练语义 | [P5N](../.research/semantics_safe_reconfiguration/p5n_reorder_final_handoff_postmortem.zh-CN.md)、[P5P–Q](../.research/semantics_safe_reconfiguration/p5p_p5q_final_v3_handoff_and_cedar_resnet_postmortem.zh-CN.md) |
| P5R–P5S | 高分辨率负载与端到端收益 | [P5R](../.research/semantics_safe_reconfiguration/p5r_highres_2d_workload_postmortem.zh-CN.md)、[P5S](../.research/semantics_safe_reconfiguration/p5s_div2k_e2e_postmortem.zh-CN.md)；收益 No-Go |
| P5T | 8-block fresh M0 校准 | [P5T 复盘](../.research/semantics_safe_reconfiguration/p5t_attempt3_v4_calibration_postmortem.zh-CN.md)、[完整过程](history/current_state_2026-09-09.md)；仅逐点描述 |

这些阶段包含已知语料校准、反例、机制检查和未完成的独立评估，不能合并为统一有效率或总体加速结论。

## 按文件类型查找

- [experiments](../experiments/)：按阶段前缀查实验代码。
- [benchmark](../benchmark/)：协议与冻结配置；final_v1/v2/v3 是历史协议版本，名称不表示最终科学结果已产生。
- [outputs](../outputs/)：结果与执行记录；失败 attempt、partial 与成功结果不能互换。
- [原始研究记录](../.research/semantics_safe_reconfiguration/)：设计、复盘与源码语料。
- [文献阅读](literature/README.md)、[老师汇报](../reports/supervisor/README.md)、[历史评审](../review/README.md)。

先看当前状态和当前主线；需要了解选择依据时，再查对应阶段复盘。
