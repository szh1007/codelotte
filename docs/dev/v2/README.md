# v0.2.0 开发资料

> 状态：计划中（2026-10-20 立项）。票据 01–11 已拆解，`ready-for-agent`。
> v1 归档在 [../v1/](../v1/README.md)。

## 目标

在 minimal core 上接入 MCP 与 Skill，补齐系统提示词、通用命令、专用沙箱镜像，并把权限审批升级为按作用域生效。

## 入口

| 文档 | 内容 |
|---|---|
| [SPEC.md](SPEC.md) | v0.2.0 技术规格、用户故事与测试决策 |
| [PLAN.md](PLAN.md) | 里程碑、工作拆解、发布门槛与风险 |
| [tickets/](tickets/README.md) | v0.2.0 票据、依赖层级与发布门槛 |
| [ROADMAP.md](ROADMAP.md) | 占位；v0.2.0 完成后补齐 |

## ADR

| # | 决策 | 状态 |
|---|---|---|
| [0006](../../adr/0006-mcp-integration-and-trust.md) | MCP 外部工具适配与项目信任 | accepted |
| [0007](../../adr/0007-permission-scopes-and-command-classes.md) | 权限显式决策、命令类与会话规则 | accepted |
| [0008](../../adr/0008-system-prompt-and-session-v2.md) | 系统提示词组装与 session/v2 | accepted |
| [0009](../../adr/0009-skills-loading-and-invocation.md) | Skill 渐进加载与显式调用 | accepted |

累计索引：[docs/adr/README.md](../../adr/README.md)。

> v0.2.0 的 SPEC / PLAN 随实现推进补在本目录；在补齐前，技术约束以 ADR-0006–0009 与票据验收项为准。
