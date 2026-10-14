# AutoContract H6–H7H 版本化证据清单

> 审计规则：禁止把下表跨 Effect 版本汇总成一个总准确率。各阶段的分析器、adapter、上下文和预测粒度不同；它们是方法演进证据，不是同一个冻结模型上的独立同分布测试集。

| 阶段 | 分析器 | 框架/语境 | 粒度 | 单元 | 主指标 | unsafe FA | safe recall | reason | coverage | gate |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| H6 | EffectV2 | MONAI + MMDetection + DALI | effect_cell | 12 | 76.1% | 2 | — | — | — | FAIL |
| H7B | EffectV3 | MONAI + MMDetection + DALI | operator_decision | 14 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | PASS |
| H7C | EffectV3 | TorchIO | operator_decision | 7 | 100.0% | 0 | 100.0% | 85.7% | 100.0% | FAIL |
| H7D | EffectV4 | TorchGeo | operator_decision | 5 | 80.0% | 0 | 75.0% | 80.0% | 80.0% | FAIL |
| H7E | EffectV4 | audiomentations | operator_decision | 7 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | PASS |
| H7F | EffectV5 | imgaug | operator_decision | 8 | 87.5% | 0 | 80.0% | 87.5% | 100.0% | PASS |
| H7G | EffectV6 | Albumentations | operator_decision | 8 | 87.5% | 1 | 100.0% | 87.5% | 100.0% | FAIL |
| H7H | EffectV7 | Kornia | operator_context_decision | 9 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | PASS |

## 审计结论

- 共登记 8 个版本化阶段：4 个通过各自预注册 gate，4 个失败。这里的通过数不能解释为总体成功率。
- 每一行都绑定 summary、detail、protocol 与 freeze 文件的 SHA-256；脚本重算 gate，并要求与原结果一致。
- H6 是 effect-cell 指标，H7B–H7H 是 operator/context decision 指标，二者不可直接比较。
- H7H 只支持 EffectV7 在 Kornia compatible-params/sample-vs-replay 语境下的小样本结论。

## 论文主结果仍缺什么

1. 用同一个冻结的 EffectV7.x 和统一 oracle schema，一次性评估跨框架的 final blind corpus。
2. H8C 已在 CV+audio 五个 cache workloads 上跑通统一 baselines：hybrid 2/2 safe、0/3 unsafe、100% pilot oracle benefit；仍缺独立 oracle 与真实 unseen corpus。
3. 在同一 corpus 上完成 static-only、dynamic-only、registry-only、hybrid 与 manual-hint ablation。
4. 由独立标注者或学长审计 oracle；当前 AI researcher 自标注只能算 pilot evidence。

## 可复现命令

```bash
python experiments/build_autocontract_evidence_inventory.py
```

Manifest policy: `forbidden`.
