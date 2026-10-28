# codelotte v0.2.0 开发票据（Tickets）

> 由 v0.2.0 规划拆分的 **15 张票据**（01–15），按依赖顺序推进。
> 技术规格：[../SPEC.md](../SPEC.md) · 开发计划：[../PLAN.md](../PLAN.md)。
> 设计依据：ADR-[0010](../../../adr/0010-agent-service-and-job-model.md) – [0012](../../../adr/0012-kafka-for-jobs-and-events.md)；术语以 [CONTEXT.md](../../../../CONTEXT.md) 为准。
> v0.1.x 的 22 张票据已归档到 [docs/dev/v1/tickets/](../../v1/tickets/README.md)；
> v0.3.0（MCP / Skill）票据在 [docs/dev/v3/tickets/](../../v3/tickets/README.md)。
> 交付原则：**全部完成并跑出数据后才对外使用**；半成品不写简历、不进面试材料。

## 依赖层级（每层内可并行）

| 层 | 票据 |
|---|---|
| 1 | 01 |
| 2 | 02（←01） |
| 3 | 03（←02） |
| 4 | 04 · 05 · 07 · 08（←03） |
| 5 | 06（←05）· 09（←08） |
| 6 | 10 · 11（←09） |
| 7 | 12（←10,11）· 15（←11） |
| 8 | 13（←12） |
| 9 | 14（←13,15） |

## 票据列表

| # | 标题 | Blocked by | 状态 |
|---|---|---|---|
| [01](01-deploy-foundation.md) | 部署地基（compose + schema + 连接层） | None | done |
| [02](02-serve-skeleton.md) | serve 骨架（API + worker + 优雅关闭） | 01 | ready-for-agent |
| [03](03-users-and-auth.md) | 用户与鉴权（API Key + 缓存） | 02 | ready-for-agent |
| [04](04-rate-limit-and-quota.md) | 限流与配额（lab 01 + lab 05） | 03 | ready-for-agent |
| [05](05-cache-problems.md) | 缓存三大问题（lab 02） | 03 | ready-for-agent |
| [06](06-cache-consistency.md) | 缓存一致性（lab 03） | 05 | ready-for-agent |
| [07](07-distributed-lock.md) | 分布式锁（lab 04） | 03 | ready-for-agent |
| [08](08-job-queue.md) | 任务队列（lab 06） | 02 | ready-for-agent |
| [09](09-consumer-semantics.md) | 消费语义与幂等（lab 07） | 08 | ready-for-agent |
| [10](10-backpressure-and-burst.md) | 削峰与背压（lab 08） | 09 | ready-for-agent |
| [11](11-event-bus-and-aggregation.md) | 事件总线与异步汇总 | 09 | ready-for-agent |
| [12](12-observability-and-faults.md) | 可观测性与故障注入 | 10, 11 | ready-for-agent |
| [13](13-load-test-and-report.md) | 压测与实验报告 | 12 | ready-for-agent |
| [14](14-release.md) | v0.2.0 发布收口 | 13, 15 | ready-for-agent |
| [15](15-clients-and-demo.md) | 客户端与演示（远程 CLI + 单页 HTML） | 11 | ready-for-agent |

## 使用方式

- **认领**：挑一张「所有 Blocked by 都已完成」的票据，按验收标准实现；完成后勾选验收项并更新本表状态。
- **顺序纪律**：依赖表即施工顺序；跳过阻塞边会返工。
- **证据纪律**：带 lab 的票据，`results.json` 缺失即视为未完成。
- **内核纪律**：每张票据完成时检查 `git diff --stat src/codelotte/*.py`，除新增 `serve/` 外必须为空。
- **术语**：以 [CONTEXT.md](../../../../CONTEXT.md) 为准；设计约束见 ADR-0010–0012。
