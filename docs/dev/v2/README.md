# v0.2.0 开发资料：服务化与中间件

> 状态：计划中（2026-10-28 立项）。票据 01–15 已拆解，`ready-for-agent`。
> v0.1.x 归档在 [../v1/](../v1/README.md)；原 v0.2.0（MCP / Skill / 权限 v2）顺延到 [../v3/](../v3/README.md)。

## 目标

把 codelotte 从「本地单人 CLI」扩展出第三种运行形态 `codelotte serve`：多用户、多实例的
Agent 后端服务。在这个形态里落地三样此前没有的东西——**Redis 缓存与配额、Kafka 消息队列、
PostgreSQL 持久化**——并为每一项产出可复现的实验数据。

这条线的本质不是「加中间件」，而是**造出一个真实存在并发与故障的执行面**，让缓存一致性、
限流、队列削峰、幂等消费这些问题有地方发生。

## 入口

| 文档 | 内容 |
|---|---|
| [SPEC.md](SPEC.md) | v0.2.0 技术规格：服务形态、数据模型、缓存策略、消息语义、测试决策 |
| [PLAN.md](PLAN.md) | 施工顺序、阶段划分、工时预算、风险与交付原则 |
| [tickets/](tickets/README.md) | v0.2.0 票据、依赖层级与验收标准 |
| [ROADMAP.md](ROADMAP.md) | 占位；v0.2.0 完成后补齐 |

## ADR

| # | 决策 | 状态 |
|---|---|---|
| [0010](../../adr/0010-agent-service-and-job-model.md) | Agent 服务化：serve 入口与全异步 job 模型 | accepted |
| [0011](../../adr/0011-data-ownership-and-cache-strategy.md) | 数据所有权：配额以 Redis 为主存，Session entries 留 JSONL | accepted |
| [0012](../../adr/0012-kafka-for-jobs-and-events.md) | Kafka 同时承担 Job 队列与事件总线 | accepted |

累计索引：[docs/adr/README.md](../../adr/README.md)。

## 两条不可动摇的边界

1. **内核不改。** `AgentLoop`、`SessionStore`、`Ledger`、四个工具、权限层、沙箱层的行为与
   接口不变；serve 只决定「谁调用它们」和「事件发到哪里」。CLI 仍然零中间件依赖。
2. **证据先于功能。** 每张票据的验收都包含一组可复现的对比数据（错误版本 vs 正确版本）。
   没有数据的场景不算完成——这条沿用 v1 的评测纪律。

## 与 v0.3.0 的关系

原 v0.2.0 的 MCP / Skill / 权限 v2 / 沙箱镜像计划原样顺延为 **v0.3.0**，票据与 ADR 不动，
入口在 [../v3/](../v3/README.md)。两条线互不阻塞：v0.3.0 的票据依赖的是 session/v2 与权限
模型，与 serve 层没有交集。
