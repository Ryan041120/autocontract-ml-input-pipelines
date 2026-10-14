> 2026-09-09 整理前的 CURRENT_STATE 全文快照。以下状态按过程追加，可能已被后续条目取代；最新状态见 [CURRENT_STATE](../../CURRENT_STATE.md)。

# AutoContract P5T — Current State

## 当前目标

在 DIV2K validation workload 上完成一次可信、可复现的 8-block fresh M0 benefit experiment；任何 partial child 都不得作为正式结果。

## 已完成内容

- 固定了 Python 3.11 / PyTorch CPU / Cedar / split / P5S 输入与哈希。
- B2 diagnostic 已完成，结论为 `no_failure_reproduced`。
- 已建立并测试完整的 8-block child/result/aggregate 执行路径、数据隔离、固定顺序、first-error stop、hash/log 与 write-once 结果发布。
- v13 控制链已冻结：
  - runner: `experiments/autocontract_p5t_attempt3_v13.py`
  - contracts: `experiments/autocontract_p5t_attempt3_contracts_v4.py`
  - generator: `experiments/autocontract_p5t_frozen_launcher_generator_v7.py`
  - result schema: `benchmark/final_v1/p5t_attempt3_result_v3.schema.json`
  - freeze-v7 SHA: `5a60e9edafabac303b1e91a5c0be225e6fa946a789aeb8ad590e18db9ac17f29`
  - launcher-v7 SHA: `d84b22137d9975e8bb0c0ec2ae846e0b3e1885197d522a787264c9c527a089d1`
  - execution-v7 SHA: `690858a7165e381b5a3e683ce0c1566fe14e641a998f11573e0f10c9b55307da`

## 已确认事实

- v11、v12 两次失败均发生在数据访问前，属于控制面授权错误。
- v13 的 ordinal 1 已真实执行 dataset/M0 并写出完整 child，但 parent 在 schema validation 阶段拒绝；尚无 stage 或 aggregate。
- v13 partial child 不是正式结果，禁止复用、汇总或报告其中的 performance 数值。
- 当前没有匹配的 runner/launcher 进程。
- 三个失败现场均保留，未 retry、未 recover、未 cleanup。

## 当前 Bug

`p5t_attempt3_result_v3.schema.json` 与生产者/Core 的真实 Windows telemetry 类型域不一致：

- `page_faults`、`process_read_bytes`、`process_write_bytes`：生产者允许非负整数或 unsupported 状态字符串；schema-v3 只允许整数。
- `ac_power`：生产者允许多种字符串状态；schema-v3 只允许 boolean 或单一 unsupported 值。
- battery 字段也应按 Core 的实际合同核对全部 null / unsupported / integer 分支。

内存中把 schema 联合类型改为与 Core 一致后，现有 ordinal-1 child 的 schema errors 为 0，完整 deep validator 通过；未发现篡改证据。

## 关键失败现场

- v11：lock SHA `38e8b15423e5a815b48b5535d8ba49abae65046d1716c1889879a1922b4d1dcb`；stderr SHA `a973f9e2c607967e17246c4df2db08034b71049864be95566fb932276f74f0e8`。
- v12：lock SHA `13d87defd005cbe56535e328b04ebf0101bdd4e6658b30bb8a5da2379f58b34b`；stderr SHA `15f5d71bd9d5892df14a3add8a669f5c572e007720783a2f73614dd944e1d1c7`。
- v13：lock SHA `84ff1d5cb47d33433a29980b93c492ac39d74d0f5d19af8b4b6ab706d6e36e0b`；ordinal-1 child SHA `caeec5786bed089c0117bcf4a27c6ef06872be4b79dfafd3418023975f7c5b06`；stderr SHA `c1aec810d23988710e4a9cfef97ff5cfe9ce8a96c26025fd6a6b767e5487c518`。

## 不可违反约束

- 不清理、覆盖或复用上述失败现场。
- 不把任何 partial child 当作正式结果，不读取或汇报其 performance 数值。
- 保持 train/validation/test 隔离；不得提前查看正式测试结果。
- 正式运行前固定随机种子、环境、代码、schema、配置及 hashes。
- 不再为非科研关键问题增加递归 closure / validator / review 层。
- 未经用户明确授权，不得再次执行正式实验或启动新的控制面版本。

## 最小修复结果（2026-08-11）

- 已新增 schema-v4，并与 Core 的 telemetry 类型域同步。
- 已新增薄重绑定 runner-v14 / contracts-v5 / generator-v8；使用独立 attempt3-v4 state namespace，拒绝复用 v13 partial。
- 五组针对性 schema/Core 测试、compile、no-data selftest（131 checks）及三个最小 smoke 均通过。
- 独立 Review：PASS；未发现会导致科研结论错误、数据泄漏、partial 误收、不可复现或正式执行明显错误的问题。
- 新 aggregate/lock/work/stage 仍不存在；尚未生成 freeze-v8、launcher-v8、execution-v8，尚未运行正式实验。

关键 SHA：

- runner-v14: `8459a97aabdef85a09b2b51b27498e8b3d1171048bae6cceb94f3cc3fbc85459`
- contracts-v5: `fa542b3f922aa635841bc4e9774ed18469e8a31cb18f60b7172275f44d7b82fe`
- generator-v8: `ce19251061f85a7f2ebb69cc117d0f6f38f82af3a303823dabcad4dcfc684f39`
- schema-v4: `0a4b5f0c81b61a2133f540c1262d8d096705468577f3467f041a833d8ad342da`

## 正式授权后的首次控制面尝试（2026-08-11）

- 用户已明确授权正式运行；预检及 runner-v14、contracts-v5、generator-v8、schema-v4、Core、protocol、split、fixed Python 的 8 项固定 SHA 均通过。
- 首个控制面命令在生成 freeze-v8 时以退出码 2 停止：`Attempt3Error:v14_missing`。
- 直接原因是 runner-v14 的 freeze 构建要求 canonical `outputs/autocontract_p5t_attempt3_v4_selftest_v14.json` 已存在；该门在 freeze 发布前触发。
- 同级 canonical no-data prerequisites 共缺少 5 个：v14 selftest、orchestration smoke-v6、launcher smoke-v6、Cedar smoke-v6、independent-review-v6。
- freeze-v8、launcher-v8、execution-v8、v4 aggregate/lock/work/stage 均未生成；正式 attempt 启动次数为 0；匹配 Python 进程为 0。
- 已按 first-error stop 停止；未 retry、未 recover、未 cleanup，未读取或报告任何 partial performance。
- v11、v12、v13 关键失败现场 SHA 复核不变。
- 独立审查结论：科研约束与 first-error stop 为 PASS；正式运行就绪性为 FAIL / BLOCKED。问题是执行编排跳过既定 prerequisite 发布链，不是 freeze 合同或 schema-v4 的新缺陷。

## 正式 fresh experiment 成功（2026-08-11）

- 用户已重新明确授权补齐既定 no-data prerequisites、闭合 v8 配置链并仅运行一次 fresh attempt。
- 5 个 canonical no-data prerequisites 均一次发布并验证通过：
  - v14 selftest（131 checks）SHA：`6573e001ef06edb95cd42bdc1e5f7c01c9af675ffc2a1e13a396453dd2218d7f`
  - orchestration smoke-v6 SHA：`b47d2f9820a552497f7ad4d7270c339ed584a8eeef47438d0ea49fa6b05c9bb2`
  - launcher smoke-v6 SHA：`0aab7d2fc18281a2368a3c64c61e86fc0e3809d2f7322b4a2c341e31a28ade87`
  - Cedar smoke-v6 SHA：`2275672baee9b5d6649095d4ba5b31a637ccf42f9164e794e80ac120b9822ae5`
  - independent-review-v6 SHA：`e76e602781304b993ed6dca1fc7cb0e3ae460b1ebad4b52383544736d27ca4cd`；结论为 `controls_closed_no_data`
- v8 配置链已闭合：
  - freeze-v8 SHA：`e2a53d1c57923c21482fa3b5c39d73c8f418b784cd87d68d5cae52d72a5d1e02`
  - launcher-v8 SHA：`c2e226e5ef85f93b3ee81de9e5fb5c3b8ad5802c4fe4dd7f282c7ad77827e910`
  - execution-v8 SHA：`892f9e1090ea60a141c9e012611c17b9b2057b9a78828aa4e40fd56315e2ad7c`
- 正式 launcher 调用记录为 1 次，退出码 0，运行约 498.7 秒；成功产生 canonical aggregate：
  - path：`outputs/autocontract_p5t_attempt3_v4_aggregate.json`
  - SHA：`8801942b31a08850c83e5694b6c52a3dcf3568754cbb2147543eafbf68cdf7c4`
- aggregate 已独立通过 canonical bytes、schema-v4、runner-v14 `validate_aggregate`、8 个 Core `validate_block`、child SHA/identity/auth binding、固定 schedule 和 split 隔离复核。
- `fresh_attempt_only=true`、`old_partial_aggregate=false`；v4 lock/work/stage 均已消失，匹配进程为 0。
- v11、v12、v13 关键失败现场 SHA 保持不变；未读取、复用或汇报 v13 partial performance。
- 独立成功审查：PASS；未发现明显回归、数据泄漏、旧 partial 误收或授权链不闭合问题。

正式 calibration-only symmetric points：

| Ordinal | Sequence | Cell | symmetric point |
|---:|:---:|---|---:|
| 1 | CAAC | mobilenetv3_crop224 | 0.8987305405 |
| 2 | CAAC | resnet18_crop448 | 0.9278660885 |
| 3 | CAAC | mobilenetv3_crop448 | 0.9033743360 |
| 4 | CAAC | resnet18_crop224 | 0.9242525766 |
| 5 | ACCA | resnet18_crop224 | 0.9313954509 |
| 6 | ACCA | mobilenetv3_crop448 | 0.8284326764 |
| 7 | ACCA | resnet18_crop448 | 1.0021457706 |
| 8 | ACCA | mobilenetv3_crop224 | 0.9408559487 |

## 结论边界

- 这是一次完整、fresh、8-block、CPU-warm、DIV2K validation calibration-only M0 experiment 的正式 canonical 结果。
- 8 个注册点中 7 个 authorized/control 墙钟几何均值比小于 1，1 个略高于 1；只允许逐点描述。
- aggregate 标记 `scientific_evidence=false`；禁止据此进行 pooling、CI、Go/No-Go 或总体稳定加速/统计显著性/泛化/因果/冷缓存/GPU/正式测试集性能声明。
- 文件系统可独立证明一个完整成功 attempt identity；“launcher 历史调用 1 次”由本轮保存的执行命令与退出码记录佐证。成功后 raw token/lock 原始字节按设计清除，只保留 8 个 child 中一致的 commitment/SHA。

## 当前停止状态

P5T attempt3-v4 正式 fresh experiment 已完成并通过独立审查。当前没有匹配进程或残留 v4 state；不得自动 rerun、recover 或启动新版本。后续仅可在上述 calibration-only 边界内做描述性分析；任何新实验仍需用户明确授权。未关机。

## P5U no-data 设计（2026-09-04）

- 已完成 P5U 瓶颈门控安全重排的 no-data 设计与静态协议；未访问数据、未运行 profiling/训练/benchmark/smoke/selftest/launcher，未生成实验结果。
- P5U 明确本科阶段定位、RQ1–RQ4、P5V 四 cell 单机 CPU-warm/worker=0/无 prefetch baseline-only profiling、`exposed_input_share >= 20%` 与 `predicted_gain_share >= 5%` 资格门、A/B/C/D 矩阵、两层安全评价及停止规则。
- P5V 固定每 cell 5 warm-up blocks + 20 measured blocks，报告 median/IQR/MAD；MAD/median > 10% 或环境/电源/温度门失败即 profile 无效并 first-error stop，不自动重跑、不删异常、不补 block。
- 下一步推进 P5V 前必须先解决有标签数据集与四类互斥 split 合同、并再次获得明确授权；任务级 non-inferiority margin 属于 P5W freeze 前 blocker，不是 P5V 前置条件。不得据此自动启动新实验。

## P5V 数据集与 split 静态设计（2026-09-09）

- 已在不访问数据的前提下选择 DTD r1.0.1、官方 partition 1、47 类 category 标签作为 P5V 主数据集；Oxford-IIIT Pet 仅保留为 fallback，未根据任何性能结果选库。
- 已固定四类用途：`train1` 每类经预注册 SHA-256 排序取 10 张作为 profile/calibration、余下 30 张作为 effect-evaluation；官方 `val1` 仅作 task-validation；官方 `test1` 全阶段禁止实验访问。
- 固定前缀为 RGB decode、shorter-edge Resize(512)、float32 scale 和 domain guard；只允许既有 `Normalize ↔ RandomCrop(no padding)` 关系进入可移动区段，crop 仍为 224/448，模型输出改为 47 类。
- 当前仍为 `design_only_no_data`：DTD 未下载/读取，实际 archive/file SHA、样本 manifest、runtime/Resize/batch/steps/environment freeze 均未闭合；未运行 profiling、训练或 benchmark，未生成新结果。
- 下一步只能在用户再次明确授权后取得并核验 DTD、实例化 write-once split manifest、完成最小 preflight；不得自动运行 P5V。P5T calibration points 仍不得参与 P5V 选择或推断。

## P5V 数据取得与 manifest attempt 0（2026-09-09）

- 用户已授权的范围仅为：下载/读取 DTD、核验 archive、实例化 split manifest 和最小环境 preflight；未授权 P5V profiling、训练或正式 benchmark。
- 官方 DTD r1.0.1 archive 已下载至 LocalAppData（不在 Git/OneDrive），大小 625,239,812 bytes；MD5 `fff73e5086ae6bdbea199a49dfb8a4c1` 与 torchvision 固定值一致，SHA-256 为 `e42855a52a4950a3b59612834602aa253914755c95b0cff9ead6d07395f8e205`；已解包。
- write-once manifest attempt 0 按预注册重复内容门 first-error stop：发现 4 个 content SHA-256 跨允许 split 重复，其中 2 个为 profile/effect、2 个为 effect/task-validation。输出 manifest 不存在；未自动 retry，未移动、替换或补样本，生成器未解析 `test1.txt`。
- P5T 固定 venv 的 `python.exe` bytes 与 SHA 未变，但其 `pyvenv.cfg` 指向的原 Microsoft Store Python 3.11 base executable 已不存在，当前不可启动；未修改历史 venv，也未采用 Anaconda Python 3.9 作为 P5V runtime。
- P5V profiling、训练、Cedar 和性能计时均未启动，未观察性能值或生成科学结果。
- 当前需要用户决定：建议保留 DTD，并在任何 fresh manifest 前预注册“跨 split 内容重复等价类全部隔离、不补样本”的 amendment；备选为放弃 DTD，改用此前声明的 Oxford-IIIT Pet fallback。runtime replacement 也需在后续静态前提中单独闭合。

## P5V DTD manifest attempt 1 成功（2026-09-09）

- 用户明确选择保留 DTD，并授权：预注册跨 split 完全重复内容的整组隔离规则、不移动/替换/补样本；新建 P5V 专用 Python 3.11 环境；只重新生成一次 manifest；暂不运行 profiling。
- duplicate-quarantine amendment 已在 fresh 数据重读前固定，SHA-256：`1ae35cf2f04b1822142485b942bf23c993861c0adc1ff14ad72cdc4cc92474ec`。
- 已在 LocalAppData 新建隔离 P5V runtime（Python 3.11.9，`system_site_packages=false`），未修改失效但保留的 P5T runtime，未修改系统 PATH 或系统 Python 注册。runtime environment manifest SHA-256：`b5dff03bbcb3843c64357e22ff34df8b612d8a06a2d9be10937b3c2340528322`。
- manifest fresh attempt 1 仅调用 1 次，退出码 0，未自动 retry。生成器 SHA-256：`893eaf49737734a836056c9402954780d1399707cf059c44e9aaa8c2b3c6912c`。
- 按 amendment 隔离 4 个跨 split content-SHA 等价类、共 8 条样本，全部来自 `dotted` 类；未移动、替换或补位。计数由 470/1410/1880 变为 profile-calibration 468、effect-evaluation 1406、task-validation 1878，总计 3752。
- write-once manifest：`benchmark/final_v1/p5v_dtd_split_manifest.json`，SHA-256：`6491cf0aaa7aa2da9cd06bc5ca31a4c68a999b95e47d8a90ac05155a630c61af`。复核确认路径与 split key 唯一、allowed splits 间无剩余 content-SHA 交叉、每个 split 仍含全部 47 类。
- 未读取 `test1`，未运行 profiling、训练、Cedar、模型构造或性能计时；`scientific_evidence=false`。本次授权已耗尽，后续 P5V profiling 或其他实验必须重新获得明确授权。
