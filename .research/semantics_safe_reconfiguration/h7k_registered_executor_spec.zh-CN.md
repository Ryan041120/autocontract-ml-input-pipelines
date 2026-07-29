# H7K registered/owned replay executor 设计

日期：2026-07-29

## 目标

H7J 每次调用重复验证静态事实，随机配对中位开销约 25%。H7K 将静态 proof 移到注册阶段，同时保留每次调用真正依赖动态输入或可能被 operator 修改的检查。

## 可缓存检查

仅当 target 由 executor 私有持有且外部不能正常取得引用时，以下事实允许在注册时检查一次：

- certificate integrity；
- framework、framework version、repository commit；
- target operator graph 与 source certificate 的一致性；
- frozen EffectV7 leaf proof set；
- container child binding、顺序和 contract composition；
- private parameter snapshot digest；
- target pool 中每个 instance 的 operator graph。

## 每次调用必须保留

- caller 提供的 sample identity；
- input shape/dtype/layout schema；
- 从 private snapshot 创建独立 working copy；
- target lease，保证同一 target 同时只服务一个调用；
- apply 后 working params digest，防止 operator 内修改；
- 成功后才释放输出。

output digest 不影响 replay 安全，可通过 receipt level 控制：

- `minimal`：绑定 registration、certificate、sample、target slot 和 post-params digest；
- `audit`：在 minimal 基础上增加 output digest。

## Target pool

注册接口接收 factory，而不是外部构造好的 target。executor 创建并私有保存 N 个配置等价 instance；queue lease 负责并发调度。pool size=1 等价于 H7J 的单 target 串行锁，pool size>1 允许不同 worker 并发使用不同 target。

## 成功判据

1. H7J 全部安全/正确性测试保持通过。
2. wrong sample/schema 在 operator invocation 前拒绝。
3. 改配置 target、缺 leaf proof、错误 child composition 在注册阶段拒绝。
4. pool=4、4 worker、至少 100 次调用全部输出一致、RNG 不变、0 error。
5. `minimal` receipt 不含 output digest，`audit` receipt 含正确 digest。
6. 随机交错配对中 registered minimal 相对 H7J atomic 的中位调用时间下降。
7. 单独报告注册成本和 break-even；不把 proof generation 成本隐藏到调用期之外。
