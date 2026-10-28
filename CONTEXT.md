# codelotte

codelotte 是一款终端 coding agent（harness），作为 Agent 开发岗的求职作品持续开发。本文件是本仓库的术语表：只收录本项目语境下有特定含义的词。

## Language

**codelotte**:
本作品的名字与系统整体——一个 minimal-core、可扩展的终端 coding agent。单独出现时指整个系统，不指某个模块。
_Avoid_: 项目（project，指仓库时除外）、产品（product）

**Harness**:
本项目语境下，指除模型之外的全部 agent 系统：循环、工具、会话、上下文管理、权限与沙箱。「同模型不同 harness」里的 harness 即此义；codelotte 的工程对象就是这个 harness。
_Avoid_: 框架（framework）、脚手架（scaffold，仅用于引用外部研究时）

**Minimal Core**:
本项目采纳的设计取向（源自 PI agent）：内核只提供不可再分的原语，其余能力经扩展机制组装——适应使用者的工作流，而不是内建所有功能。
_Avoid_: 极简主义（作为卖点；调研结论：极简本身不构成差异化）

**Session**:
本项目的数据地基与记录单位：append-only JSONL 树（entry 带 id/parentId），消息、工具调用、用量、压缩、分支全部记录其中；上下文从活动分支确定性重建。一次任务执行的完整可回放记录。
_Avoid_: 对话历史、聊天记录（指 UI 滚动日志时）

**Run**:
一次用户提示到最终回答的完整执行：`AgentLoop.run()`；内部可包含一个或多个模型 turn（工具调用循环）。中文里未特别说明的「回合」指 run；run 结束事件是 `RunEnded`。
_Avoid_: 用 turn 指 run（本仓库的 turn 专指模型轮次）

**Turn（模型轮次）**:
一次 assistant 回复及其声明的 tool calls / tool results；收集结构是 `_ModelTurn`。一个 run 包含一到多个 turn。
_Avoid_: 把 turn 当作“一次用户提问到回答”（那是 run）

**Failure attribution（失败归因）**:
把一次失败归入五类病位之一（模型误判 / 工具 schema / 上下文丢失 / 循环 / 环境），并给出证据与置信度；规则版、确定性、不调用模型。归因回答“病在哪一层”，不回答“谁的责任”。
_Avoid_: 把归因当作根因证明（它是可解释的代理证据）

**Regression task（回归任务）**:
由一条失败案例生成的独立评测任务：保留原任务的 setup/verifier/预算，只换 id；用于修好之后防止复发。
_Avoid_: 把回归任务混进原任务集（默认放 `evals/regressions/`）

**MCP Server**:
通过 Model Context Protocol 向 codelotte 提供外部工具的服务或进程；传输为 stdio 或 Streamable HTTP。项目级配置只有在该项目被 trust 后生效。
_Avoid_: MCP 插件、工具服务器（指 codelotte 内建工具时）

**MCP Tool**:
MCP Server 暴露的单个工具；在工具列表、权限规则与会话记录中用 `mcp__<server>__<tool>` 全名标识，避免与内建工具或其他 server 重名。
_Avoid_: 外部工具（太泛）

**Skill**:
以目录承载的可复用任务说明，入口是目录内的 `SKILL.md`，名称取目录名。codelotte 先看元数据，任务匹配或用户显式调用时再加载正文与资源。Skill 是上下文，不是工具，也不等同于 Slash Command。
_Avoid_: 技能包、插件（plugin）

**Skill Listing（技能清单）**:
系统提示词中呈现给模型的 Skill 元数据摘要（name / description / location）。正文不常驻上下文。
_Avoid_: 技能列表（指 `/skills` 的 TUI 输出时）

**Skill Invocation（显式技能调用）**:
用户以 `/skill:<name> [args]` 主动加载某个 Skill；与模型依据 description 自动加载相对。技能正文作为一条用户消息进入当前 Run，并写入 Session。
_Avoid_: 把显式调用当作普通 Slash Command 别名

**System Prompt**:
每次请求前由 codelotte 组装的行为说明（身份、工具规则、权限与沙箱约束、技能清单、项目指令、cwd）。它不属于 Session 的消息树，不参与压缩，也不随 fork 复制。
_Avoid_: 系统消息（指压缩摘要那条 system message 时）

**Prompt Version（提示词版本）**:
System Prompt 内容与来源的标识（版本 + hash）；写入 Session 元数据，用于回放告警与跨版本对比。
_Avoid_: 模型版本

**Permission Verdict（权限判定）**:
规则求值得到的三档结果：allow / ask / deny。它回答「按规则该怎么处理」。
_Avoid_: 把 verdict 与用户决策混为一谈

**Permission Decision（权限决策）**:
用户对一次 ask 的选择：once / session / always / deny / feedback。它回答「这一次实际怎么处理」。
_Avoid_: 审批结果（可用于界面文案，不作为术语）

**Session Rule（会话规则）**:
由 session 决策产生的显式放行，只在本会话内有效；resume/fork 时从 Session 的 permission 记录重放，不跨会话。
_Avoid_: 临时规则（含义不清）

**Command Class（命令类）**:
一条 shell segment 解析后的「可执行文件 + 子命令」组合（如 `git status`）。本会话放行以命令类为单位，不以原始字符串前缀为单位；复合命令逐段匹配。
_Avoid_: 命令前缀（会误导为字符串前缀匹配）

**Project Trust（项目信任）**:
用户对某个工作目录的显式信任标记；项目级权限规则、MCP 配置、Skill 与项目指令文件只有在该目录被 trust 后才加载。
_Avoid_: 授权（指单次工具调用时）

**Slash Command**:
TUI 中以 `/` 开头、由 codelotte 解析而不发给模型的内建命令（如 `/model`、`/clear`）。Skill 显式调用是其中一种特殊形式。
_Avoid_: 命令（指 bash 命令时）

**Serve（服务模式）**:
codelotte 的第三种运行形态 `codelotte serve`：多用户、多实例、带中间件依赖的 Agent 后端。与 TUI（交互式）和 `-p`（无头单次）并列；内核行为与另两种形态一致。
_Avoid_: 服务端（太泛）、后端（指整个项目时）

**User**:
调用 serve 的账号，是配额、限流与账单的唯一主体。本项目没有「组织」层级；一个 User 可以有多个 API Key。它不指 agent 在对话中服务的终端用户。
_Avoid_: 租户（tenant）、客户（customer）

**API Key**:
User 调用 serve 的凭证；数据库只存 `sha256` 摘要，不存明文；吊销后立即失效。
_Avoid_: Token、密钥（指 LLM provider 的 key 时）

**Job**:
一次 Run 的调度单元：提交后入队，由 Worker 领取执行，状态为 `queued / running / succeeded / failed / cancelled`。一个 Job 恰好执行一次 Run；Job 回答「排到哪了、跑到哪了」，Run 回答「模型和工具做了什么」。
_Avoid_: 任务（指评测 task 时）、请求（指 HTTP 请求时）

**Worker**:
消费 Job 队列、执行 Run 的独立进程；可多实例部署，与 API 进程分开扩容。
_Avoid_: 执行器（指 sandbox executor 时）

**Quota**:
User 在某个自然日内的可用额度，以「分」计。提交 Job 时预扣、Run 结束时结算；权威值在 Redis，PostgreSQL 只记流水。
_Avoid_: 余额（容易被理解为账户余额）
