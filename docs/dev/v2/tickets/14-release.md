# 14: v0.2.0 发布收口

**What to build:** 把新形态、新数据、新限制一次说清，并冻结证据。

- README 增加「服务化」一节：架构图、启动命令、八个 lab 的关键数字、明确的 Out of Scope。
- `CONTEXT.md` 新增术语：User / API Key / Job / Worker / Quota / Serve。
- CHANGELOG `0.2.0`；打 tag `0.2.0`。
- `interview/` 材料包增补：服务化 walkthrough、简历 bullet、可讲数字表；**明确标注哪些是实测**。
- 旧实验结论（E1–E5）保持 v0.1.1 口径，不冒充 v0.2.0 复测结果。
- v0.3.0 的票据与 ADR 保持不动，确认没有互相踩踏。

🗣 大白话：把这次做的东西、数字、边界一次讲清，不拿旧数字冒充新结果。

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] README：服务化一节 + 文档索引更新 + 状态更新
- [ ] `CONTEXT.md`：六个新术语
- [ ] `CHANGELOG.md`：0.2.0 条目
- [ ] `interview/`：新增服务化 walkthrough 与数字表，标注实测/设计
- [ ] `docs/adr/README.md`：0010–0012 入索引
- [ ] 全量测试绿；`ruff` / `pyright` 干净；`pytest -m serve` 绿
- [ ] tag `0.2.0`
- [ ] `docs/dev/v2/tickets/README.md` 状态全部 `done`
- [ ] 确认 `src/codelotte/` 下除 `serve/` 外无 diff（内核零改动）
