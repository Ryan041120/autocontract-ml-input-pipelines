# Final v1 独立标注指南

## 1. 标注者看到什么

标注者拿到 sealed public manifest、固定 commit 的只读源码、依赖锁和通用测试脚手架。不得查看 AutoContract 输出、历史 H6–H8 标签、开发者对该 unit 的判断或其他标注者的初稿。

每位 primary 先独立回答两个问题：

1. 在 manifest 声明的上下文中，候选优化是否保持可观察语义？
2. 若拒绝，首要的粗粒度原因是什么？

“输出在几个样本上相同”不等于安全。必须同时检查输出、随机数状态、可变对象、外部状态、autograd、源码绑定和跨调用/跨 epoch 多样性。

## 2. unit 级步骤

1. 校验 repository commit、文件、symbol 和 `binding_sha256`，不一致立即暂停，不猜测映射。
2. 写下配置、生命周期阶段、训练/评估模式、worker 数和随机种子假设。
3. 阅读候选边界内外的实现以及直接调用链；把证据锚定到 commit:path:line 或测试 ID。
4. 先做静态 effect 判断，再运行 manifest 预先规定的差分检查。不得为了得到更清晰结果临时改变样本。
5. 分别记录 output、RNG、gradient、lineage、diversity oracle。未知就是 `unknown`，不要用“看起来没问题”替代证据。
6. 给出 `admit` 或 `reject`。证据不足、运行环境无法覆盖必要分支时必须 fail closed，使用 `unsupported_or_ambiguous`。
7. 填写 confidence、rationale 和 evidence anchors；不能只复制框架文档的宣传性描述。

## 3. 标签定义

- `admit`：在声明上下文及生命周期内，候选变换的所有相关可观察语义都有正面证据支持等价。
- `reject`：存在反例，或缺少证明关键语义等价所需的证据。
- `known_unsafe=true`：已经有源码、规范或可复现实验表明至少一项语义被改变。单纯“不确定”不设为 true。
- `coarse_reason=none`：只与 `admit` 配对。
- `unsupported_or_ambiguous`：证据不足导致的保守拒绝，不得伪装成已知不安全。

主要拒绝原因按最早破坏正确性的机制选择：隐藏 RNG、外部状态、内部 mutation、模式依赖、lineage/binding、augmentation diversity、gradient/autograd、无法支持。若有多个原因，在 rationale 中完整记录，但只给一个 coarse reason。

## 4. 性能与正确性隔离

是否有收益不决定是否安全。先冻结语义标签，再执行 paired performance profile。只有 oracle 允许且收益为正的 workload 才进入“oracle benefit”分母。失败、超时和不支持要计入 analyzer coverage，不能从结果中删除。

## 5. 保密与污染

private oracle 不提交到本仓库，不放到开发者可访问的云盘或 issue。盐值用 32 个随机字节，例如：

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

发现自己曾参与 analyzer 规则、阈值、该框架开发语料或相关失败分析时，必须披露并退出该 unit 的 primary/reviewer 角色。
