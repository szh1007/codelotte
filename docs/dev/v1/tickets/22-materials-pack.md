# 22: 材料包：治理文档 + 面试脚本 + 数据刷新

**What to build:** 把"面试武器库"打包收口：① 治理文档三件套——security policy（安全模型与漏洞报告途径）、roadmap（未来方向）、CONTRIBUTING（协作方式）；② 20 分钟面试 walkthrough 脚本——动线为"数据表 → 现场演示 → 代码走读 → 失败分析"，含每段要点与可能追问的答案；③ 简历 bullet 的 [占位符] 全部填入真实数字（成功率/成本/拦截率/stars/dogfood 天数）；④ 所有 README 与文档中的数字刷新到最终版本。

🗣 大白话：最后一步打包——故事、数据、演示动线、追问答案全部就位，面试时打开仓库就能讲、点开链接就有证据。

**Blocked by:** 14（README + dogfood）、19（E4）、20（E1+E2）、21（E3+E5）

**Status:** done（2026-10-19；含作者待补项：整场 20 分钟口述计时、dogfood 连续记录、
3 分钟录屏。其余交付物已完成，材料中如实标注，未把待补项写成已完成）

- [x] 治理文档三件套就位：[SECURITY.md](../../../../SECURITY.md) / [ROADMAP.md](../ROADMAP.md) / [CONTRIBUTING.md](../../../../CONTRIBUTING.md)
- [x] walkthrough 脚本按 20 分钟动线完成（[interview/walkthrough.md](../../../../interview/walkthrough.md)）；
      现场演示段实际跑通并计时：**12.3s、7 次调用、¥0.009622（峰值）、缓存 87%**；
      会话轨迹已入库：[rehearsal-session-20261019.md](../../../../interview/rehearsal-session-20261019.md)
- [ ] 整场 20 分钟口述演练计时（待作者；[walkthrough §8](../../../../interview/walkthrough.md#8-附录-b演练记录)
      有检查清单与调整表）
- [x] 简历 bullet 四条填入真实数字（[interview/resume.md](../../../../interview/resume.md)）：
      27/27、pass^3 9/9、长任务保留率 87.8%→93.3%、成本 −23.1%、总节省 80.8%、
      注入 27/27、死循环 5/5、误报 0/31、stars=1；第 4 条 dogfood 的真实数字是
      **0 天 / 0 个自产 PR**，已标注「暂不投递」
- [x] README 数据表更新为最终版，并同步 PLAN / ADR-0004 / SPEC 的实现状态：
      当前只实现 `openai-completions`，`anthropic-messages` 是协议抽象预留（不写「双协议已实现」）；
      测试数 599 passed / 8 deselected

## 交付物

| 文件 | 内容 |
|---|---|
| [SECURITY.md](../../../../SECURITY.md) | 威胁模型、两层安全模型、已知限制、漏洞报告途径与范围 |
| [ROADMAP.md](../ROADMAP.md) | 当前状态、下一步主题、明确不做的事、优先级规则 |
| [CONTRIBUTING.md](../../../../CONTRIBUTING.md) | 环境、命令、测试/评测约定、代码风格、commit/PR 流程 |
| [interview/README.md](../../../../interview/README.md) | 材料包索引、三条必说限制、数字刷新方式 |
| [interview/data-sheet.md](../../../../interview/data-sheet.md) | 一页纸数据表（仓库、评测可信度、E1–E5、演示、限制） |
| [interview/walkthrough.md](../../../../interview/walkthrough.md) | 20 分钟动线、每段话术、追问答案、兜底与演练记录 |
| [interview/resume.md](../../../../interview/resume.md) | 四条简历 bullet + 每个数字的来源/分母/边界 |
| [interview/project-experience-v1.md](../../../../interview/project-experience-v1.md) | 简历版项目经历 v1：概述+指标、5 条技术介绍、技术栈、关键词文档索引 |
| [interview/pi-agent-and-claude-code.md](../../../../interview/pi-agent-and-claude-code.md) | Pi agent 极简主义介绍、codelotte 的参考点、与 Claude Code 的横向对比 |

## 本次刷新纠正的事实

- **协议能力**：代码只有 `openai-completions`；README 架构图、PLAN、SPEC、ADR-0004 索引
  原先隐含「双协议已实现」，现已全部改为「协议抽象预留、未实现」。
- **stars / dogfood**：stars=1（2026-10-19）、dogfood=0 天 / 0 PR；不夸大。
- **演示成本**：README 样例是低谷时段 ¥0.004394；2026-10-19 实测为峰值 ¥0.009622，
  两者都在材料中标注了时段，避免把成本说成固定值；实测会话已导出到
  [rehearsal-session-20261019.md](../../../../interview/rehearsal-session-20261019.md)。
- **口径修正**：`eval compaction` 的 9 任务全量（单组合）是 36 条案例，E1 的三组合矩阵
  另计（短任务 72 + 长任务 36）；quickstart 的 17 秒包含 12 秒真实任务，不是纯 clone + sync；
  stars 复现命令改用 REST 字段 `stargazers_count`；CONTRIBUTING 明确主程序不从环境变量
  读取 provider/模型/API key（评测适配器会传递现有环境给子进程）。
