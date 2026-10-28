# 08: Skill 加载与自动匹配

**What to build:** 扫描 `~/.codelotte/skills/`、项目 `.codelotte/skills/`（trust）、`~/.agents/skills/`、项目 `.agents/skills/`（trust）。目录名 = 技能名；入口 `SKILL.md`；frontmatter 的 `name` / `description` 必需且 `name` 与目录一致；未知字段忽略；invalid 告警并跳过。会话启动快照；同名按「项目 > 用户 > agents」覆盖并告警。Level 1：系统提示词 `<available_skills>` 列 name/description/location，设 token 预算，`disable-model-invocation` 不列入。Level 2：模型用 `read` 读正文；prompt 说明相对路径按技能目录解析。

🗣 大白话：把技能目录变成模型能看到的「技能清单」；它只在需要时读正文，正文不常驻上下文。

**Blocked by:** 01、02

**Status:** ready-for-agent

- [ ] skill loader + frontmatter 校验 + 冲突/shadowing
- [ ] 系统提示词技能段（预算、截断告警、`disable-model-invocation`）
- [ ] 自动加载说明与相对路径规则
- [ ] 项目级 skills trust 门控
- [ ] 测试：目录发现、frontmatter、冲突、预算、trust、prompt 段
- [ ] 文档：README / SKILL 格式说明
