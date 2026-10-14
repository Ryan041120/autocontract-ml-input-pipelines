# AutoContract

Research prototype for evidence-checked reordering of ML input pipelines under explicit observation and consumer contracts.

这是一个进行中的科研项目，不是通用安全优化系统。当前可核对的成果包括严格语义反例、受信模型中的条件关系、优化器候选约束接入，以及未满足预设收益门的历史性能结果。**尚未建立相对强基线的方法优势、稳定端到端收益或真实任务质量保持。**

## 从这里开始

| 内容 | 入口 |
|---|---|
| 做了什么、哪些结论成立、老师两问回答到哪里 | [阶段成果总结](docs/research_summary_2026-10-14.zh-CN.md) |
| 下一步的优先级、验收与停止条件 | [收拢后的研究路线](docs/research_roadmap.zh-CN.md) |
| 对新颖性、方法和证据的审查 | [研究审查](review/research_assessment_2026-10-14.zh-CN.md) |
| 公开内容与离线复核边界 | [Public artifacts](docs/PUBLIC_ARTIFACTS.md) |
| 可复核的成果投影与模型例子 | [Public evidence snapshot](reports/research/2026-10-14/README.md) |
| 更早阶段的背景与过程记录 | [历史导航](docs/research_index.md) |

## 当前成果（2026-10-14）

- 统一包含输出字节、布局、定义性、输入／对象／RNG状态和别名的安全观察；复现 Normalize／Crop 数值一致但布局和后续行为不同的反例。
- 实现 Normalize(0.5)／Flip 的条件模型关系，以及微型 Normalize／CenterCrop(2,2)／stack 的封闭 batch 模型。源码映射、原生语义和 non-escape 仍有显式假设。
- 接通主方法与基线的共同开发请求和固定 Cedar 规划核心；人工成本不代表实测速度，完整当前 API 路径尚待验证。
- 完成13种证据复用／失效开发消融。共享静态与主方法共用关系路径，目前不能把复用或版本绑定算作独有优势。
- 准备真实47类标签的四 cell 原序 baseline 和 runner／gates。真实 pipeline 与 profiling 尚未执行验证，资源准备留待后续。

历史 P5S 的预设收益判定保持 **No-Go**；P5T仅允许8点校准的逐点描述。测试／保存后核对次数不等于独立 benchmark 样本数。

## 研究主线

先在明确边界下比较有效关系／反例与分析成本，再把真实候选接到消费者和优化器；有瓶颈与收益机会时才测净收益。近数据处理、动态卸载、跨框架通用化和任务级放宽语义暂不扩展。

manual hints／human oracle 是可选补充。自动参考仍须有可检查证据和明确适用域；Unknown 不强行填成真值。共享静态和强差分应拥有同样的规则、源码信息与预算。

## 只运行纯模型复核

Python 3.11，仓库根目录：

```sh
python -B experiments/check_published_model_examples.py
```

这个命令检查4个保存的条件模型例子及定向篡改拒绝，只使用标准库，不导入Torch、不读取图片、不构建模型、不采集温度或进行profiling／训练。它验证受信模型关系，不验证native内核、live guards或完整Cedar。

当前公开包是经过整理的摘要、代表性结果和纯模型源码。原始机器状态、绝对本机路径、失败／partial状态、私有oracle、数据集及第三方安装包不由此次发布新增；本地原记录保留。旧协议中的强制人工流程和当时“下一步”属于历史，不是当前路线。

[第三方来源](THIRD_PARTY.md)保留。根目录requirements是历史依赖记录，不能当作当前完整重现环境；请勿把所有历史实验脚本当作测试套件批量运行。
