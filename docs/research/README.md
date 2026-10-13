# 企业级 Coding Agent 技术栈调研

> 信息截止：2026-10-13 ｜ 调研方式：4 个并行研究任务覆盖六个技术域，关键事实经交叉验证。来源与置信度分级见 [06-sources-and-confidence.md](06-sources-and-confidence.md)，**引用前请先读该文**。

## 结论先行

2026 年不存在能整包采购的「企业级 coding agent 技术栈」。工程上收敛为 8 层选型，竞争焦点已从「模型能力」转向 **harness（脚手架）+ 上下文基础设施 + 沙箱 + 评测 + 治理**。主流架构是 **自持精简 agent loop + 平台组件外购**。

## 四个改变选型逻辑的事实

### 1. Harness 与模型同等重要，甚至更决定成本

| 数据 | 来源 |
|---|---|
| Claude Code+Sonnet 5.5 与 Codex+GPT-6.1 Sol 在同 effort 档**同为 63 分**，每任务成本 $14.19 vs $1.04（≈13 倍） | Artificial Analysis Coding Agent Index v1.5（2026-10-07） |
| 21 组 model×harness 对比：成功率仅差 1.1pp（SWE-bench Lite 上 Fable 5：Claude Code 97.8% vs pi 96.7%），成本差约 2 倍（$1.33 vs $0.67/次）；Terminal-Bench 2.0 上 pi 83.3% @ $0.42 vs Codex 78.9% @ $0.76 | HarnessTax（UC Berkeley Sky Computing，2026-09） |
| 机制：Claude Code 平均初始上下文 **> pi 的 10 倍**（平均 turn 数几乎相同，15.3 vs 15.4）；⚠️ 该研究样本小（每 benchmark 30 题 × 3 次）且有复跑反驳，引用需注明 | 同上 |

→ 调 harness / effort 的杠杆 ≥ 换模型。

### 2. 公开 benchmark 进入信任危机

- **OpenAI 2026-02-23 停止报告 SWE-bench Verified**：o3 从未解出的 138 题中 ≥59.4% 存在测试缺陷；所有被测前沿模型能逐字复现金标准补丁（训练数据污染）。Epoch AI 将其评级为 "Flawed"。
- 接替者：**Terminal-Bench 4.0**（榜首 Claude Opus 5.5 + Claude Code **64.85%**，330 trials）、**SWE-bench Pro**（public/held-out/commercial 三段防污染设计）、**Harbor-Index 1.0**（82 道防饱和题，**无组合超过 30%**，榜首 25.6%）。
- 统计学现实：前 30 名中相邻模型对无法通过 McNemar 检验区分；scaffold 差异（29.8pp）> 模型区间（8.8pp）。
- 刷分实测：Cursor 审计发现 Opus 4.8 在 SWE-bench Pro 上 **63% 的成功轨迹能检索到修复补丁**；arXiv 2606.16062 测得 28.5% 的 Verified 任务存在 reward hack 路径。

→ 内部自建 eval 是必需品，公开榜不可作为选型依据。详见 [04](04-sandbox-and-evaluation.md#二评测体系)。

### 3. 安全从「防注入」转向「遏制」

- 自适应策略下对 SOTA 防御的攻击成功率 **>85%**，18 个受调查防御多数缓解率 <50%（SoK，arXiv 2601.17548）。
- 真实供应链事件已规模化：Miasma 蠕虫植入 `.claude/` `.cursor/` 配置（73 个微软仓库下线）、CHAINDROP、postmark-mcp 后门（~15,000 邮件/天）、Shai-Hulud（500+ npm 包窃取 `ANTHROPIC_API_KEY`）。
- 治理框架：OWASP Agentic Top 10 + OWASP MCP Top 10（MCP03=工具投毒）、NSA MCP 安全指南（2026-05）、CSA 白皮书（2026-06）。
- 共识：**containment over prevention** —— 防线在沙箱、凭证、供应链、行为监控层，不在模型层。

### 4. 部署收敛为「云端控制面 + 企业边界内执行」

Bedrock/Vertex/Foundry 落 VPC（Claude Code）、Coder Agent Relay（云 agent + 自托管执行）、Factory Private（VPC/on-prem/air-gapped，Private Preview）、GitLab Duo Self-Hosted（offline GA）。**原生真 air-gapped GA 的主流产品几乎没有**。

## 分层速览

| 层 | 2026-10 主流选择 | 详见 |
|---|---|---|
| L1 模型与推理 | 分层路由（前沿/主力/走量）+ prompt caching / batch / effort 三杠杆 | [01](01-models-and-orchestration.md) |
| L2 Agent 编排 | 自持精简 loop 为主流答案；LangGraph 1.0 / 厂商 SDK 补状态与工具 | [01](01-models-and-orchestration.md#二agent-编排框架) |
| L3 上下文与代码智能 | agentic grep 优先 + regex/语义索引按需 + LSP/SCIP + 分层 AGENTS.md | [02](02-context-engineering.md) |
| L4 工具协议 | MCP（2026-07-28 无状态版）+ Tool Search 延迟加载 + AGENTS.md/Skills | [03](03-tool-protocols.md) |
| L5 执行沙箱 | microVM（Firecracker/gVisor）；选型看生命周期语义而非隔离强度 | [04](04-sandbox-and-evaluation.md) |
| L6 评测 | 题集 + 脚本 + CI 门禁；确定性判分优先；公开榜不可信 | [04](04-sandbox-and-evaluation.md#二评测体系) |
| L7 可观测与成本 | OTel GenAI semconv（Development 状态，pin 版本）+ Langfuse/LangSmith + 成本归因 | [05](05-security-and-platform.md) |
| L8 安全治理 | 权限分层（deny>ask>allow）+ PreToolUse 拦截 + 审计（NHI）+ SOC2/ISO 42001 | [05](05-security-and-platform.md) |

## 关键 build-vs-buy 决策

| 决策 | 2026 主流答案 | 依据 |
|---|---|---|
| Agent loop | 自持精简 loop；SDK 起步但保留替换面 | harness tax 数据 |
| 模型 | API 分层路由；自部署仅当合规要求或 >10 亿 tok/月 | 盈亏平衡点 |
| 检索 | grep-first，按需加 regex/语义索引；不建 2023 式 RAG | GrepRAG、Cursor |
| 沙箱 | 起步用商业（E2B/Modal/Vercel）；规模化上 K8s agent-sandbox | 生命周期语义 |
| 评测 | 题集 + 脚本 + CI 门禁，**不建平台** | 腾讯 107 天复盘 |
| 可观测 | OTel 兼容层 + 独立 eval 层，pin schema 版本 | semconv 未稳定 |
| 治理 | 权限 + 沙箱 + 审计从 day-1 建（企业采购门槛） | 攻击面数据 |
| 协议 | MCP（无状态版）+ AGENTS.md + Skills | 事实标准 |

## 从零落地顺序

1. **Phase 0 验证**：模型 API 网关 + 精简 loop + 文件/命令工具 + 一个沙箱，跑通内部任务集
2. **Phase 1 上下文**：grep/glob/read 工具、分层 AGENTS.md、compaction、prompt cache 纪律（静态前缀在前）
3. **Phase 2 评测闭环**：内部题集 + 确定性判分 + 变异测试 + CI 门禁（oracle/no-op/cheating 三对照）
4. **Phase 3 治理**：权限分层 + PreToolUse 拦截 + 审计日志 + 成本归因
5. **Phase 4 集成**：GitHub/GitLab → CI → Slack/Jira → IDE

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-models-and-orchestration.md](01-models-and-orchestration.md) | 模型层（闭源/开源/推理引擎/成本杠杆）+ Agent 编排框架（自建 vs 框架、多 agent、长任务） |
| [02-context-engineering.md](02-context-engineering.md) | 代码检索路线、索引技术、tree-sitter/LSP/SCIP、长上下文 vs RAG、大仓策略 |
| [03-tool-protocols.md](03-tool-protocols.md) | MCP 状态与 2026-07-28 无状态改版、互操作标准矩阵、工具经济学、工具设计实践 |
| [04-sandbox-and-evaluation.md](04-sandbox-and-evaluation.md) | 沙箱隔离技术与商业服务、大厂执行架构、benchmark 现状与刷分、企业自建 eval |
| [05-security-and-platform.md](05-security-and-platform.md) | 权限模型、prompt injection、审计合规、数据路径、可观测性、成本治理、部署与市场 |
| [06-sources-and-confidence.md](06-sources-and-confidence.md) | 来源清单与置信度分级（引用前必读） |

## 关联调研（同期产出，同在本目录）

| 文档 | 内容 |
|---|---|
| [pi-agent-design.md](pi-agent-design.md) | PI agent（模仿对象）的身份、设计哲学、HarnessTax 一手数据与 10 条可迁移设计点 |
| [agent-job-market.md](agent-job-market.md) | 2026 Agent 岗位 JD 与面试考点（技术需求分级清单、面试高频 17 题） |
| [portfolio-differentiation.md](portfolio-differentiation.md) | 作品生态扫描与 8 个差异化方向（D1–D8），含招聘评估视角 |

## 时效性说明

本领域以周为单位变化。本文档数字以 2026-10-13 检索时点为准；正文中 `【一手】/【三方】/【厂商】/【二手】/【待核验】` 标签的含义与遗留风险见 [06](06-sources-and-confidence.md)。
