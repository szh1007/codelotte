# 09: Skill 显式调用与 /skills

**What to build:** `/skill:<name> [args]`；tab 补全；未知/无效技能报错。调用时读 `SKILL.md`，拼成 `<skill name location>正文</skill> + args` 的 user 消息；写 `skill` entry（name/location/contentHash/args/content）；replay 还原同一消息。TUI 折叠显示 `skill: <name>`，HTML 导出支持。`/skills` 列出技能、来源、invalid、shadowing；`/skills reload` 在 run 边界刷新清单并追加 `event/promptChanged`。`disable-model-invocation` 只允许显式调用。`allowed-tools` 等字段忽略。

🗣 大白话：输入 `/skill:名字` 直接加载技能；即使之后技能文件被改了，旧会话回放仍然和当时一模一样。

**Blocked by:** 05、08

**Status:** ready-for-agent

- [ ] `/skill:` 解析 + 补全 + 错误
- [ ] 调用时读正文、拼消息、写 `skill` entry
- [ ] replay 逐字节一致；文件修改后历史不变
- [ ] TUI 折叠块 + 导出
- [ ] `/skills` / `/skills reload`
- [ ] `disable-model-invocation` 语义
- [ ] 测试：调用、replay、文件变化、无效技能、补全
- [ ] 文档：README 命令表 + 技能说明
