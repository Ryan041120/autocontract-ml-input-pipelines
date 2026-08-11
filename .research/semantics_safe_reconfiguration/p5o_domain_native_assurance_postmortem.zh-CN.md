# P5O：Domain / Native Assurance 与 final-v3 协议修订

日期：2026-08-01
状态：21/21 PASS
结果：`outputs/autocontract_p5o_domain_native_assurance.json`
结果 SHA-256：`c46bcdcfca3901bce8145866eda0d1e9d7cd66cef236685bde968df3f578bf46`

## 1. 这轮回答什么问题

外部三评审共同指出两条尚未闭合的前提：receipt 绑定了声明 input domain，但没有保证运行样本属于该域；SourceIndexV1 绑定 Python 层，却不能被表述成完整 C++/CUDA/native kernel attestation。P5O 不接触未来独立 final pair/oracle，而是在冻结 P5L/P5M/P5N 的前提下回答：

1. 当前两个 ReorderCapabilityV2 lemma 到底使用哪些 domain 字段；
2. registration、batch-boundary 和 per-sample guard 分别能发现什么；
3. pure Python、known-versioned native 和 opaque native 如何 fail closed；
4. final 协议如何显式记录 pair family、RNG、definedness、exception、observational relation、domain assurance 与 native boundary。

## 2. 冻结与新产物

P5O byte-check 了 V2 producer、SourceIndexV1、final-v2 三套 schema、P5M result 和 P5N result，七项 hash 全部保持不变。旧 V2 没有被改写，因此 P5L/P5M 的 verifier closure 与结果仍可复核。

新增：

- `benchmark/final_v1/p5o_domain_native_assurance_protocol.json`；
- `experiments/autocontract_p5o_domain_native_assurance.py`；
- `benchmark/final_v3/` 下 public/private/prediction schema 与 templates；
- `benchmark/final_v3/P5O_WORKSHEET.zh-CN.md`；
- `outputs/autocontract_p5o_domain_native_assurance.json`。

固定执行环境为 Python 3.11.9、torch 2.0.1+cpu、torchvision 0.15.2+cpu。P5N 同环境回归仍为 30/30 PASS，结果与原 SHA-256 `e48438d1ad1802781b184b6120eec97d6656e22940f9d919b5bf0c774754202f` 一致。

## 3. Premise-use audit

直接审计 `_ensure_total_on_domain` 与 `_select_lemma` 后，lemma 逻辑读取的 domain 字段只有 `height_min` 和 `width_min`，用于保证 spatial selection 不 padding/不失败。`type/layout/channels/dtype/device` 是当前固定实现切片的 representation/runtime boundary；它们由入口验证，但不是关系代数公式中的数值前提。

`value_min`、`value_max`、`height_max`、`width_max`、`allow_nonfinite` 没有被当前两个 lemma 消费。它们可以继续绑定在旧 receipt 中维持 statement identity，但不能因为声明里出现了就默认在热路径扫描。未来 interpolation、rounding 或 finite-only lemma 若真正使用这些字段，必须发布新的 premise profile/verifier version。

## 4. Domain assurance 结果

在 8 个已知/合成 case 中注入 5 类运行时结构违例：首样本 dtype、后续样本 dtype、后续 channel、后续最小尺寸和后续 non-tensor。另加入超出声明 value range 与 NaN 两个非前提 case。

| 模式 | 结构违例检出 | False reject | 解释 |
|---|---:|---:|---|
| registration | 0/5 | 0 | 只验证声明，不能发现运行时替换 |
| representative list batch sentinel | 1/5 | 0 | 只看首样本，会漏掉 ragged/list 后续违例 |
| per-sample | 5/5 | 0 | 检查每个 sample 的七个实际 premise |
| uniform dense NCHW batch sentinel | 3/3 | 0 | dtype/channel/min-shape 是整批共享属性，可在 batch boundary 一次验证 |

因此 final-v3 的执行策略不是“一律逐元素扫描”：

- registration 只能作为控制面绑定，不能单独支撑运行时 Supported；
- uniform dense batch 可使用 batch-boundary structural guard；
- ragged/list 或可能逐样本变化的输入必须 per-sample；
- 当前 lemma 不扫描 value range 或 finite，因为它们不参与证明。

本机 200 次微基准的 median：registration 每次声明约 15.4 μs；16-sample list 首样本 sentinel 约 2.8 μs；uniform dense batch sentinel 约 6.5 μs；16 个 sample 全检约 38.4 μs，即约 2.4 μs/sample。P95 分别约 40.9、3.0、12.5、70.3 μs。这些数字只是当前 CPU/Python 微基准，不是预注册 overhead gate，也不能外推到训练吞吐。

## 5. Native boundary 结果

P5O 不再把“Python slots 可绑定”写成“整个执行栈纯 Python”：

- 本地 `pure_python_identity` 的 portable callable closure 完整，分类 `pure_python / allow_local_proof`；
- torchvision `Identity` 虽有完整 Python SourceIndex，实际执行仍依赖 torch/torchvision native runtime，分类 `known_versioned_native / allow_versioned_relation_only`，并绑定 Python、platform、torch/torchvision、CUDA/CXX ABI 和 torch config digest；
- builtin `len` 无可移植 code/source closure，分类 `opaque_native / force_unknown`。

该 runtime identity 仍不是 native binary/kernel 或硬件状态的完整 attestation。P5O 的 21 个检查包含攻击：opaque native 没有 external attestation 却输出 Supported 时拒绝；运行 premise violation 下 Supported 时拒绝；把 current exact lemma 偷换成 declared-tolerance relation 时拒绝。

## 6. final-v3 协议变化

Public manifest 新增：

- `evaluation_mode`，把 contaminated dry-run 与 independent final 分开；
- `pair_family` 与 RNG strata；
- input premise profile、assurance plan 和是否需要 value scan；
- 左右 operator 的 native boundary class、identity 和 strict policy；
- output/definedness/exception/RNG post-state 的显式 observational relation；
- family/RNG/Wilson/non-identity/cross-framework reporting plan。

Private oracle 把 output、definedness、exception 和 RNG post-state 分开标注；Noncommutes witness 必须指出 mismatch dimension。Prediction 记录 guard mode/检查次数/violations/overhead、native decision，以及 source inspection、guard implementation、adapter minutes 和 semantic-rule SLOC。

8-pair dry-run 覆盖七个 family、三种 RNG context 和两个 synthetic framework。其 unsafe/unresolved Supported 为 0、non-identity Supported 为 2、Supported framework count 为 2，但这些标签和 prediction 都由项目代码生成，`scientific_evidence=false`，只证明 schema/scorer/guard 路径能工作。

## 7. 结论与下一主线

P5O 修正了两种容易越界的说法：声明 domain 不是 runtime membership；Python source binding 不是 native stack attestation。当前最窄可靠结论是：对 current exact relation lemma，结构前提可以在 dense batch boundary 或 ragged per-sample 低成本检查；opaque native 无外部证明时严格 Unknown。

下一步不再扩 known-corpus relation family。内部可做的是把 final-v3 validator/worksheet 冻结成独立人员可执行包，并准备 prediction-seal 后的真实 cedar workload harness；真正 RQ1 数据仍必须由未参与 P5K–P5O 的 selector/annotators 产生。若没有外部角色，任何新的 8/8、21/21 都不能升级为 independent evidence。
