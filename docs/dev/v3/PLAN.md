# codelotte v0.3.0 开发计划（PLAN）

> 状态：ready-for-agent ｜ 日期：2026-10-20
> 技术规格：[SPEC.md](SPEC.md) · 票据：[tickets/](tickets/README.md) · 决策：[ADR-0006](../../adr/0006-mcp-integration-and-trust.md) – [ADR-0009](../../adr/0009-skills-loading-and-invocation.md)
> v1 计划归档在 [../v1/PLAN.md](../v1/PLAN.md)；v0.3.0 的 ROADMAP 在开发完成后补齐。

## 一页速览

| 项 | 内容 |
|---|---|
| 是什么 | codelotte v0.3.0：在 minimal core 上接入 MCP 与 Skill，补齐 System Prompt、通用命令、专用沙箱镜像，并把权限升级为作用域模型 |
| 为什么现在做 | v0.1.1 的 harness 已经可测量；下一步的短板是扩展性（外部工具/技能）与日常可用性（命令/提示词/沙箱） |
| 成功标准 | 用户能在不修改内核的情况下接 MCP、按需加载 Skill；模型行为由 System Prompt 约束；权限能表达「命令类/路径范围/会话」；本地 git 可用；既有评测与回放不变量不破 |
| 非目标 | 多 agent、RAG、Web UI、多模态、网络白名单、远程 git、OAuth、MCP 非 tools 能力 |
| 技术栈 | Python 3.13 + Textual + Docker + 官方 Python `mcp` SDK；模型仍走自研 `openai-completions` |
| 版本 | 0.3.0；ROADMAP 延后到开发完成后补 |

## 起点（v0.1.1）

- 四工具 minimal core：`read` / `write` / `edit` / `bash`。
- append-only JSONL 会话树；压缩即 entry；fork / resume / HTML 导出。
- 权限层 + Docker 长驻容器（`python:3.13-slim`、`--network none`、工作区 RW 挂载）。
- 死循环三层防御；逐次成本记账；评测闭环（9 条正式任务 + judge + 归因 + 防御）。
- 无 System Prompt、无 slash command、无 MCP、无 Skill、沙箱无 git。
- v1 文档已归档到 [../v1/](../v1/README.md)；历史 run 不重写。

## 里程碑

不承诺日期；按依赖推进。每层内的票据可并行。

| 阶段 | 票据 | 交付 | 验收 |
|---|---|---|---|
| M0 基础设施 | 01 · 03 · 10 | session/v2 与兼容读取；权限模型 v2；专用沙箱镜像 + git | v1 会话可读/可 resume；权限优先级与重放测试绿；镜像内本地 git 可用 |
| M1 提示词与匹配 | 02 · 04 | System Prompt + 项目指令；命令类/路径范围/审批弹层 | live/resume 前缀一致；压缩合并为单 system；`git status` 不覆盖 `git push` |
| M2 命令与 MCP | 05 · 06 | Slash Command + 核心命令；MCP core | `/model`/`/effort` 跨 resume；MCP fake server 端到端；默认 ask |
| M3 UX 与 Skill | 07 · 08 | MCP 运行时 UX；Skill 加载与自动匹配 | `/mcp` 状态；list_changed 在 run 边界；技能清单与预算 |
| M4 显式技能与发布 | 09 · 11 | `/skill:<name>` + `/skills`；发布收口 | 技能正文回放一致；9 任务 ×3 重跑；MCP/Skill 最小 eval |

## 工作拆解

| # | 票据 | 主要交付 |
|---|---|---|
| 01 | session/v2 与兼容读取 | 写 v2、读 v1+v2、schemaUpgraded marker、兼容测试 |
| 02 | 系统提示词组装 + 项目指令 | 唯一组装函数、单条 system、Prompt Version、AGENTS/CLAUDE trust |
| 03 | 权限模型 v2 | 五档决策、优先级、会话规则重放、glob 转义修复 |
| 04 | 命令类匹配、路径作用域与审批弹层 | shell 分段/命令类、文件路径范围、五档弹层 + 反馈 |
| 05 | Slash Command + 核心命令 | parser、`/model` `/effort` `/context` `/clear` `/compact` `/permissions` |
| 06 | MCP core | 配置/信任、SDK 客户端、工具适配、命名、默认 ask |
| 07 | MCP 运行时 UX | `/mcp`、`list_changed`、重连、导出标记 |
| 08 | Skill 加载与自动匹配 | 目录发现、frontmatter、清单预算、read 加载、trust |
| 09 | Skill 显式调用与 `/skills` | `/skill:`、skill entry、回放、`/skills` reload |
| 10 | 专用沙箱镜像 + git | Dockerfile、git 配置、非 root、GHCR、CI Docker 测试 |
| 11 | v0.3.0 发布收口 | 重跑评测、最小 eval、文档/CHANGELOG、tag、镜像发布 |

## 发布门槛（DoD）

1. 每张票据的验收项全部勾选；单测 + 至少 1 条集成测试。
2. `session/v2` 兼容测试：v1 读取/导出/resume/fork；历史 `evals/runs/**` 零改动。
3. 9 条正式任务 ×3 重跑并更新 README/面试数据表，标注 v0.3.0。
4. MCP 工具调用、Skill 自动加载、Skill 显式调用各至少 1 条最小 eval。
5. E1/E2/E5 不重跑；README 明确写「v0.1.1 结论，v0.3.0 未复测」。
6. CHANGELOG 0.3.0、README 功能/命令/配置、SECURITY、SPEC、quickstart 同步。
7. `ruff`、`pyright`、全量测试绿；Docker 集成测试在 Linux CI 绿。
8. 打 tag `0.3.0`，发布 GHCR 镜像；发布说明列出已知限制。

## 证据计划

- **正式任务集**：9 条任务 ×3，记录成功率、pass^3、成本、耗时、缓存命中。
- **MCP 最小 eval**：一条任务要求调用本地 fake MCP server 的工具；验证工具发现、审批、结果回传、审计。
- **Skill 最小 eval**：自动匹配一条（description 触发 `read`），显式调用一条（`/skill:`）；验证正文进入上下文、回放一致。
- **上下文成本**：记录 System Prompt + 技能清单 + MCP schema 的固定 token 开销；用 `/context` 的 `est.` 分项展示。
- **不重跑**：E1/E2/E5 的矩阵；保留 v0.1.1 报表并在文首标注版本边界。
- **诚实口径**：新增数字与旧数字分开标注；不把 v0.1.1 的成本/成功率写成 v0.3.0 的结果。

## 风险与应对

| 风险 | 应对 |
|---|---|
| MCP server 在宿主机执行任意代码 | 项目级配置必须 trust；用户级默认信任；审批显示 server；文档明确边界 |
| 命令分段/命令类解析被绕过 | 词法分段 + 无法解析即 ask + 危险 flag 强制 ask；≥20 形态对抗测试 |
| System Prompt 破坏 live/resume 前缀 | 唯一组装函数；compaction 合并单 system；逐字节前缀测试；请求指纹纳入 system |
| 显式批准被 ask 规则压住 | 新优先级 `deny > 显式批准 > ask > allow`；专项矩阵测试 |
| v1 会话兼容 | 读 v1+v2；resume 时写 schemaUpgraded marker；不重写历史 run |
| 沙箱镜像体积/构建时间 | 只装约定工具；GHCR 缓存；CI build 不 push；Docker 测试单独 marker |
| 技能正文过大 | Level 1 预算 8k tokens / 100 技能；超出截断告警；`/context` 可见 |
| 范围膨胀 | 砍单线：镜像额外运行时 → 项目级 MCP/Skill → 非核心命令；MCP core、权限 v2、显式 Skill 不砍 |

## 砍单线

按以下顺序收缩，先砍后面的：

1. 镜像中的额外语言运行时（Go/Rust 本就不在范围内）。
2. 项目级 MCP / Skill 配置（保留系统级主路径）。
3. 非核心命令（`/permissions`、`/help` 可最后补）。
4. **不砍**：MCP core、权限 v2、System Prompt、Skill 显式调用（模块的主要动机）。

## 文档与变更控制

- 本目录：SPEC / PLAN / ROADMAP（占位）/ tickets / ADR 入口。
- v1 文档冻结在 [../v1/](../v1/README.md)，不再更新。
- 新决策先写 ADR；推翻旧决策时新增 ADR 并标注 superseded。
- 术语变更同步 `CONTEXT.md`；票据表状态随实现更新。
- 发布后补 ROADMAP（当前状态、下一步、明确不做、优先级规则）。

## 面试映射

| 能力 | 可讲的技术点 |
|---|---|
| MCP | 协议面选择、官方 SDK 与自研取舍、项目 trust、生命周期、工具命名 |
| Skill | 渐进加载、`read` 复用、显式调用、正文写入会话保证回放 |
| System Prompt | 请求时组装、与压缩/缓存/指纹的交互、项目指令 trust |
| 权限 v2 | shell 分段与命令类、路径范围、会话规则重放、反馈语义 |
| 沙箱镜像 | 可复现镜像、git 身份、非 root、供应链与 CI |
| 命令与 TUI | 会话状态切换、模型/effort 事件、上下文可见性 |
| 评测 | 重跑与不重跑的边界、最小 eval、数字诚实 |

## 当前状态与下一步

- 状态：文档与票据已完成；实现未开始。
- 下一步（层 1，可并行）：**01 session/v2**、**03 权限模型 v2**、**10 沙箱镜像**。
- 推荐先做 01：它最小，且解锁 02 / 05 / 08。
