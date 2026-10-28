# 架构决策记录（ADR）

> 一条决策一个文件，状态写在文件头的 `Status:` 行。新决策从 0010 起编号；
> 改变已接受的决定时新增一条，并在旧文末标注 `superseded by NNNN`，不改写历史。

| # | 决策 | 状态 | 日期 | 一句话后果 |
|---|---|---|---|---|
| [0001](0001-portfolio-positioning.md) | 定位为「可验证的 harness 工程」（实验报告形态） | accepted | 2026-10-13 | 深度押 D1 评测 / D2 安全 / D4 压缩 / D5 归因，用数据而不是功能清单交付 |
| [0002](0002-python-over-typescript.md) | Python 3.13 + uv，不跟 TypeScript | accepted | 2026-10-13 | 放弃 node 系 agent 生态，换熟练度与国内岗位覆盖率 |
| [0003](0003-session-model.md) | append-only JSONL 树 + 压缩即条目 | accepted | 2026-10-13 | 消息、工具调用、usage、压缩、分支同源；导出 / 评测 / 归因共用一份轨迹 |
| [0004](0004-self-built-llm-adapter.md) | 自研薄 adapter（httpx2 + 内联 SSE），不用 SDK / litellm | accepted（部分实现） | 2026-10-13 | 缓存命中与峰谷计价字段可见；已实现并实测 `openai-completions`，`anthropic-messages` 协议抽象预留、未实现 |
| [0005](0005-two-layer-execution-security.md) | 权限层与沙箱层相互独立 | accepted | 2026-10-13 | 审批弹窗不是安全边界；bash 默认进 Docker 长驻容器 |
| [0006](0006-mcp-integration-and-trust.md) | MCP 外部工具适配与项目信任 | accepted | 2026-10-20 | tools-only + stdio/Streamable HTTP + 官方 SDK；项目级 mcp.json 必须 trust，stdio server 在宿主机运行 |
| [0007](0007-permission-scopes-and-command-classes.md) | 权限：显式决策、命令类与会话规则 | accepted | 2026-10-20 | deny > 显式批准 > ask > allow；bash 按 segment/命令类匹配，文件工具按工作区路径范围；会话规则可重放 |
| [0008](0008-system-prompt-and-session-v2.md) | 系统提示词组装与 session/v2 | accepted | 2026-10-20 | prompt 请求时组装、不写消息树、与压缩摘要合并；写 v2、读 v1+v2，不重写历史 run |
| [0009](0009-skills-loading-and-invocation.md) | Skill：SKILL.md 渐进加载与显式调用 | accepted | 2026-10-20 | 不新增 skill 工具，正文用 read 加载；`/skill:<name>` 显式调用并把正文写入会话 |
| [0010](0010-agent-service-and-job-model.md) | Agent 服务化：serve 入口与全异步 job 模型 | accepted | 2026-10-28 | 新增 `codelotte serve`；run 提交成 Job 入队，worker 独立扩容；内核零改动 |
| [0011](0011-data-ownership-and-cache-strategy.md) | 数据所有权：配额以 Redis 为主存 | accepted | 2026-10-28 | 配额不能超支故缓存不当副本；Session entries 留 JSONL，元数据进 PG |
| [0012](0012-kafka-for-jobs-and-events.md) | Kafka 同时承担 Job 队列与事件总线 | accepted | 2026-10-28 | 选 Kafka 是为了可重放与分区保序；ack 语义靠手动提交 + 幂等 + DLQ 自补 |

## 如何新增

1. 复制任一 ADR 的结构：标题、`Status: proposed | accepted | superseded`、日期、正文
   （决策 + 理由 + 被否备选）。
2. 文件命名 `NNNN-kebab-title.md`，在上表加一行。
3. 被取代的旧 ADR 不改正文，只在状态行加 `superseded by NNNN`。
