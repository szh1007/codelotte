# Skill：SKILL.md 渐进加载与显式调用

Status: accepted (2026-10-20)

Skill 是上下文扩展，不是新工具：

- 格式：一个技能一个目录，目录名即技能名，入口 `SKILL.md`；frontmatter 必须有 `name`（与目录一致）与 `description`，未知字段忽略。
- 位置：`~/.codelotte/skills/`、项目 `.codelotte/skills/`（需 trust）、`~/.agents/skills/`、项目 `.agents/skills/`（需 trust）。同名按「项目 > 用户 > agents」覆盖并告警。
- 渐进加载：Level 1 只把 name/description/location 放进系统提示词（有 token 预算）；Level 2 模型用现有 `read` 工具读取 SKILL.md 正文；Level 3 正文引用的资源按需读取。不新增 `skill` 工具。
- 会话启动时快照清单；`/skills reload` 在 run 边界刷新并追加 prompt event。
- 显式调用：`/skill:<name> [args]`。调用时读取正文，拼成一条 user 消息（`<skill name location>正文</skill>` + 参数），并写一条 `skill` entry（name/location/contentHash/args/content）；replay 时还原为同一消息，保证文件被修改后历史仍可回放。
- `disable-model-invocation: true`：不进入系统提示词清单，只能显式调用。
- `allowed-tools` / `license` / `compatibility` / `metadata` 解析但忽略；权限层始终是唯一权威。
- `name`/`description` 缺失或与目录不一致：启动告警并跳过，`/skills` 标记 invalid。

理由：

- Agent Skills 的 SKILL.md 约定已跨 agent 生态（pi、Claude Code）；兼容它能直接复用现有技能。
- 不新增工具，符合 minimal core，并避免工具 schema 膨胀。
- 显式调用是技能模块的主要使用场景；`/skill:` 命名空间避免与内建命令冲突。
- 把正文写入会话记录，才能满足「resume 前缀逐字节一致」的回放不变量。
- 技能正文是来自磁盘的指令，不是系统指令；权限层不应因技能加载而放宽。

被否备选：

- 专用 `skill(name)` 工具（多一个工具、多一套权限语义）。
- 扫描 `.claude/skills`（跨 agent 目录用 `.agents/skills` 更中立）。
- 支持 standalone `.md`（目录模型更简单、冲突更少）。
- `/<name>` 作为调用语法（与内建命令抢命名空间）。
- 只在调用时读文件、不做记录（文件变化后回放漂移）。

后果：

- 技能正文计入上下文与成本；大技能需要预算与 `/context` 可见性。
- `/skill:` 成为保留前缀；技能名不能含 `:`。
