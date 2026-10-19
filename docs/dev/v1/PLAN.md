# codelotte 开发方案（v1 · 2026-10-13）

> 本文档是三轮设计访谈（grilling + domain-modeling）收敛后的完整方案。
>
> - **关键决策**：[docs/adr/](../../adr/)（0001–0005）
> - **术语表**：[CONTEXT.md](../../../CONTEXT.md)
> - **技术规格**：[SPEC.md](SPEC.md)
> - **任务拆解**：[tickets/](tickets/README.md)
> - **事实依据**：
>   - [技术栈调研](../../research/README.md)
>   - [pi 设计笔记](../../research/pi-agent-design.md)
>   - [岗位 JD 调研](../../research/agent-job-market.md)
>   - [生态差异化扫描](../../research/portfolio-differentiation.md)
>   - [DeepSeek API 笔记](../../tech/deepseek-api.md)
>   - [Python 栈笔记](../../tech/python-stack.md)
>
> **执行状态（2026-10-19）**：本文是原始方案，保留目标与取舍的历史记录；实际交付以
> [README](../../../README.md)、[CHANGELOG](../../../CHANGELOG.md) 与 [面试数据表](../../../interview/data-sheet.md) 为准。
> 未达成的计划项（如 dogfood ≥4 周、任务集 30+）不作为已完成成果宣传。

## 0. 一页速览

| 项 | 内容 |
|---|---|
| 是什么 | codelotte——minimal-core、可扩展的终端 coding agent；Agent 开发岗求职作品 |
| 目标市场 | 国内为主（Agent 平台/应用方向，大厂 + AI 创业双投），海外加分 |
| 成功标准 | 一句话：「**把 harness 的成本/成功率/失败率从 A 改到 B，并知道为什么**」——用实验报告证明 |
| 深度押注 | D1 评测闭环 / D2 权限沙箱 / D4 压缩质量 / D5 轨迹归因（详见 [定位 ADR](../../adr/0001-portfolio-positioning.md)） |
| 技术栈 | Python 3.13 + uv 0.13 + Textual 8.2.8 + httpx2 + Docker；模型走 DeepSeek（`openai-completions` 已实测；`anthropic-messages` 协议抽象预留，未实现） |
| 节奏 | 约 6 周；**W4 开始投递**，边走边迭代 |
| 形态 | CLI-first + TUI + 自包含 HTML 会话导出；public repo 第 1 天起 |

## 1. 架构

### 1.1 包布局

```
codelotte/
├── PLAN.md（本文件）/ CONTEXT.md / README.md / LICENSE(MIT)
├── pyproject.toml            # uv_build 后端 + [project.scripts] codelotte=...
├── uv.lock
├── docs/                     # adr/ · research/ · tech/ · experiments/(W5)
├── evals/
│   ├── tasks/                # NNN-slug.toml（任务定义，见 §4）
│   └── runs/                 # 跑数记录（锁依赖+锁 git ref+原始轨迹）
└── src/codelotte/
    ├── cli.py                # 入口：run / export / eval 子命令
    ├── loop.py               # agent loop + 死循环三层防御
    ├── session/              # store.py（JSONL 树）· context.py（活动分支重建+确定性序列化）
    ├── providers/            # protocol.py（wire protocol 抽象+模型目录）· openai_completions.py
    │                         # · anthropic_messages.py · sse.py（内联解码 ~100 行）
    ├── tools/                # read.py · write.py · edit.py · bash.py（仅 4 个，Minimal Core）
    ├── permissions/          # rules.py（tool(pattern) 解析）· approval.py（TUI 审批/headless fail-closed）
    ├── sandbox/              # docker.py（长驻容器+exec+网络策略）· local.py（--no-sandbox 逃生门）
    ├── compaction/           # trigger.py（双触发）· summarize.py（结构化模板+约束重注入）
    ├── usage/cost.py         # 按时段（峰谷）+ 缓存命中/未命中的记账
    ├── export/html.py        # 自包含单文件导出
    ├── tui/app.py            # Textual 应用（流式渲染/审批弹层/成本 footer）
    └── evals/                # loader.py · runner.py（pass^k+种子+计费时段）· verifiers.py（命令式优先+judge κ）
```

### 1.2 数据流

```
用户 ⇄ TUI(Textual)
         │
    ┌────▼─────┐
    │ Agent Loop │──► providers/adapter（openai-completions → DeepSeek；anthropic-messages 预留）
    └─┬──┬───┬──┘        │
      │  │   │           └──► usage/cost（每调用记 token/缓存命中/时段价）
      │  │   └──► compaction（双触发；压缩落为 Session 一条 entry）
      │  └──────► session store（append-only JSONL 树；一切进这里）
      └─────────► tools ⇄ permissions（规则+审批）⇄ sandbox（Docker）
                     │
                     └──► export/html（时间线+成本面板+拦截/压缩标记）
                          evals（直接读 Session 作为轨迹）
```

**关键不变量**：一切经过 Session——消息、工具调用、usage、压缩、分支。评测与归因共用同一数据源（[ADR-0003](../../adr/0003-session-model.md)）。

## 2. 核心机制（第 3 轮定案）

### 2.1 压缩（D4）

- **触发**：软触发（上下文利用率 ~60%，在最近的「任务边界」执行——边界 = 用户消息边界 ∪ git commit 点）+ 硬触发（~85% 立即）
- **摘要**：结构化模板（任务目标 / 已完成 / 关键决策及理由 / 活跃约束 / 文件清单 / 下一步）；同模型 self-summarize；**硬约束在摘要器之外额外重注入**（防 ConstraintRot）
- **记录**：压缩产物就是 Session 里的一条 entry（summary + 保留边界），可精确比对压缩前后
- **回归套件**：同任务强制压缩 k=1/3/5 → pass 率衰减曲线 + 关键状态保留率（压缩后用 checkpoint 问题集测）；触发策略与模板作为 A/B 参数

### 2.2 权限与沙箱（D2）

- **规则语法**：`tool(pattern)`（如 `bash(git diff *)`、`read(src/**)`）；**破坏性动词**（`rm -rf`、`push --force`、`reset --hard`、`chmod -R` 等）禁止通配放行，只能精确规则或逐次审批
- **规则来源**：CLI > 项目级 `.codelotte/permissions.toml`（需 trust 确认）> 用户级
- **审批**：TUI inline（本次 / 本会话 / 始终 / 拒绝）；headless fail-closed；`--approve` 单次显式全信
- **沙箱**：每会话一个 Docker 长驻容器（`docker exec` 复用），bind mount 工作区，网络默认 deny + 域名白名单；`--no-sandbox` 为显式逃生门

### 2.3 死循环三层防御（对齐 JD 最经典考点）

1. 工具层：重复调用检测 + 结果无进展检测
2. 推理层：迭代上限 + 熔断（连续失败模式识别）
3. 规划层：约束重注入 + 自修正提示

### 2.4 成本（D3）

- 每调用记账：token（in/out）、缓存命中/未命中（hit ≈ 1/50 价）、**按峰谷时段计价**（off-peak 五折）
- TUI footer 实时显示会话成本；`/session` 出分模型/分阶段账单
- 两个可量化干预：缓存命中率提升（确定性序列化 + 前缀稳定）、非紧急任务 off-peak 调度

### 2.5 导出（面试演示本体）

`codelotte export --html <session>` → 自包含单文件（内联 CSS/JS）：时间线（消息/工具调用可折叠）+ **成本面板**（token/命中率/峰谷费用）+ 标记（压缩点、注入拦截、死循环熔断）。README 放真实样例链接。

## 3. 评测系统（D1）

- **任务格式**：`evals/tasks/NNN-slug.toml`——id / bucket（A dogfood、B 对抗、C 公开）/ 仓库快照（git ref + setup）/ 指令 / 验收器（命令式优先，LLM judge 兜底且记录 κ）/ 超时与 token 预算
- **轨迹**：直接复用 Session JSONL（评测与 D5 归因同源）
- **执行**：每任务 k=3 次，记录种子与实际计费时段；结果落 `evals/runs/<run-id>/`（可复现）
- **指标**：pass^k、per-task 成本、缓存命中率、失败分类分布、压缩后成功率
- **CI**：GitHub Actions 跑冒烟子集（B 桶自带）+ 单元测试
- **Baseline**：mini-swe-agent（litellm 接 DeepSeek）+ 裸单轮 API——测 scaffolding tax
- 起步 10-15 条（W4 前），W5 扩到 30+

## 4. 实验计划（W5，每项一份实验报告：任务集/基线/干预/指标/轨迹/复现脚本）

| # | 实验 | 干预 | 主指标 |
|---|---|---|---|
| E1 | 压缩回归 | 触发策略 × 摘要模板 A/B | pass 衰减曲线、状态保留率 |
| E2 | 成本曲线 | 缓存命中率提升 + off-peak 调度 | 成本/任务、命中率、峰谷分布 |
| E3 | 失败归因 | 失败分类器上线前后 | 归因准确率（人工标注对照）、失败分布 |
| E4 | Scaffolding Tax | codelotte vs mini-swe-agent vs 裸 API | 同任务成功率/成本对照 |
| E5 | 防御有效性 | 注入/死循环对抗桶 | 拦截率（目标 100%）、误报率 |

**砍单顺序**（超期时从后往前砍）：E5 → E3 → C 桶任务 → Responses 协议 → TUI 视觉打磨。E1/E2/E4 是核心，必须完成。

## 5. 里程碑（约 6 周）

**W1 骨架**：git init + public + MIT + README 骨架 + .gitignore（凭据）｜ uv 0.13 + src 布局 + scripts 入口 ｜ adapter v0（openai-completions + SSE + usage 解析）｜ 4 工具（local 模式）｜ loop v0 + 最简 TUI
✅ 验收：能完成「在本仓库改一个文件并跑测试」的真实任务

**W2 会话与成本**：session store（JSONL 树 + fork + 确定性序列化）｜ 成本记账（时段+缓存）→ TUI footer ｜ HTML 导出 v1 ｜ **dogfood 正式开始**（每日任务记录）
✅ 验收：完成一个 dogfood 任务，导出 HTML 含完整成本面板

**W3 安全与压缩**：权限层（语法+trust+审批+fail-closed）｜ Docker 沙箱（长驻容器）｜ 死循环三层防御 ｜ 压缩 v1（双触发+模板+约束重注入）｜ 专用测评 - 压缩回归 v0（3 条任务）
✅ 验收：注入用例被拦截；强制压缩 3 次的任务仍能完成

**W4 MVP 里程碑 → 开始投递**：README v1（中文版）+ ADR 索引 + 演示录屏 ｜ 修 dogfood 高频问题
✅ 验收：外部人 20 分钟内克隆跑通

**W5 评测与实验**：eval runner ｜ E1-E4（E5 视余量）｜ 复盘文 1 篇（结论双语）
✅ 验收：实验报告落库，数据进 README

**W6 打磨与材料**：security policy / roadmap / CONTRIBUTING ｜ 简历材料包 + 面试 walkthrough 脚本（20 分钟动线：数据表 → demo → 代码走读 → 失败分析）｜ 数据刷新
✅ 验收：材料包完整，可投二面（2026-10-19 已完成，见 [interview/](../../../interview/README.md)、[SECURITY.md](../../../SECURITY.md)、[CONTRIBUTING.md](../../../CONTRIBUTING.md)、[ROADMAP.md](ROADMAP.md)）

## 6. 交付物清单（DoD）

1. Public repo（MIT）：代码 + `uv tool install` 可装 + 20 分钟 quick start
2. ADR 0001-0005+ ｜ CONTEXT.md ｜ README 中文版（证据先行）
3. 实验报告 E1-E5（≥4 份）+ 复盘文 1 篇
4. HTML 会话样片 ≥2（含成本面板/拦截记录）
5. dogfood 日志 ≥4 周（合并 PR 数、省时、翻车案例）
6. 演示录屏 + 面试 walkthrough 脚本

## 7. 面试映射（交付物 → 考点）

| 交付物 | 直接回答的考点 |
|---|---|
| 评测系统 + E4 | 「你这个系统怎么验证有效？」（问穿句）、baseline 意识、scaffolding tax |
| 专用测评 - 压缩回归 v0 + E1 | 上下文压缩管线、压缩后保真、回归测试 |
| 死循环三层防御 | 「调了三个工具就死循环，异常处理在哪写的？」 |
| 权限 + 沙箱 + E5 | 高危操作管控、注入防御、凭证不进上下文 |
| 成本面板 + E2 | 量化意识、模型路由/成本工程、缓存经济学 |
| Session 树 + E3 | 轨迹归因（attribution 是招聘方点名能力）、fork/A-B |
| 自研 adapter | Function Calling/协议理解、多模型接入 |
| ADR 全集 | 「为什么这么设计」的每一个追问 |

## 8. 简历 bullet（最终版见 [interview/resume.md](../../../interview/resume.md)）

1. 独立设计开发 **codelotte**：一款 minimal-core 终端 coding agent（Python 3.13 / Textual / 自研 LLM 接入层），从 0 实现 agent loop、会话树、权限沙箱与评测体系，开源 **1 star**（2026-10-19）
2. 构建 agent 质量闭环：9 条任务 × 3 次正式评测 **27/27、pass^3 9/9**；量化 harness 改进——长任务压缩保留率 **87.8% → 93.3%**、成本 **−23.1%**；实际成本较无缓存+全峰价反事实 **−80.8%**（¥1.0717 → ¥0.2058）
3. 设计双层执行安全（权限规则 × Docker 沙箱）与轨迹级失败归因，把 prompt 注入与死循环做成可复现用例：注入 **27/27**、死循环剧本 **5/5**、正常任务误报 **0/31**
4. （暂不投递）连续 **0 周**以自研 agent 开发自身（dogfood），累计合并 **0 个**自产 PR；
   dogfood 日志已有脚手架，但尚未开始记录。补齐后再按日志填写

> 数字来源、分母与「不能证明什么」见 [interview/resume.md](../../../interview/resume.md)；
> 该文件是维护入口，PLAN 只保留摘要。

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| DeepSeek 能力不足以跑复杂任务 | dogfood 从小任务起步；baseline 同模型（对照公平）；跨模型槽位预留 |
| Textual 学习曲线 | W1 只做单屏流式最简版，样式后置（砍单项） |
| Windows + Docker 性能/兼容 | 长驻容器减少冷启动；`--no-sandbox` 兜底；Windows Terminal 为目标环境 |
| 6 周估时偏差 | W4 是硬检查点；超期按 §4 砍单顺序收缩 |
| 单模型对照缺位 | adapter 协议抽象已预留；当前只实测 `openai-completions`，第二协议/第二模型为后续工作（见 [ROADMAP.md](ROADMAP.md)） |

## 10. 待办（非阻塞）

- [ ] 本机 pi 的 `~/.pi/agent/models.json` 修复（`"api": "PI"` → `"openai-completions"`）+ key 移入环境变量
- [ ] `.research-tmp/` 中转脚本清理
- [ ] W1：确认 Windows Terminal 环境
