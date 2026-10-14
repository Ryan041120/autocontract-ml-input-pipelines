# P4A：adapter burden 审计复盘

## 结论

P4A 按预注册协议审计开发期全部受污染框架，结果为 **5/6 gates、FAIL**。失败应保留，不能通过改轻量门槛或删去复杂框架修饰。

10 个受污染框架均被追踪：8 个有冻结 adapter，NVIDIA DALI 为 unsupported，torchvision 只作为开发示例、没有冻结 adapter。8 个 adapter 合计 1,286 semantic logical SLOC、87 binding-glue SLOC、53 条声明规则，对应 50 个 formal units；共享基础设施另有 79 logical SLOC。

预注册的“轻量”诊断同时要求规则密度和每 formal unit 语义 SLOC 不超过门槛。只有 MONAI、MMDetection、TorchIO、TorchGeo 通过，即 4/8=50%，低于 75% gate。audiomentations、imgaug、Albumentations 的框架动态语义和 callable/target/source binding 负担较重；Kornia 虽代码量不大，但规则密度为 1.6，同样没有通过。

## 可以写与不能写的主张

可以写：AutoContract 的框架语义并非零成本；复杂 adapter 的负担可被显式计量并作为部署条件报告。不能写：adapter 普遍轻量、自动化已经替代专家、显著减少标注时间。8/8 框架都没有在协议前记录 prospective onboarding time，因此人工时间替代主张为 `unsupported_no_prospective_measurement`。

若最终论文保留 RQ3，必须由独立人员在未见框架上前瞻记录：源码阅读、规则提出、实现、调试、oracle 标注和复核的 wall-clock 时间；同时记录失败/放弃框架，不能只报成功接入。

## 证据

- protocol SHA-256: `e0827d7598bc416c9930f0630e4de93607d141ae6c870f53ee0ad51b772585b1`
- runner SHA-256: `1a69cd0c3f494a7195d90547e35d614e06fe6c6b461ec413dfda9805d08c54c1`
- result SHA-256: `0b20fe7fc5fd7c8beb27e5946b657ecee612b788cb02cb1c415a82b3d1fb4d9a`

结果路径：`outputs/autocontract_p4a_adapter_burden.json`。
