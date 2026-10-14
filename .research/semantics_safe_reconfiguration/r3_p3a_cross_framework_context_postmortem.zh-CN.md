# R3-P3a：cross-framework context compatibility 复盘

日期：2026-07-30
证据等级：已知 H7C/H7F/H7G 语料上的 posthoc transfer calibration；不是 blind holdout

## 1. 先解决“哪些结果可以放进同一分母”

旧 H7 材料对应的 operation 并不相同：

| Framework | 冻结上下文 | 与 replay_apply 是否可比 | 处理 |
|---|---|---|---|
| TorchIO H7C | legacy `sample_apply` | 否；没有冻结 stored replay evidence 或 replay phase | 7 个单元全部记 `unsupported_context` |
| imgaug H7F | `imgaug.deterministic` / `replay_apply` | 是；框架保证 per-call RNG state restoration | 8 个单元进入分母 |
| Albumentations H7G | stored params / `replay_apply` | 是；parameter-record replay | 8 个单元进入分母 |

把 TorchIO 的 Random* `sample_apply` 接纳与 replay units 混为一个准确率，会把不同研究问题伪装成跨框架证据。P3A 因此先冻结 context-compatibility gate，再运行预测。

协议 SHA-256：`f4afd13108cfb75c420cbd54c87ffbc3a96a00d3c4d9f19516be910c18c809fa`
runner SHA-256：`2fbef890be89cac08eed83dbb807a8e190f12160a6c981cb09a06b66f9c538ab`
result JSON SHA-256：`b9986a154a653e7242e09554e9527af1571d2690b9fccbe702cae51ecee0f74c`

Albumentations `HistogramMatching` 使用 H7G 后、R3 前已经建立的 phase-corrected oracle：replay/apply 中 public `read_fn` sampling helper 不可达，因此 expected=admit；record/sample 中仍应 reject。没有重新使用原来错误的 class-level reject 标签。

## 2. 冻结 EffectV7 的 zero-change transfer

| Framework | Units | Correct | Admit | Reject | Reason correct |
|---|---:|---:|---:|---:|---:|
| imgaug | 8 | 8 | 5 | 3 | 8 |
| Albumentations | 8 | 8 | 6 | 2 | 8 |
| 合计 | 16 | 16 | 11 | 5 | 16 |

统一混淆矩阵为 TP=11、FP=0、FN=0、TN=5；safe recall=100%，coarse reason accuracy=100%。本轮未修改 EffectV7 或旧 framework adapter，新增 effect/adapter rule=0；只增加 3 个显式 context-mapping entries。

这支持一个窄结论：`(configuration, phase, reachable path)` 表示能在两个不同 replay 家族——RNG-state restoration 与 parameter-record replay——上复用。不过这些单位与标签都已参与过旧研究，不能称为新的泛化准确率。

## 3. 首轮 10/11 FAIL 被保留

初次 runner 输出中，EffectV7 决策已经 16/16，但 static AST slice 只有 5/11 admitted units。原因是实现把限定方法名 `BasicTransform.__call__` 与裸 AST 名 `__call__` 直接比较，导致 6 个 Albumentations 单元形成空 slice。

修复没有添加语义规则，而是用 owner class + method name 解析限定标识符；修复后 11/11 admitted units 均生成 slice。该事件作为 identifier-resolution implementation bug 记录，不把首轮 FAIL 描述成一次性成功。

## 4. measured-source transfer 只完成了一半

11 个 admitted units 生成 63 个 reachable method AST records，共 11,029 bytes：

- imgaug：5 units、45 methods、6,779 bytes；
- Albumentations：6 units、18 methods、4,250 bytes。

但这些只是 `partial_static` artifact：它们绑定配置、phase、root source path 与 declared reachable method AST，不测量 defaults、closures、globals、native dependencies、实际 runtime origin 或 monkeypatch state。

冻结 Python 3.12 / PyTorch 2.4 环境中的 full P2b runtime measured-index readiness 为 0/2：

- imgaug vendored source 缺 `cv2` runtime dependency；
- Albumentations 缺 `pydantic` 与 `cv2`；
- TorchIO vendored corpus 本身是稀疏 source snapshot，不是完整可导入 package。

缺依赖全部记 Unsupported，没有用静态 AST 成功替代运行时证据。

## 5. 当前结论

可以支持：

> EffectV7 的 configuration/phase representation 在两个已知、语义可比的 replay families 上 zero-change transfer；其 reachable methods 可以生成 partial static measurement。

不能支持：

- P2b runtime source index 已经跨框架迁移；
- EffectV7 相对 strong greybox 具有新准确率增量；
- TorchIO H7C 是 replay 证据；
- 16/16 能外推到未见框架；
- partial AST slice 等价于 executable-source binding。

## 6. 下一步 R3-P3b

建立隔离、可复现的 runtime environment，而不是污染已冻结的主 PyTorch 环境：

1. 固定 Python、NumPy、OpenCV、Pydantic、imgaug 与 Albumentations dependency lock；
2. 从 vendored commits 导入框架并记录实际 module origins；
3. 先做最小 operator import/instantiate/replay smoke test；
4. 再将 P2b portable index 与 hot sentinel 接到每个 admitted unit；
5. 分别报告 runtime-supported、Unknown、native dependency 和 sentinel mutation coverage；
6. imgaug 与 Albumentations 任何新增 slot policy 必须进入 P3b-v1 burden，不能回写本轮 zero-change 结果。

如果隔离环境无法在不修改框架源码的情况下复现，P3b 应报告 runtime reproducibility no-go，而不是用 AST 结果代替。
