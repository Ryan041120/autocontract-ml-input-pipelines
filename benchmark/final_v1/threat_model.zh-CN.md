# Final v1 有效性威胁模型

这份协议优先防“实验看上去独立，实际上答案已经进入开发闭环”的问题。它不把密码学承诺误当成标签本身正确，也不把 0 次观察到的 violation 写成普遍安全证明。

| 威胁 | 可能造成的假结论 | 当前控制 | 仍需人工承担的责任 |
|---|---|---|---|
| 公开清单泄漏标签 | analyzer 或操作者直接/间接看到答案 | 递归禁止 answer-bearing keys；public/private schema 分离 | 检查自然语言中是否用暗示性措辞编码答案 |
| 开发语料污染 | 在熟悉失败模式上测出虚高泛化 | 永不删除的 contamination registry；至少一个全新框架 | 策展者披露曾阅读的源码、issue、文档和衍生样例 |
| analyzer 作者兼任 oracle | 独立标签只是开发假设的复写 | primary/reviewer 均须独立；开发者不得最终仲裁 | 学长或第三方确认实际人员独立性 |
| 先看预测再改标签 | 争议项向系统输出靠拢 | 私有 oracle 先加盐 commitment；预测先冻结再解封 | oracle 保管人隔离文件和访问权限 |
| 先看效果再挑样本 | 删除失败或不支持 unit | sealed manifest 固定 ID、commit、binding hash | 按预写纳入规则抽样并保留失败项 |
| 重试到成功 | 把不稳定性和 crash 隐藏 | append-only 一次性运行；失败计入 coverage | 第三方记录基础设施异常，代码变化则废弃 benchmark ID |
| 同输出伪等价 | 漏掉 RNG、state、gradient、lineage、diversity | 五类 semantic oracle 与 effect checks | 为框架生命周期选择足够长的观测窗口 |
| 有收益即安全 | 性能正向掩盖语义破坏 | 先冻结正确性、后做 performance profile | 不用收益信息反向修改安全标签 |
| 哈希正确即 oracle 正确 | 一致地承诺了错误标签 | 双人标注、证据锚点、争议仲裁 | 专家复核和可复现实验仍不可省略 |
| 小样本零误报过度外推 | 把有限证据写成通用保证 | 预注册门槛、样本数和置信区间一起报告 | 论文明确 claim scope 与未覆盖 effect 类别 |

## 暂不声称解决的威胁

- 恶意 oracle 保管人可以在 commitment 前故意制作错误标签；协议只能发现 commitment 后的改变。
- Git commit 和 source hash 保证绑定一致，不保证上游仓库许可、供应链或数据集条款合规。
- 50–80 个 unit 仍不能穷尽动态 Python、native extension、分布式 worker 和未知外部服务行为。
- 一个新框架只能提供有限外部有效性；最终报告必须按框架、领域和 effect 类别切片。

因此 final v1 的正确定位是：对一个明确封存语料的可审计一次性检验，而不是 AutoContract 对所有 ML input pipeline 的形式化安全证明。
