# codelotte v0.3.0 开发票据（Tickets）

> 由 v0.3.0 规划拆分的 **11 张票据**（01–11），按依赖顺序推进。
> 技术规格：[../SPEC.md](../SPEC.md) · 开发计划：[../PLAN.md](../PLAN.md)。
> 设计依据：[ADR-0006](../../../adr/0006-mcp-integration-and-trust.md) – [ADR-0009](../../../adr/0009-skills-loading-and-invocation.md)；术语以 [CONTEXT.md](../../../../CONTEXT.md) 为准。
> v1 的 22 张票据已归档到 [docs/dev/v1/tickets/](../../v1/tickets/README.md)。
> 发布门槛：每票验收 + 9 条正式任务 ×3 重跑（标注 v0.3.0）+ MCP/Skill 最小 eval + `session/v2` 兼容测试。
> E1/E2/E5 不重跑，README 保留「v0.1.1 结论，v0.3.0 未复测」。

## 依赖层级（每层内可并行）

| 层 | 票据 |
|---|---|
| 1 | 01 · 03 · 10（互不阻塞） |
| 2 | 02（←01）· 04（←03） |
| 3 | 05（←01,02,03）· 06（←03,04） |
| 4 | 07（←05,06）· 08（←01,02） |
| 5 | 09（←05,08） |
| 6 | 11（←02,04,05,07,09,10） |

## 票据列表

| # | 标题 | Blocked by | 状态 |
|---|---|---|---|
| [01](01-session-v2.md) | session/v2 与兼容读取 | None | ready-for-agent |
| [02](02-system-prompt.md) | 系统提示词组装 + 项目指令 | 01 | ready-for-agent |
| [03](03-permission-model-v2.md) | 权限模型 v2（决策、优先级、会话规则） | None | ready-for-agent |
| [04](04-command-classes-and-approval.md) | 命令类匹配、路径作用域与审批弹层 | 03 | ready-for-agent |
| [05](05-slash-commands.md) | Slash Command 基础设施 + 核心命令 | 01, 02, 03 | ready-for-agent |
| [06](06-mcp-core.md) | MCP core（配置、信任、工具接入） | 03, 04 | ready-for-agent |
| [07](07-mcp-runtime-ux.md) | MCP 运行时 UX | 05, 06 | ready-for-agent |
| [08](08-skills-loading.md) | Skill 加载与自动匹配 | 01, 02 | ready-for-agent |
| [09](09-skill-invocation.md) | Skill 显式调用与 /skills | 05, 08 | ready-for-agent |
| [10](10-sandbox-image.md) | codelotte 专用沙箱镜像 + git | None | ready-for-agent |
| [11](11-v030-release.md) | v0.3.0 发布收口 | 02, 04, 05, 07, 09, 10 | ready-for-agent |

## 使用方式

- **认领**：挑一张「所有 Blocked by 都已完成」的票据，按验收标准实现；完成后勾选验收项并更新本表状态。
- **顺序纪律**：依赖表即施工顺序；跳过阻塞边会返工。
- **术语**：以 [CONTEXT.md](../../../../CONTEXT.md) 为准；设计约束见 ADR-0006–0009。
