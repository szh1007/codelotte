# 系统提示词组装与 session/v2

Status: accepted (2026-10-20)

系统提示词是请求时组装层，不是会话内容：

- 每次请求由唯一组装函数生成：身份、工具规则、权限与沙箱约束、技能清单、项目指令、cwd；live 与 resume 共用。
- 基础提示词 + 压缩摘要 + 硬约束合并为**一条** system 消息；压缩摘要、熔断等内部调用不注入基础提示词。
- 不写入消息树；会话头记录 Prompt Version（版本 + hash），提示词变化追加 event；resume 时 hash 不一致只告警。
- 请求指纹纳入 system prompt。
- 项目指令：`~/.codelotte/AGENTS.md` 始终加载；项目 `AGENTS.md` → `CLAUDE.md` 从 cwd 向上到仓库根，只有项目被 trust 后加载；不做 `SYSTEM.md` / `APPEND_SYSTEM.md` / override / 多级合并。
- Session schema 升至 `session/v2`：写入 v2；读取 v1 + v2；不迁移、不重写 `evals/runs/**` 历史证据；新 entry 类型只在 v2 产生。
- 新 entry / 字段：`skill`、`event/modelChanged`、`event/effortChanged`、`event/promptChanged`、`event/mcpToolsChanged`、`decision=feedback`。

理由：

- 现有不变量要求 live 与 resume 的请求前缀逐字节一致；系统提示词必须走同一条组装路径。
- 现有压缩把摘要放进唯一一条 system 消息，并明确避免叠 system；合并是保持该约束的唯一简单做法。
- 写进消息树会迫使压缩、导出、fork、回放都处理一种新 entry，收益只是「回看当时 prompt」；hash + 版本足够。
- 项目指令是系统提示词价值最高的部分，但克隆仓库的指令文件是提示词注入面，复用项目 trust 是现成的边界。
- 历史评测 run 是证据，不能为了 schema 整洁而重写；读取器本来就忽略 schema，接受 v1 成本为零。

被否备选：

- 把完整 prompt 作为 entry 写进会话树（污染不变量）。
- 在 TUI/CLI 各自注入（破坏前缀一致性）。
- 叠两条 system 消息（部分 OpenAI 兼容后端拒绝）。
- 严格只读 v2（必须重写 221 个历史 run）。
- 无条件加载项目指令（克隆仓库即可注入）。

后果：

- 跨版本 resume 的 prompt 可能与首次运行不同；hash 告警即为此设。
- 精确回放需要仓库 tag 或模板版本，而不是会话文件自包含 prompt。
