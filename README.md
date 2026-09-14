# AutoContract

研究机器学习输入流水线的安全重排：先验证具体操作对在限定条件下能否交换，再由优化器选择执行方案。

## 当前进度（2026-09-09）

当前推进 P5V：DTD 数据划分 manifest 已生成，P5V 专用 Python 3.11.9 环境已建立。隔离 8 个跨划分重复样本后，共保留 3,752 个样本；profiling 尚未运行。

P5S 的性能收益结论仍为 **No-Go**。P5T 已完成一次 8-block 校准，只允许逐点描述，不能据此声称整体稳定加速。P5V 的 manifest 和环境准备不构成科学结果。

## 从这里开始

| 想了解什么 | 入口 |
|---|---|
| 当前状态、约束和下一步 | [CURRENT_STATE.md](CURRENT_STATE.md) |
| 各阶段研究及对应代码、协议、结果 | [研究导航](docs/research_index.md) |
| 老师推荐论文与 AutoContract 的对比 | [论文对比笔记](docs/literature/NDP-DF论文与AutoContract对比.md) |
| 给老师的阶段汇报 | [汇报材料](reports/supervisor/README.md) |
| 历史研究叙述 | [历史 README](docs/history/README_before_organization_2026-09-09.md) |
| 本轮文件迁移与保留说明 | [整理记录](docs/organization_log.md) |

## 目录用途

| 目录 | 内容 |
|---|---|
| `docs/` | 研究导航、论文阅读、选题背景、历史状态 |
| `reports/supervisor/` | 可直接发给老师的汇报文件 |
| `tools/` | 汇报生成等辅助工具 |
| `experiments/` | 版本化实验代码，保留原路径 |
| `benchmark/` | 协议、schema、冻结配置和 manifest，保留原路径 |
| `outputs/` | 实验结果与执行记录，保留原路径 |
| `.research/` | 原始研究记录、源码语料和第三方 Git 子模块 |
| `review/` | 历史评审提示与打包工具 |
| `tmp/` | 论文提取文本和 PDF 检查预览等工作材料 |

## 环境与执行

各研究阶段使用独立环境。P5V 环境见 [环境清单](benchmark/final_v1/p5v_runtime_environment_manifest.json)；根目录 `requirements.txt` 是历史依赖记录，不应直接用于重建 P5V。

当前用户要求暂不运行 profiling。目录整理不启动实验，也不改变数据划分和既有结论。冻结版本、失败现场及 partial 记录的使用边界见 [当前状态](CURRENT_STATE.md)。

第三方来源和版本见 [THIRD_PARTY.md](THIRD_PARTY.md)；Git 子模块路径维持不变。
