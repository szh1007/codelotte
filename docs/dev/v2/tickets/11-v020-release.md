# 11: v0.2.0 发布收口

**What to build:** 重跑 9 条正式任务 ×3，更新 README/面试数据表并标注 v0.2.0；E1/E2/E5 标注「v0.1.1 结论，未复测」。新增 MCP 工具调用、Skill 自动/显式加载的最小 eval。CHANGELOG 0.2.0、README 功能/命令/配置、ROADMAP、SECURITY、SPEC、quickstart 更新。打 tag 0.2.0，发布镜像。ruff/pyright/全量测试绿。

🗣 大白话：把新功能、 新数字、新限制一次说清；旧实验结论标明版本，不拿 v0.1.1 的数字冒充 v0.2.0。

**Blocked by:** 02、04、05、07、09、10

**Status:** ready-for-agent

- [ ] 正式评测 ×3 重跑并更新数字（标注版本）
- [ ] MCP / Skill 最小 eval 各 1–2 条
- [ ] CHANGELOG / README / ROADMAP / SECURITY / SPEC / interview
- [ ] quickstart 复测
- [ ] tag + GHCR 镜像发布
- [ ] 全量测试、ruff、pyright
- [ ] 发布说明列出已知限制（MCP 宿主机运行、远程 git 不可用、Skill 预算）
