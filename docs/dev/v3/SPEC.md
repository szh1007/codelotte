# codelotte v0.3.0 技术规格（SPEC）

> 状态：ready-for-agent ｜ 日期：2026-10-20
> 对应票据：[tickets/](tickets/README.md) 01–11
> 设计依据：[ADR-0006](../../adr/0006-mcp-integration-and-trust.md) – [ADR-0009](../../adr/0009-skills-loading-and-invocation.md)
> 术语：[CONTEXT.md](../../../CONTEXT.md)；v1 规格归档在 [../v1/SPEC.md](../v1/SPEC.md)
> 本文描述 v0.3.0 的行为与接口契约；实现顺序与交付节奏见 [PLAN.md](PLAN.md)。ROADMAP 在 v0.3.0 完成后补齐。

## Problem Statement（问题陈述）

codelotte v0.1.1 已经有一个可测量的 minimal-core harness：四工具、append-only 会话树、双触发压缩、权限层 + Docker 沙箱、死循环防御和评测闭环。但它仍然是一个封闭的 agent：

- 外部工具（context7、firecrawl 等 MCP server）无法接入；每接一个工具都要改内核。
- 可复用的任务说明（Skill）没有载体；用户只能把长指令反复粘贴进对话。
- 没有 System Prompt 与项目指令加载；模型不知道 codelotte 的工具语义、沙箱边界、权限行为，也不知道仓库约定。
- 没有日常交互命令；切模型、切思考深度、看上下文、开新会话、手动压缩都要退出重开。
- 沙箱只有上游 `python:3.13-slim`；`bash` 里没有 git，也没有常用开发工具。
- 权限的「本会话允许」只对当前精确 subject 生效；无法表达「git status 这一类」、文件工具的工作区范围或 MCP 工具全名；「始终允许」可能被已有 ask 规则压住；没有「告诉模型换个做法」的入口。
- 如果把这些能力直接塞进内核，会破坏 minimal core 的边界，并威胁两条现有不变量：live/resume 请求前缀逐字节一致、Session 是唯一事实源。

v0.3.0 要解决的是：在不破坏这两条不变量的前提下，让 codelotte 具备扩展生态与日常可用性，并把权限模型提升到「作用域」级别。

## Solution（解决方案）

v0.3.0 增加六个能力，全部以 ADR 约束边界：

1. **MCP 适配**：tools-only；stdio + Streamable HTTP；官方 Python SDK；用户级/项目级 `mcp.json`；项目级必须 trust；工具名 `mcp__<server>__<tool>`；默认 ask；run 边界刷新。
2. **Skill**：`SKILL.md` 目录；渐进加载（元数据 → 正文 → 资源）；不新增工具，用 `read` 加载正文；`/skill:<name>` 显式调用；正文写入会话以保证回放。
3. **System Prompt**：请求时组装；不写入消息树；与压缩摘要合并为一条 system；项目指令 trust 门控；Prompt Version/hash 可追溯。
4. **Slash Commands**：`/model`、`/effort`、`/context`、`/clear`（`/new`）、`/compact`、`/help`、`/permissions`、`/mcp`、`/skills`；只在空闲时可用；未知命令不发给模型。
5. **专用沙箱镜像**：`python:3.13-slim` + git/常用开发工具/Node 22/uv；POSIX 非 root；仅保证本地 git；镜像版本化并进 CI。
6. **权限 v2**：五档决策；`deny > 显式批准 > ask > allow > 默认 ask`；命令分段与命令类；文件工具路径范围；会话规则重放；反馈不计熔断。
7. **Session v2**：写入 v2；读取 v1+v2；新 entry 类型只在 v2 产生；不迁移、不重写历史证据。

## User Stories（用户故事）

1. 作为 codelotte 用户，我希望在系统级 `mcp.json` 配置 MCP server，以便不修改内核就能使用 context7、firecrawl 等外部工具。
2. 作为 codelotte 用户，我希望项目级 MCP 配置在首次加载时要求确认，以便克隆一个陌生仓库不会直接在宿主机执行命令。
3. 作为 codelotte 用户，我希望 MCP 工具默认需要审批，以便外部工具不能未经同意就行动。
4. 作为 codelotte 用户，我希望用 `/mcp` 查看 server 状态、工具数与错误，以便排查连接问题。
5. 作为 codelotte 用户，我希望 MCP 工具使用 `mcp__<server>__<tool>` 命名，以便不同 server 与内建工具不重名。
6. 作为 codelotte 用户，我希望 MCP 工具列表变化只在下一个 run 生效，以便同一轮对话里模型看到的工具集保持稳定。
7. 作为 Skill 作者，我希望一个目录 + `SKILL.md` 就是一个技能，以便复用 Claude Code / pi 生态的现有技能。
8. 作为 codelotte 用户，我希望系统提示词里只出现技能的 name/description/location，以便技能正文不常驻上下文。
9. 作为 codelotte 用户，我希望模型用现有 `read` 工具加载技能正文，以便不为了技能新增一个工具。
10. 作为 codelotte 用户，我希望用 `/skill:<name>` 显式加载技能，以便在自动匹配不触发时强制使用。
11. 作为 codelotte 用户，我希望技能正文被写入会话记录，以便技能文件之后被修改时，历史会话仍能逐字节回放。
12. 作为 Skill 作者，我希望 `disable-model-invocation: true` 让技能不出现在自动清单里，但仍可显式调用。
13. 作为 codelotte 用户，我希望 `/skills` 查看已加载、无效与被遮蔽的技能，以便诊断技能目录问题。
14. 作为 codelotte 用户，我希望 `/skills reload` 在 run 边界刷新技能清单，以便新增技能不必重启进程。
15. 作为 codelotte 用户，我希望 System Prompt 解释 codelotte 的工具语义、沙箱边界与权限行为，以便模型少犯工具误用。
16. 作为 codelotte 用户，我希望 System Prompt 在每次请求时组装而不是写进消息树，以便压缩、fork、导出不被污染。
17. 作为 codelotte 用户，我希望压缩摘要与基础提示词合并为一条 system 消息，以便兼容不接受叠 system 的后端。
18. 作为 codelotte 用户，我希望项目 `AGENTS.md` / `CLAUDE.md` 只在项目被 trust 后加载，以便仓库指令不能静默注入。
19. 作为 codelotte 用户，我希望 resume 时发现 Prompt Version 变化会告警，以便知道本次行为可能与首次运行不同。
20. 作为 codelotte 用户，我希望 `/model` 切换当前会话的模型并在 resume/fork 后保持，以便不必每次重开。
21. 作为 codelotte 用户，我希望 `/effort` 切换思考深度并在 resume/fork 后保持，以便按任务难度控制成本。
22. 作为 codelotte 用户，我希望 `/context` 显示精确的 provider 总 token 与分项估算，以便知道离压缩阈值还有多远。
23. 作为 codelotte 用户，我希望 `/clear` / `/new` 开一个新会话，同时保留旧会话可导出，以便清空上下文但不丢记录。
24. 作为 codelotte 用户，我希望 `/compact` 可以强制压缩并附带关注点，以便在长任务中主动整理上下文。
25. 作为 codelotte 用户，我希望 `/permissions` 查看规则与来源，以便知道某类操作为什么被放行或询问。
26. 作为 codelotte 用户，我希望未知 `/xxx` 直接报错而不是发给模型，以便命令拼写错误不会变成一次真实请求。
27. 作为 codelotte 用户，我希望 slash command 只在空闲时可用，以便 run 进行中不会被状态切换打断。
28. 作为 codelotte 用户，我希望沙箱内置 git 与常用开发工具，以便 `bash` 能做版本控制与日常检查。
29. 作为 codelotte 用户，我希望沙箱镜像是固定版本、可本地重建、可从 GHCR 拉取，以便环境可复现。
30. 作为 codelotte 用户，我希望本地 git 使用沙箱身份且不读取宿主机凭据，以便提交可用但不泄露凭据。
31. 作为 Linux 用户，我希望容器以我的 UID/GID 运行，以便 `.git` 文件不被 root 拥有。
32. 作为 codelotte 用户，我希望远程 git 操作失败时给出明确原因，以便知道是 `--network none` 而不是 git 坏了。
33. 作为 codelotte 用户，我希望审批提供本次/本会话/始终/拒绝/手动输入五档，以便按风险选择合适的作用域。
34. 作为 codelotte 用户，我希望文件工具的「本会话允许」覆盖工作区路径范围，以便正常编辑不反复询问，同时越界仍询问。
35. 作为 codelotte 用户，我希望 bash 的「本会话允许」按命令类生效，以便允许 `git status` 后同类命令不再问。
36. 作为 codelotte 用户，我希望允许 `git status` 不会连带允许 `git push`，以便子命令之间的风险边界清楚。
37. 作为 codelotte 用户，我希望复合命令逐段检查，以便 `git status; rm -rf /` 不会因为第一段被允许而整体放行。
38. 作为 codelotte 用户，我希望包装器、命令替换、重定向等无法静态判定的形态重新询问，以便解析边界不能被绕过。
39. 作为 codelotte 用户，我希望危险 flag 永远重新询问，以便已允许的命令类不能执行 `git push --force`。
40. 作为 codelotte 用户，我希望显式批准覆盖 ask 规则但永远不能覆盖 deny，以便「始终允许」真的生效，同时保留硬拒绝。
41. 作为 codelotte 用户，我希望会话规则在 `--continue` / `--resume` 后仍然有效，以便「本会话」的含义与 session 文件一致。
42. 作为 codelotte 用户，我希望「手动输入建议」拒绝本次调用并把我的话回给模型，以便纠正方向而不重启 run。
43. 作为 codelotte 用户，我希望反馈不计入连续失败熔断，以便连续纠偏不会把 run 误终止。
44. 作为 codelotte 用户，我希望 MCP 工具的审批显示 server 名，以便识别同名仿冒。
45. 作为维护者，我希望 session/v2 能读 v1 会话且不重写历史评测记录，以便证据可复现。
46. 作为维护者，我希望新测试尽量走现有最高测试缝，以便验证行为而不是实现细节。
47. 作为面试官/评审者，我希望每个关键决策都有 ADR 与票据，以便解释「为什么这么做」。
48. 作为 CI 维护者，我希望沙箱镜像在 Linux runner 上构建并跑 Docker 集成测试，以便镜像不会腐烂。

## Implementation Decisions（实现决策）

### 版本与范围

- v0.3.0 只包含本规格列出的六项能力；新增范围必须先写 ADR 并更新票据。
- 实现顺序按依赖推进：基础设施（session v2 / 权限模型 / 沙箱镜像）→ System Prompt 与权限匹配 → 命令与 MCP → MCP UX 与 Skill 加载 → Skill 显式调用 → 发布收口。
- 发布门槛：每票验收 + 9 条正式任务 ×3 重跑 + MCP/Skill 最小 eval + `session/v2` 兼容测试；E1/E2/E5 不重跑，保留 v0.1.1 结论并标注。

### Session v2

- 新会话一律写 `session/v2`；读取器同时接受 v1 与 v2，不新增 schema 校验。
- v1 会话可读、可导出、可 resume/fork。v1 文件第一次追加 v2-only 内容前，写入一条 `event` entry，`kind=schemaUpgraded`，记录 `from=session/v1`、`to=session/v2`；之后按 v2 解释。原始 header 不改写；回放忽略该 marker。
- 新 entry/字段只在 v2 产生：`event/schemaUpgraded`、`skill`、`event/modelChanged`、`event/effortChanged`、`event/promptChanged`、`event/mcpToolsChanged`、`decision=feedback`。
- 不迁移、不重写 `evals/runs/**` 的历史会话，也不改 attribution/defense 的 v1 语料；读取器按「未知 entry 跳过」的现有规则处理。
- v1 会话导出标注 `v0.1.x`；v2 会话按当前格式导出。

### System Prompt

- 只有一个组装函数，live 与 resume 共用；section 顺序固定为：身份、工具规则、权限与沙箱约束、技能清单、项目指令、cwd。
- System Prompt 不是消息树 entry；Session 头记录 Prompt Version（版本 + hash），prompt 变化追加 `event/promptChanged`；resume 时 hash 不一致只告警。
- 压缩后的请求把「基础提示词 + 摘要 + 硬约束」合并为一条 system 消息；摘要、熔断等 `use_tools=False` 调用不注入基础提示词。
- 请求指纹纳入最终 system 内容；稳定 section 在前，动态 section 在后，保持缓存前缀稳定。
- 项目指令：`~/.codelotte/AGENTS.md` 始终加载；项目 `AGENTS.md` → `CLAUDE.md` 从 cwd 向上到仓库根，只有项目被 trust 后加载；不做 `SYSTEM.md` / `APPEND_SYSTEM.md` / override / 多级合并。
- 基础提示词按 pi 的结构改写，只描述 codelotte 真实存在的工具、沙箱与权限；若借用成段文字，在第三方声明中保留 MIT 全文与 `Copyright (c) 2025 Mario Zechner`。

### MCP

- 协议面只做 tools：`initialize`、`tools/list`、`tools/call`、`tools/list_changed`；不做 resources / prompts / sampling / elicitation；image/audio/resource 结果转占位文本。
- 传输只做 stdio 与 Streamable HTTP；旧版 HTTP+SSE 明确报错；OAuth 不做，HTTP 认证用静态 headers + `${VAR}` / `${VAR:-default}`。
- 客户端使用官方 Python `mcp` SDK，不自研 JSON-RPC 与传输层。
- 配置：`~/.codelotte/mcp.json` 与项目 `.codelotte/mcp.json`，使用 Claude Desktop 兼容的 `mcpServers`；同名项目覆盖用户级；坏 JSON/坏条目跳过并汇报。
- 信任：用户级配置视为已信任；项目级配置首次加载必须确认，内容 hash 变化后重新确认；stdio server 在宿主机运行。
- 生命周期：启动时并发连接并 `tools/list`，单 server 超时 10s、失败不阻塞会话；退出统一 kill；`list_changed` 只在 run 边界刷新并写 `event/mcpToolsChanged`。
- 工具名 `mcp__<server>__<tool>`；sanitize 非法字符；超过 provider 的 64 字符限制时截断并加短 hash；只做 direct exposure。
- 权限：所有 MCP 工具默认 ask；可按 server 配置 allow；审批弹层显示 server 名；MCP 工具描述来自外部，按不可信输入处理。

### Skill

- 一个技能一个目录，目录名即技能名；入口 `SKILL.md`；frontmatter 必须有 `name`（与目录一致）与 `description`，未知字段忽略。
- 位置：`~/.codelotte/skills/`、项目 `.codelotte/skills/`（需 trust）、`~/.agents/skills/`、项目 `.agents/skills/`（需 trust）。
- 同名冲突按「项目 > 用户 > agents」覆盖并告警；`name`/`description` 缺失或与目录不一致的技能启动告警并跳过。
- 渐进加载：Level 1 只把 name/description/location 放进系统提示词；默认预算 8k tokens / 100 个技能，超出按名称字母序截断并告警；Level 2 模型用现有 `read` 工具读取正文；Level 3 正文引用的资源按需读取。
- 不新增 `skill` 工具；技能正文是上下文，不是系统指令；技能里要求的工具调用仍走权限层。
- 会话启动时快照清单；`/skills reload` 在 run 边界刷新并追加 `event/promptChanged`。
- 显式调用：`/skill:<name> [args]`；调用时重新读取正文，拼成 `<skill name location>正文</skill> + 参数` 的 user 消息，并写一条 `skill` entry（name/location/contentHash/args/content）；回放还原同一消息。
- `disable-model-invocation: true`：不进入系统提示词清单，只能显式调用。
- `allowed-tools` / `license` / `compatibility` / `metadata` 解析但忽略；权限层始终是唯一权威。

### Slash Commands

- TUI 解析以 `/` 开头的输入；未知命令报错，不发给模型；命令只在空闲时可用。
- `/model`：无参选择器、带参切换；下一次 run 生效；写 `event/modelChanged`；resume/fork 重放最后一次；模型不存在时回退默认并告警；不写默认配置。
- `/effort`：接受 `none/minimal/low/medium/high/xhigh/max/ultra`；写 `event/effortChanged`；重放规则同 `/model`。
- `/context`：provider 报告的精确总 input tokens + 系统提示词/工具 schema/消息/技能清单/MCP 的分项估算（标 `est.`）+ 压缩阈值与使用率。
- `/clear`（别名 `/new`）：新建会话文件，清空 TUI 历史与 ledger，旧会话保留可 resume/export。
- `/compact [指令]`：即使低于阈值也强制压缩；可选关注点写入摘要请求；记录 `manual` 原因。
- `/help`、`/permissions`、`/mcp`、`/skills`：分别输出命令列表、规则与来源、server 状态、技能清单与 reload。
- 不做 `/undo`、`/rewind`、`/agents`、`/hooks`。

### Sandbox

- 专用镜像以 `python:3.13-slim` 为基础，预装 git、curl、wget、ca-certificates、ripgrep、fd-find、jq、yq、unzip、less、procps、build-essential、sqlite3、file、Node 22、uv；不装 Go/Rust。
- `/etc/gitconfig` 写入 codelotte 身份、`safe.directory /workspace`、`core.autocrlf=false`、`init.defaultBranch=main`；不挂载宿主机 git 凭据。
- POSIX 上容器以宿主 UID:GID 运行；Windows/Docker Desktop 保持默认。代价是运行期不能 `apt install`，工具全部预装。
- `settings.json` 新增 `sandbox.image`；提供 `codelotte sandbox build`；镜像发布到 GHCR，tag 绑定 codelotte 版本；CI 在 PR 上 build、tag 时 push，并在 Linux runner 跑 `-m docker`。
- 网络仍为 `--network none`；只保证本地 git（status/diff/log/add/commit/branch）；clone/fetch/pull/push 明确失败并提示 `--no-sandbox` 临时方案；网络白名单另立项。

### 权限

- 决策五档：once / session / always / deny / feedback。
- 优先级：deny 永远最高；显式批准（同 subject 的 session/always 规则）覆盖 ask；ask 覆盖 allow；无规则默认 ask。
- 「始终允许」继续写用户级 `~/.codelotte/permissions.json`，不写项目文件；弹层显示将写入的精确规则；修复 subject 含 glob 元字符时持久化未转义的 bug。
- 文件工具的会话放行按工作区路径范围：`/workspace/...` 映射到 cwd、相对路径解析、symlink `resolve()` 后判定；越界仍 ask。
- bash 按 shell segment 分段（`;`、`&&`、`||`、`|`、换行、命令替换、反引号）；每个 segment 取命令类（`argv[0]` + 非 flag 的 `argv[1]`），全部命中才放行；包装器、命令替换、重定向、全局 flag 位于子命令前等无法静态判定的形态一律 ask；危险 flag 永远重新询问。
- MCP 工具按 `mcp__<server>__<tool>` 全名放行；弹层显示 server 名。
- 会话规则在 resume/fork 时从 `permission` entry 中 `decision=session` 重放；不跨会话。
- 手动输入建议 = 拒绝该次调用 + 用户文本作为 tool error 回给模型 + run 继续；不计入连续失败熔断；普通拒绝仍计入。
- 一次模型回合的多个 tool call 逐条审批，不提供批量放行。

### 可观测性与兼容

- 所有判定、MCP 调用、命令切换、prompt 变化、schema 升级都写 entry；导出与 TUI 能显示。
- TUI 新增：审批弹层五档 + 输入框、命令输出、技能折叠块、MCP 状态。
- Session 格式、权限规则语法、MCP 配置结构的变化必须写 ADR；v1 归档文档不再更新。

## Testing Decisions（测试决策）

### 好的测试

- 只测外部行为：给定输入与注入的依赖，断言请求、会话记录、工具结果、用户可见输出；不断言私有函数或内部数据结构。
- 确定性优先：模型用 fake client，MCP 用本地 fake server，时间/成本字段做可控注入；默认测试离线。
- 一个测试验证一个行为；名称描述行为（如「允许 git status 不覆盖 git push」）。
- 对安全边界做对抗性参数化：复合命令、包装器、重定向、symlink、glob 元字符、trust 绕过。

### 测试缝

- **主缝（唯一首选）**：AgentLoop + 注入的模型客户端、工具元组、审批回调、执行器、Session store。System Prompt、权限判定、MCP 工具适配、Skill 注入、命令导致的 loop/session 变更都从这里验证。这是现有 roundtrip/loop 测试已经在用的缝。
- **UI 缝**：TUI pilot，验证审批弹层五档、命令解析、技能折叠块、MCP 状态输出。
- **沙箱缝**：DockerExecutor 的真实容器集成测试，标记 `docker`，默认排除，CI 在 Linux runner 跑；验证镜像、git、属主、网络提示。
- **回放缝**：Session store + `messages_from_entries`，验证 live/resume 逐字节一致、v1/v2 兼容、压缩合并、skill entry 回放。
- 不为 MCP 客户端内部再开新缝：fake server 在协议边界替换，仍通过主缝驱动。

### 测试模块与先例

- 权限矩阵/规则/信任：沿用现有 permission 单元与组件测试的参数化风格。
- TUI：沿用现有 Textual pilot 与快照测试。
- Session：沿用现有树/分支/确定性测试；新增 v1→v2 upgrade marker 与 v1 读取。
- Roundtrip：新增 system prompt 请求形状、压缩合并、命令切换、MCP 工具调用、skill 加载的端到端。
- Docker：沿用现有 `-m docker` 集成套件；新增镜像内 git 与属主测试。
- MCP：新增本地 stdio fake server 与本地 Streamable HTTP fake server；不依赖外网。
- Eval：新增 MCP 工具调用与 Skill 自动/显式加载的最小任务。

## Out of Scope（不在范围内）

- MCP resources / prompts / sampling / elicitation / OAuth / 旧版 HTTP+SSE。
- MCP codemode / deferred / hidden exposure；工具搜索。
- 扫描 `.claude/skills`；standalone `.md` 技能；技能市场、依赖解析、技能版本管理。
- `/undo`、`/rewind`、`/agents`、`/hooks`、模型选择的默认配置持久化（`/model --save`）。
- 网络白名单、远程 git、宿主机凭据挂载、Go/Rust 等额外镜像运行时。
- 多 agent 编排、RAG/代码库索引、Web UI/IDE 插件、多模态、`anthropic-messages` 适配器。
- E1/E2/E5 重跑；v1 归档文档的内容更新。
- v0.3.0 之后的路线图内容（ROADMAP 在开发完成后补）。

## Further Notes（补充说明）

- **安全边界**：项目 trust 是 MCP server 启动与项目指令/技能加载的边界；权限层只管工具调用；Docker 沙箱限制 bash 的实际后果。三层互不替代。
- **已知限制**：MCP stdio server 拥有宿主用户权限；远程 git 在 `--no-sandbox` 之前不可用；技能正文计入上下文与成本；跨版本 resume 的 prompt 可能变化（hash 告警）。
- **发布节奏**：票据 01/03/10 可并行；02/04 依赖基础；05/06 依赖提示词与权限；07/08 依赖命令与 MCP/提示词；09 最后接通显式技能；11 收口。
- **文档**：ADR-0006–0009、CONTEXT 术语、v1 归档、票据索引；ROADMAP 占位文件在 v0.3.0 完成后补齐。
- **变更控制**：实现中若发现需要推翻 ADR 的决定，新增 ADR 并在旧文末标注 superseded；不直接改历史决策。
