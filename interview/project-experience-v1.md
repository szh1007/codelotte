# codelotte 项目经历（简历版）

> **版本：v1（2026-10-19）**。后续迭代新建 v2 / v3，不覆盖旧版；版本记录见文末。
> 用途：直接摘录到简历「项目经历」栏；文末索引供面试前按关键词预习。
> 事实边界：当前只实现 `openai-completions`；dogfood 0 天 / 0 个自产 PR；
> judge 与失败归因标注为 `author-draft`，待独立复核。

## 0. 简历摘录（可直接粘贴）

**codelotte** · 独立开发 · Python 3.13 / Textual / Docker / DeepSeek

- 从 0 实现 minimal-core 终端 coding agent：agent loop、四工具、append-only 会话树、
  权限层 × Docker 沙箱、双触发压缩、死循环三层防御、逐次成本记账与 HTML / Markdown 导出。
- 建立可复现评测体系：9 条任务 × 3 次正式评测 **27/27、pass^3 9/9**；oracle / no-op /
  cheating 控制 agent 自检；LLM judge κ 校准、失败归因与回归任务。
- 量化 harness 改进：压缩模板把长任务关键状态保留率 **87.8% → 93.3%**、成本 **−23.1%**；
  缓存 + off-peak 使实际成本较无缓存全峰价 **−80.8%**。
- 安全与鲁棒性：prompt injection **27/27 未执行**、死循环剧本 **5/5 按层拦截**、
  正常任务误报 **0/31**；同模型对照与 mini-swe-agent 成功率打平（18/18），单案例耗时低 33.5%。
- 技术栈：Python 3.13 · uv · Textual · httpx2 · Docker · GitHub Actions · pytest / Ruff / Pyright。

## 1. 概述与评估指标

**一句话：** 独立设计并实现 **codelotte**——一款 minimal-core、可测量的终端 coding agent（harness）。

**技术总结：** 从 0 实现 agent loop、四个基础工具、append-only 会话树、权限层 × Docker 沙箱、
双触发上下文压缩、死循环三层防御、逐次成本记账与自包含会话导出。消息、工具调用、usage、
压缩、权限判定与护栏事件全部落在同一份 JSONL 轨迹里，回放、记账、评测与失败归因共用同一数据源。

**评估指标：**

| 指标 | 结果 | 口径 / 来源 |
|---|---|---|
| 正式评测 | **27/27 通过，pass^3 9/9** | 9 条任务 × 3 次，Docker；[report](../evals/runs/20261018T154112Z-fa9db83/report.md) |
| 控制 agent 自检 | oracle 9/9、no-op 0/9、cheating 0/9 且 9/9 标记 | 离线零成本；[report](../evals/runs/20261018T154851Z-fa9db83-controls/report.md) |
| 同模型对照 | codelotte 18/18、mini-swe-agent 18/18、裸 API 0/18 | E4；codelotte 成本 +15.4%、耗时 −33.5% |
| 压缩质量 | 长任务保留率 **87.8% → 93.3%**，成本 **−23.1%** | E1；单次重复，有噪声 |
| 成本优化 | 缓存命中 **89.0%**，相对无缓存+全峰价 **−80.8%** | E2；反事实重算，非关缓存 A/B |
| 防御有效性 | 注入 **27/27**、死循环剧本 **5/5**、正常任务误报 **0/31** | E5；行为测试，非运行时过滤器 |
| 失败归因 | **15/15**，宏观 F1 **1.000** | E3；作者草稿语料待复核 |

> 读法：每个数字的分母、噪声与「不能证明什么」都在 [一页数据表](data-sheet.md) 与各实验报告里。
> 简历只摘结论，面试时展开边界。

## 2. 技术介绍（5 条）

### 2.1 Agent 内核与数据地基

- 实现流式工具调用循环：请求模型 → 解析 `tool_calls` → 权限判定 → 执行 → 回填结果；
  支持流式文本、思考内容与 usage 解析。
- 设计 append-only JSONL 会话树（entry 带 `id/parentId`）：消息、工具调用、usage、压缩、
  权限与护栏事件同源；上下文从活动分支确定性重建，天然支持 `--continue` / `--resume` / `--fork`。
- 四个最小工具：`read` / `write` / `edit` / `bash`；文件工具在宿主机工作区执行，
  `bash` 默认进 Docker 容器。
- 代码：[loop.py](../src/codelotte/loop.py#L249) ·
  [session/store.py](../src/codelotte/session/store.py#L270) ·
  [session/context.py](../src/codelotte/session/context.py#L29) ·
  [tools/](../src/codelotte/tools/)

### 2.2 上下文压缩与回归

- 双触发：软阈值（默认 60%）在任务边界压缩；硬阈值（默认 85%）立即压到最小保留集。
- 结构化摘要 + 硬约束独立重注入，防止摘要过程丢掉「不许做什么」；压缩本身落为一条 entry，
  原始记录仍可查，可精确比对压缩前后。
- 压缩后用 checkpoint 探针做确定性评分；E1 用「切点策略 × 摘要模板 × k」矩阵验证，
  三节模板把长任务保留率从 87.8% 提到 93.3%，成本还降 23.1%。
- 代码：[compaction/trigger.py](../src/codelotte/compaction/trigger.py#L178) ·
  [compaction/summarize.py](../src/codelotte/compaction/summarize.py#L56)
- 实验：[E1 压缩曲线](../docs/experiments/e1-compaction-curve.md)

### 2.3 权限层 × Docker 沙箱

- 规则语法 `tool(pattern)`；判定 `deny > ask > allow`，无命中默认 `ask`；
  破坏性动词（`rm -rf`、`git push --force`、`git reset --hard` 等）不能被通配或裸工具规则放行。
- 项目级规则需 `codelotte trust` 确认；无头模式 fail-closed；每次判定落会话，可审计。
- `bash` 默认在每会话一个 Docker 长驻容器里执行：只挂工作区、根文件系统只读、
  `--network none`、内存/CPU/PID/超时限额；`--no-sandbox` 是显式逃生门。
- 代码：[permissions.py](../src/codelotte/permissions.py#L269) ·
  [sandbox/docker.py](../src/codelotte/sandbox/docker.py#L71) ·
  [SECURITY.md](../SECURITY.md)
- 实验：[E5 防御有效性](../docs/experiments/e5-defense-effectiveness.md)

### 2.4 死循环三层防御与失败归因

- 工具层：重复调用 / 无进展检测；推理层：连续失败熔断；规划层：任务目标与硬约束重注入，
  必要时温和终止。阈值在 `settings.json` 可配，所有拦截写成 `guardrail` 事件。
- 失败归因：从会话轨迹自动判断五类病位（模型误判 / 工具 schema / 上下文丢失 / 循环 / 环境），
  每条结论带证据与置信度，规则确定性、零额外成本；失败案例可转成可复跑的回归任务。
- 结果：死循环剧本 5/5、真实模型压力 3/3 介入且任务仍完成、正常任务误报 0/31；
  归因 15/15、宏观 F1 1.000（作者草稿语料）。
- 代码：[guardrails.py](../src/codelotte/guardrails.py#L184) ·
  [evals/attribution.py](../src/codelotte/evals/attribution.py)
- 实验：[E3 归因](../docs/experiments/e3-attribution-accuracy.md) ·
  [E5 防御](../docs/experiments/e5-defense-effectiveness.md)

### 2.5 评测体系与成本工程

- 任务 TOML：指令、初始文件、验收器、预算、checkpoint；验收器优先命令式，
  LLM judge 仅兜底且必须先有 κ 校准。
- 九个评测命令：`run / compare / controls / judge / attribute / regression / cost / defense / compaction`；
  支持 pass^k、控制 agent 自检、对照组、失败归因、防御审计与反事实成本。
- 逐次成本记账：token、缓存命中/未命中、峰谷时段；E2 从 usage 反事实重算，
  缓存命中 89.0%、相对无缓存+全峰价总节省 80.8%；E4 同模型对照成功率打平，
  codelotte 成本 +15.4%、单案例耗时 −33.5%。
- 代码：[evals/runner.py](../src/codelotte/evals/runner.py#L221) ·
  [evals/execution.py](../src/codelotte/evals/execution.py#L106) ·
  [cost.py](../src/codelotte/cost.py)
- 实验：[E2 成本曲线](../docs/experiments/e2-cost-curve.md) ·
  [E4 scaffolding tax](../docs/experiments/e4-scaffolding-tax.md)

## 3. 技术栈

| 层 | 选型 |
|---|---|
| 语言 / 包管理 | Python 3.13、uv 0.13（`uv.lock` 锁依赖） |
| CLI / TUI | argparse、Textual 8.2.8 |
| LLM 接入 | 自研 adapter：httpx2 + 内联 SSE；已实现 `openai-completions`（DeepSeek），`anthropic-messages` 协议抽象预留 |
| 执行隔离 | Docker 长驻容器（`docker exec` 复用）、本地执行器逃生门 |
| 会话与导出 | append-only JSONL 树、自包含 HTML / Markdown 导出 |
| 评测与统计 | TOML 任务、pass^k、Cohen's κ、精确率/召回率/F1、反事实成本 |
| CI | GitHub Actions（Ubuntu + Windows）、Ruff、Pyright、pytest（599 passed / 8 deselected） |
| 文档 | Markdown、Mermaid、ADR 0001–0005 |

## 4. 文档与代码索引（按关键词跳转）

| 关键词 | 跳转 | 说明 |
|---|---|---|
| 项目定位 / 差异化 | [README.md](../README.md) | 一句话定位、30 秒演示、证据段 |
| 设计来源 / Pi 对比 | [pi-agent-and-claude-code.md](pi-agent-and-claude-code.md) | Pi agent 极简主义、codelotte 参考点、Claude Code 对比 |
| 技术规格 | [SPEC.md](../docs/dev/v1/SPEC.md) | 完整技术规格与实现决策 |
| 架构决策 | [docs/adr/](../docs/adr/README.md) | ADR 0001–0005 |
| 票据与状态 | [docs/dev/v1/tickets/](../docs/dev/v1/tickets/README.md) | 22 张票据与验收项 |
| Agent 循环 | [src/codelotte/loop.py](../src/codelotte/loop.py#L249) | `AgentLoop`、事件流、run 生命周期 |
| 会话树 | [session/store.py](../src/codelotte/session/store.py#L270) · [session/context.py](../src/codelotte/session/context.py#L29) | append-only JSONL、活动分支重建 |
| 四个工具 | [src/codelotte/tools/](../src/codelotte/tools/) | `read` / `write` / `edit` / `bash` |
| 权限层 | [src/codelotte/permissions.py](../src/codelotte/permissions.py#L269) | 规则、审批、trust、fail-closed |
| Docker 沙箱 | [src/codelotte/sandbox/docker.py](../src/codelotte/sandbox/docker.py#L71) | 长驻容器、只读根、网络 none、限额 |
| 压缩 | [compaction/trigger.py](../src/codelotte/compaction/trigger.py#L178) · [compaction/summarize.py](../src/codelotte/compaction/summarize.py#L56) | 双触发、摘要模板、约束重注入 |
| 死循环防御 | [src/codelotte/guardrails.py](../src/codelotte/guardrails.py#L184) | 三层状态机与阈值 |
| 成本记账 | [src/codelotte/cost.py](../src/codelotte/cost.py) | 峰谷价、缓存命中、账单 |
| 评测 runner | [evals/runner.py](../src/codelotte/evals/runner.py#L221) · [evals/execution.py](../src/codelotte/evals/execution.py#L106) | 任务执行、pass^k、验收 |
| 失败归因 | [src/codelotte/evals/attribution.py](../src/codelotte/evals/attribution.py) | 五类病位、证据、回归任务 |
| 防御测试 | [src/codelotte/evals/defense.py](../src/codelotte/evals/defense.py) | 死循环剧本、注入、误报审计 |
| E1 压缩曲线 | [docs/experiments/e1-compaction-curve.md](../docs/experiments/e1-compaction-curve.md) | 策略 × 模板 × k |
| E2 成本曲线 | [docs/experiments/e2-cost-curve.md](../docs/experiments/e2-cost-curve.md) | 缓存 + off-peak 反事实 |
| E3 归因 | [docs/experiments/e3-attribution-accuracy.md](../docs/experiments/e3-attribution-accuracy.md) | 15/15、混淆矩阵 |
| E4 scaffolding tax | [docs/experiments/e4-scaffolding-tax.md](../docs/experiments/e4-scaffolding-tax.md) | codelotte / mini / 裸 API |
| E5 防御 | [docs/experiments/e5-defense-effectiveness.md](../docs/experiments/e5-defense-effectiveness.md) | 注入、死循环、误报 |
| 一页数据表 | [interview/data-sheet.md](data-sheet.md) | 面试屏幕共享 |
| 20 分钟 walkthrough | [interview/walkthrough.md](walkthrough.md) | 动线 + 追问答案 + 兜底 |
| 简历 bullet | [interview/resume.md](resume.md) | 四条 bullet + 来源/边界 |
| 演示会话 | [interview/rehearsal-session-20261019.md](rehearsal-session-20261019.md) | 12.3s / ¥0.009622 / 87% |
| 安全模型 | [SECURITY.md](../SECURITY.md) | 威胁模型、已知限制、报告途径 |
| 协作方式 | [CONTRIBUTING.md](../CONTRIBUTING.md) | 环境、测试、PR 流程 |
| 路线图 | [ROADMAP.md](../docs/dev/v1/ROADMAP.md) | 下一步与明确不做 |
| 操作手册 | [evals/README.md](../evals/README.md) · [evals/run.md](../evals/run.md) | 九个命令与报表 |
| 跑数记录 | [evals/record.md](../evals/record.md) | 已入库基线索引 |
| 快速开始 | [README.md#快速开始](../README.md#快速开始) | 配置与运行 |
| 演示脚本 | [docs/demo/](../docs/demo/README.md) | 3 分钟录屏分镜 |

## 5. 版本记录

| 版本 | 日期 | 变化 |
|---|---|---|
| **v1** | 2026-10-19 | 首版：基于票据 01–22 的最终交付物；数字快照与 [一页数据表](data-sheet.md) 一致 |
| v2 | 待定 | 独立复核 judge/归因标注、更长任务链、第二模型/协议、dogfood 连续记录后更新 |
| v3 | 待定 | 视后续功能与实验补充 |

> 更新规则：新增版本时**新建文件**（如 `project-experience-v2.md`），保留 v1 供对照；
> 数字只从入库报表与 [一页数据表](data-sheet.md) 刷新，不手抄、不估算。
