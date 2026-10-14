# P5M relation-lemma boundary falsification：复盘

日期：2026-07-30
状态：11/11 PASS；known-version adversarial calibration，不是形式 soundness 或独立 final

## 1. 为什么需要 P5M

P5L 在已知 torchvision corpus 上把 strict coverage 从 0/28 提升到 10/28，但其中两个关系 lemma 是人工编写的 upstream semantic bridge。receipt 的 hash、SourceIndex 和 verifier closure 即使全部正确，也不能自动保证这座语义桥准确描述了 torchvision 的真实实现。

P5M 因此不增加新算子或 lemma，而是预注册三层证伪：域/配置外必须拒绝；域内边界执行必须保持 output、exception 和 RNG post-state；真实 cedar 必须在随机算子链发生换序后仍满足同一观测等价关系。

停止规则为：任何域外 unsafe accept 或域内 mismatch 都撤销受影响的 lemma version，并停止扩展 proof family。

## 2. 冻结与攻击矩阵

P5M byte-freeze P5L protocol、公共 schema、V2 producer/verifier、P5L runner 和 result。运行时仍为 Python 3.11.9、torch 2.0.1+cpu、torchvision 0.15.2+cpu，24 个 torchvision v2 Python 文件 tree digest 不变；cedar 固定在 clean commit `f062305fcdab196e871c5d09b4c82ab788b4da79`。

攻击矩阵包括：

- 15 个 input-domain/totality mutations：layout、channel、dtype、device、nonfinite、value range、shape type/range，以及 CenterCrop/RandomCrop 刚好越过 totality 前提；
- 13 个 operator type/config mutations：Normalize inplace/channel/std/nonfinite、Grayscale 输出通道、RandomCrop padding/size、CenterCrop size、非法 flip probability、Identity subclass 和 GaussianBlur；
- 18 个 admitted pair configurations，包括 flip `p=0/0.5/1`、crop 位于 domain 最小边界，以及 identity、Normalize、Grayscale 的两类 lemma；
- 4 个空间角点 × 6 个 seed × contiguous/non-contiguous CHW，共 864 次双序执行；
- 真实 cedar 随机链 `[Normalize, RandomCrop, Identity]`。

每次域内执行同时比较 exact tensor、definedness/exception，以及 Python、NumPy、torch 三套 RNG post-state。动态测试只用于寻找 lemma/implementation bridge 的反例，不能单独签发 receipt。

## 3. 结果

最终为 **11/11 PASS**：

- domain/totality mutations：0/15 admitted；
- operator type/config mutations：0/13 admitted；
- admitted metamorphic trials：864；mismatch：0；
- 两个 lemma、四个空间角点和两种 memory layout 均实际覆盖；
- 所有域内输出逐位相等，观测到的 `max_abs_delta=0.0`；
- 所有域内 Python/NumPy/torch RNG post-state 相同。

拒绝发生在正确的保守层：例如 `normalize_inplace_unsupported`、`normalize_channel_count_mismatch`、`normalize_zero_std`、`random_crop_padding_unsupported`、`spatial_selection_may_pad_or_fail_on_domain`、`grayscale_requires_three_output_channels` 或 `unsupported_operator_type`。非法 flip probability 在 torchvision 构造器自身即被拒绝。

## 4. 随机 cedar 链

无 receipt 的 fail-closed baseline：

- candidate count：1；
- path：`[3,2,1,0]`；
- 三个 operator 均 fixed。

三张 locally replayed V2 receipts 后：

- candidate count：6；
- cedar 选择 path `[3,0,1,2]`；
- 8 个输入全部输出逐位一致，`max_abs_delta=0.0`；
- execution 后 Python、NumPy、torch RNG digest 全部一致。

这比 P5L 的 deterministic chain 多验证了一项关键义务：换序没有改变 RandomCrop 为后续样本留下的随机流状态。

## 5. Proof 与 adapter burden

固定环境描述性测量：

| 指标 | 结果 |
|---|---:|
| receipt generation median | 80.526 ms |
| local verification median | 101.798 ms |
| canonical receipt size | 2,928 bytes |
| V2 module SLOC | 396 |
| semantic-adapter SLOC | 208 |

这些是 registration/control-plane calibration，不是 hot-path benchmark。结果不支持“证明适配普遍轻量”的主张，反而与 P4A 的 adapter-burden 负结果一致：即使只覆盖两个 lemma，人工语义桥也有可观代码与审计成本。

## 6. 可以和不能声称什么

可以声称：在固定版本、源码树、配置、声明输入域和 RNG context 下，两个 P5L lemma 经 28 个域外攻击和 864 个域内 metamorphic trials 后未发现 bridge counterexample；随机 cedar 链实际换序后保持 exact output 和 RNG post-state。

不能声称：

- 已形式验证 torchvision 实现；
- 864 次测试证明数学 soundness；
- input tensor 的 domain membership 已在生产热路径强制执行；
- 结论跨 torchvision 版本、device、dtype 或 native kernel；
- 已有独立 pair oracle 或未污染泛化证据；
- receipt overhead/adapter burden 很低；
- 已产生训练吞吐或模型指标收益。

特别是 input-domain digest 绑定的是声明；当前仍依赖上游 schema/registration 保证实际数据属于该域。P5M 只在域内构造样本进行验证，没有把逐样本 domain check 加入 cedar 热路径。

## 7. 路线决策

P5M 没有触发 lemma 撤销，因此 V2 可从“首次 coverage prototype”提升为“mutation-hardened known-version prototype”。但继续在 P5K 已知语料上增加 interpolation、blur 或 rounding lemma 的边际科学价值已经较低。

下一不可替代工作应是 P5N reorder-final handoff：

1. 冻结独立人员使用的 pair-selection 和 annotation guide；
2. 由未参与 P5K–P5M 调规则的人选择 20–40 个新 pair；
3. 两名标注者独立给出 Commutes / Noncommutes / Unknown，并生成 salted commitment；
4. 在 reveal 前运行 V1/V2 producer，记录 coverage、unsafe accepts、Unknown 和 prospective adapter time；
5. reveal 后只按冻结指标报告，不能继续调 lemma 再重跑。

如果暂时无法获得独立人员，下一轮只能准备并自测 handoff 工具，不能把内部 AI 角色扮演称为 independent blind。

## 8. 可复核产物

- protocol：`benchmark/final_v1/p5m_relation_boundary_falsification_protocol.json`
- runner：`experiments/autocontract_p5m_relation_boundary_falsification.py`
- result：`outputs/autocontract_p5m_relation_boundary_falsification.json`
- result SHA-256：`f244a33287d66902ff569d6fe94c2f7489120c1d0974f6468036954823edbec8`
