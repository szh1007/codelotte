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
