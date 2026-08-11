# AutoContract final blind benchmark handoff v1

这个目录把最终实验拆成三个互相隔离的阶段：语料选择、私有标注、一次性预测。当前仓库只完成了协议和工具；尚未产生最终盲测结果。

## 核心不变量

1. `public_manifest.json` 只能包含源码绑定、上下文、候选变换和验证计划，不能包含标签、预期结果或安全暗示。
2. `private_oracle.json` 由未参与 analyzer 开发的人保管，不进入开发分支，不发给运行者。
3. 标注完成后先发布加盐哈希承诺。运行者只拿到公开 manifest 和 commitment。
4. analyzer、runner、adapters、阈值、公开 manifest 全部封存后，只执行一次正式预测。
5. 预测 JSON 的哈希和时间戳冻结后，才由保管人公开 private oracle 并验证承诺。
6. 任何预测前接触标签、基于失败样例修代码或重新挑选样本，都使该版本失去 final-blind 身份。
7. dynamic probe plan 和 workload-to-horizon derivation 也属于 runner 的冻结部分，不能在看到 unit 或标签后调整。

## 目标构成

建议封存 60 个 unit，允许范围为 50–80：

- 至少 3 个框架、2 个应用领域；
- 至少 1 个框架完全不在 `contamination_registry.json`；
- 至少 20 个 `rewrite_validation` unit；
- 至少 6 个 `optimizer_workload` unit；
- 每个 unit 固定 40 位 commit SHA、源码文件、公开 symbol 和源码绑定哈希；
- 风险类型和安全/不安全比例只在 private oracle 中统计，不在公开包中泄漏。

这些是覆盖性下限，不是为了迎合模型能力而配平标签。候选应从预先写下的纳入/排除规则抽取；不能先看 analyzer 输出再决定保留什么。

## 文件与保管

- `public_manifest.template.json`：语料策展者填写，开发者和运行者可见。
- `private_oracle.template.json`：独立标注者填写，仅 oracle 保管人可见。
- `oracle_commitment.schema.json`：可公开的承诺格式，不包含标签统计。
- `annotation_guide.zh-CN.md`：逐 unit 标注规则。
- `adjudication_protocol.zh-CN.md`：复核、争议和独立性规则。
- `threat_model.zh-CN.md`：标签泄漏、污染和伪独立性的有效性威胁。
- `one_shot_run_checklist.zh-CN.md`：封存、运行、解封顺序。
- `baseline_horizon_amendment.zh-CN.md`：评审后增加的动态基线、公平预算和 horizon 推导冻结规范。
- `baseline_horizon_protocol.v0.json`：当前 synthetic calibration 使用的机器可读协议；尚未冻结为 final runner。
- `h8c_r1_stateful_dynamic_protocol.json`：在已知 H8C workload 上核查公平动态基线的评审驱动协议；不是 final-blind 协议。
- `h8c_r2_novelty_falsification_protocol.json`：有限动态预算与 EffectV7-style source contract 的参数化 novelty stress test；不是跨框架证据。
- `experiments/autocontract_final_benchmark_admin.py`：校验、承诺、验证、封存工具。

## 管理命令

```powershell
python experiments/autocontract_final_benchmark_admin.py self-test `
  --output outputs/autocontract_final_handoff_selftest.json

python experiments/autocontract_final_benchmark_admin.py validate-public `
  benchmark/final_v1/public_manifest.json --strict

python experiments/autocontract_final_benchmark_admin.py commit-oracle `
  private/private_oracle.json `
  benchmark/final_v1/public_manifest.json `
  benchmark/final_v1/oracle_commitment.json

python experiments/autocontract_final_benchmark_admin.py verify-oracle `
  private/private_oracle.json `
  benchmark/final_v1/public_manifest.json `
  benchmark/final_v1/oracle_commitment.json
```

`seal` 只封存公开材料、runner 和 adapters 的 SHA-256；它不会读取 private oracle。正式预测工具也必须保持同样的隔离。

## 当前结论边界

H8C 说明 hybrid gate 在五个内部 CV/audio workload 上能保留两个安全机会并拒绝三个有收益但不安全的候选。它仍是已知源码、已知 oracle 的内部校准。只有本协议完成真实独立语料、独立标签和一次性运行后，才能支撑“对未见代码泛化”的主张。
