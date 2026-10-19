# 02: 系统提示词组装 + 项目指令

**What to build:** 新增请求时组装的 System Prompt。内容 = 身份 + 工具规则（按 codelotte 的 `read/write/edit/bash` 语义改写 pi 结构）+ 权限与沙箱约束 + 技能清单占位（票据 08 填充）+ 项目指令 + cwd。live 与 resume 共用同一个组装函数；压缩后的请求把「基础提示词 + 摘要 + 硬约束」合并为一条 system 消息；摘要、熔断等 `use_tools=False` 调用不注入基础提示词；请求指纹纳入 system。会话头写 Prompt Version（版本 + hash），prompt 变化追加 `event/promptChanged`；resume 时 hash 不一致只告警。项目指令：`~/.codelotte/AGENTS.md` 始终加载；项目 `AGENTS.md` → `CLAUDE.md` 从 cwd 向上到仓库根，只有项目被 trust 后加载，未信任时 TUI 横幅提示。

🗣 大白话：每次请求前给模型一张「工作说明书」；它不写进聊天记录，也不会被压缩吞掉；旧会话继续用同一套拼装逻辑，行为不会漂移。

**Blocked by:** 01（session 头字段）

**Status:** ready-for-agent

- [ ] 新模块 `src/codelotte/prompt.py`（或 `system_prompt.py`）：`build_system_prompt(...)` 与固定 section 顺序
- [ ] 基础 prompt 只描述 codelotte 真实存在的工具、沙箱与权限；若借用 pi 成段文字，新增 `THIRD_PARTY_NOTICES.md` 保留 MIT 全文与 `Copyright (c) 2025 Mario Zechner`
- [ ] `loop.py` 与 `session/context.py` 共用组装结果；live/resume 请求 roles 测试更新为 `system/user/...`
- [ ] 压缩：`build_compaction_messages` 接受基础 prompt，输出**一条** system；摘要/熔断调用不注入
- [ ] `_request_fingerprint` 纳入 system prompt
- [ ] 项目指令加载与 trust 门控；未信任提示；`AGENTS.md` 优先于 `CLAUDE.md`
- [ ] Prompt Version/hash 写 session 头 + 变更 event；resume 不一致告警
- [ ] 测试：组装顺序、live/resume 前缀一致、压缩合并、内部调用排除、trust、hash 告警
- [ ] 文档：README/SPEC 的「system prompt 未实现」改为当前行为
