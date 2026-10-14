# Final v1 一次性运行检查表

## A. 语料与 oracle 封存

- [ ] public manifest 为 `sealed`，共 50–80 个真实 unit，至少 3 框架、2 领域。
- [ ] 至少 1 个框架不在 contamination registry；所有源码绑定均在 analyzer freeze 后选择。
- [ ] 公开 manifest 通过 strict 校验且无标签键、答案文本或安全比例。
- [ ] private oracle 已完成双人复核与仲裁，位于开发者不可见的位置。
- [ ] oracle 保管人生成并公开 commitment；未公开标签分布。

## B. 执行物封存

- [ ] analyzer、optimizer policy、threshold、runner、adapters 和依赖锁均不可再修改。
- [ ] `seal` 生成 freeze JSON，参与者核对所有 SHA-256。
- [ ] 正式运行环境从未挂载 private oracle。
- [ ] 输出 schema、timeout、unsupported 和 crash 计分规则已经固定。
- [ ] 空跑只使用无标签 fixture；没有在 final unit 上做试运行。

## C. 一次性预测

- [ ] 记录开始时间、机器/OS/Python/依赖和 git commit。
- [ ] 逐 unit 写 append-only 原始预测；失败也保留，不重试到成功。
- [ ] 只允许修复基础设施级故障，且必须在查看任何标签前由第三方记录；若代码或规则改变，当前 benchmark ID 作废。
- [ ] 运行结束立即冻结 prediction JSON、日志和环境清单的哈希。
- [ ] 在 prediction commitment 发布前，任何人都未解封 private oracle。

## D. 解封与计分

- [ ] oracle 保管人发布 private oracle；运行者先执行 `verify-oracle`。
- [ ] 校验失败立即停止，不选择性修补。
- [ ] 一次性计算全部预注册指标：known-unsafe false accepts、safe recall、coarse-reason accuracy、coverage、oracle-benefit coverage。
- [ ] 同时报告 unit 数、失败/不支持、置信区间、每框架/领域切片和完整混淆矩阵。
- [ ] 不根据结果改标签或排除困难 unit；任何探索性二次分析明确标为 post hoc。

## E. 论文表述

- [ ] 达到所有 gate 才能声称通过 final-blind benchmark。
- [ ] 零已知不安全误接收必须连同样本数和置信区间报告，不能表述为普遍安全证明。
- [ ] 未达到 gate 仍完整报告，并把失败类型转为下一版本的研究问题，而不是回填本版本。
