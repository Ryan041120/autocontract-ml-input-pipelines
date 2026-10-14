# 项目整理记录

日期：2026-09-09。范围为导航、文档归档、汇报和辅助脚本迁移，没有启动 profiling、训练或实验。

## 迁移表

| 原路径 | 新位置或处理 |
|---|---|
| README.md 原长篇内容 | docs/history/README_before_organization_2026-09-09.md；根目录改为简明入口 |
| CURRENT_STATE.md 原过程记录 | docs/history/current_state_2026-09-09.md；根目录改为当前状态与约束 |
| cachew_pecan_optimization_research_memo.md | docs/background/cachew_pecan_选题备忘录.md |
| M202273722_AutoContract_论文对比审阅.md | docs/literature/NDP-DF论文与AutoContract对比.md |
| .research/semantics_safe_reconfiguration/m202273722_ndp_df_autocontract_p_series_review.zh-CN.md | 重复正文合并到上一项，原路径保留入口 |
| output/pdf/autocontract_暑假研究总结_给老师.pdf | reports/supervisor/2026暑假_AutoContract研究总结.pdf；二进制内容不变 |
| tmp/create_summer_summary_pdf.py | tools/build_summer_summary_pdf.py；同步调整输出路径 |

## 引用与保留

新增研究阶段、文献、汇报、工具与临时文件入口。历史 README 和备忘录的相对链接适配新位置；旧命令保留作历史记录。review/build_single_file_packet.ps1 改用历史 README，未重新打包，既有输出包保留。

根目录 `ignored` 是带协议、runner、manifest 哈希的 P5S smoke JSON；来源未充分确认，保留原位。临时论文文本和预览保留供回查。

experiments/、benchmark/、outputs/ 中 650 个非 __pycache__ 文件在整理前记录 SHA-256，整理后核对路径和内容，覆盖现存失败现场及忽略文件。第三方源码与 Git 子模块未迁移，外部 DTD 和 runtime 不在整理范围。

整理不改变 P5S No-Go、P5T calibration-only 和 P5V 暂不 profiling 的边界。

## 恢复方法

按迁移表反向移动并恢复相对引用即可。旧状态正文保存在历史快照，旧 README 叙述保存在历史页，合并的论文正文仍完整存在，没有永久删除独有研究内容。

## 验证

- 650 个受保护文件前后路径与 SHA-256 全部一致，未新增或删除其中的文件。
- 15 份入口及归档文档中的 84 个本地链接检查通过，无断链。
- 原 CURRENT_STATE 全文在历史快照中完整保留；论文正文与整理前完全一致，SHA-256 为 `7f60ae08d7f407137c82577d44dfd7b4055a0eb6db86ce8d364a5abf8a30f4fb`。
- 汇报 PDF 前后 SHA-256 一致：`2b7282201d0eb71381f7d66f043901d05010ebb5b3d2a017454322d9dd9cd365`。
- 汇报生成脚本通过 Python AST 语法检查，评审打包脚本通过 PowerShell Parser 检查；均未执行生成或打包。
- `git diff --check` 无报错；仓库含未跟踪文件，因此完整性结论依据上述直接文件核对，不以 Git 差异代替。
