# AutoContract — 当前状态

更新日期：2026-09-09。此页为当前入口；过程记录见[历史状态全文](docs/history/current_state_2026-09-09.md)。历史记录中的“当前”“尚未”等表述只对应记录当时。

## 当前阶段：P5V 数据与环境准备已完成

- 保留 DTD r1.0.1、官方 partition 1、47 类 category 标签。
- manifest attempt 0 因跨允许 split 内容重复而停止；随后用户授权整组隔离、创建独立 Python 3.11 环境、仅再生成一次 manifest。
- fresh attempt 1 成功：4 组跨 split 完全重复内容、共 8 个样本已隔离，无搬移、替换或补样本。
- profile/calibration：468；effect-evaluation：1406；task-validation：1878；共 3752。各 split 仍含全部 47 类，允许 split 间无剩余内容 SHA 交叉。
- P5V 专用 Python 3.11.9 环境导入检查通过。P5T 历史环境未修改，其原 base Python 缺失问题仍保留。
- 未读取 test1，未运行 P5V profiling、训练、Cedar 或性能计时；`scientific_evidence=false`。

## 当前有效文件

| 文件 | 用途 |
|---|---|
| [P5U 研究设计](.research/semantics_safe_reconfiguration/p5u_bottleneck_gated_safe_reorder_design.zh-CN.md) | 瓶颈动机、实验范围和停止规则 |
| [P5V 数据划分设计](.research/semantics_safe_reconfiguration/p5v_dtd_dataset_split_design.zh-CN.md) | 静态设计，实际计数以修订及 manifest 为准 |
| [重复隔离修订](benchmark/final_v1/p5v_dtd_duplicate_quarantine_amendment_v1.json) | 全等价类隔离、不补样本 |
| [样本 manifest](benchmark/final_v1/p5v_dtd_split_manifest.json) | 3752 个可用样本的身份与划分 |
| [P5V 环境清单](benchmark/final_v1/p5v_runtime_environment_manifest.json) | 固定依赖与解释器身份 |
| [attempt 1 收据](benchmark/final_v1/p5v_dtd_manifest_attempt1_receipt.json) | 唯一一次 fresh 生成及复核记录 |

manifest SHA-256：`6491cf0aaa7aa2da9cd06bc5ca31a4c68a999b95e47d8a90ac05155a630c61af`。

## 既有成果与结论边界

- P5S：机制验证完成，性能收益 **No-Go** 保持不变。
- P5T attempt3-v4：完整 fresh 8-block M0 校准完成。aggregate 标记 `scientific_evidence=false`，只允许逐点描述；禁止 pooling、CI、Go/No-Go、总体稳定加速、泛化、因果、冷缓存、GPU 或正式测试集性能声明。
- P5T 的 8 个校准点不得用于 P5V 选择或推断。
- P5T v11/v12/v13 失败现场必须保留；v13 partial 不得读取并汇报 performance，不得复用为正式结果。
- 历史版本及关键 SHA 见[完整过程记录](docs/history/current_state_2026-09-09.md)。

## 下一步与执行约束

当前用户明确要求：**暂不运行 profiling**。本次目录整理仅调整文档与辅助材料，不构成任何实验授权。

P5V 后续需按既定设计补齐运行前的 runtime/Resize/batch/steps/environment 等固定条件；独立环境导入通过不等于 Cedar 和完整 profiling 执行链已就绪。任何 P5V profiling 或训练均待用户明确授权。

P5V 既定边界为四 cell、单机 CPU-warm、worker=0、无 prefetch、baseline-only profiling；每 cell 5 warm-up blocks + 20 measured blocks，报告 median/IQR/MAD。MAD/median > 10% 或环境/电源/温度门失败时 first-error stop，不自动重跑、不删异常、不补 block。资格门为 exposed_input_share >= 20% 与 predicted_gain_share >= 5%。任务级 non-inferiority margin 是 P5W freeze 前 blocker。

保持 train/validation/test 隔离，禁止提前查看正式测试结果。冻结实验的代码、schema、配置、随机种子、环境和 hashes 不能因目录整理改变。不得为非科研关键问题增加递归 closure/validator/review 层，也不得自动 rerun、recover 或启动新控制面版本。
