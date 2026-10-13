# 06 来源与置信度分级（引用前必读）

> 本文档解决一个问题：**哪些结论可以直接引用，哪些必须回源核验。**
> 调研环境有一个重要限制：本次多轮调研中 WebFetch 多次被网络策略拦截、Firecrawl 额度耗尽，**相当一部分结论基于搜索引擎返回的聚合摘要而非逐页抓取原文**。因此每份文档中的标签必须被认真对待。

## 标签体系

| 标签 | 含义 | 可引用程度 |
|---|---|---|
| 【一手】 | 直接抓取官方文档/规范/博客/API 原文获得 | 可直接引用；跨 2026-10 后的引用建议看一眼是否有版本更新 |
| 【独立】 | 学术论文、独立评测机构（METR、Epoch、Artificial Analysis 等） | 可直接引用，注明机构与时间 |
| 【三方】 | 专业媒体/分析机构（InfoQ、The Register、Fortune、CSA 等） | 可引用；重大数字建议回源 |
| 【厂商】 | 厂商自述（官方博客、定价页、benchmark 自报） | 引用时必须标注「厂商口径」 |
| 【二手】 | 聚合类站点、SEO 内容、转述链 | **数字必须回源后才可引用** |
| 【待核验】 | 单源支撑或存疑 | 仅作线索，不作依据 |

## 一、本次调研的独立二次确认（4 项，均为高置信）

| 结论 | 确认方式 | 来源 |
|---|---|---|
| OpenAI 于 2026-02 停止报告 SWE-bench Verified（138 题 ≥59.4% 有缺陷；污染证据） | 独立搜索确认 + 多语种媒体交叉 | https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ |
| SpaceX 以 $60B 全股票收购 Cursor/Anysphere（2026-06-16 宣布） | 多家一线媒体（Reuters 系、Fortune、CNBC TV18 等） | https://fortune.com/2026/06/17/spacex-acquire-cursor-60-billion/ |
| Gartner 2026-05 发布 Enterprise AI Coding Agents MQ：AI 原生厂商占据 Leader，云厂商被挤出；MCP 支持列为硬性要求 | GitHub 官方公告 + 媒体交叉 | https://github.blog/ai-and-ml/github-copilot/github-recognized-as-a-leader-in-the-gartner-magic-quadrant-for-enterprise-ai-coding-agents-for-the-third-year-in-a-row/ |
| MCP 2026-07-28 无状态规范（移除 initialize/会话；server/discover；MRTR；HTTP 标准头） | 规范 changelog + AAIF + The Register 交叉 | https://aaif.io/blog/mcp-2026-changes-the-rules |

另：Anthropic Claude 5 系（Fable 5.1 / Opus 5.5 / Sonnet 5.5 / Haiku 5.5）型号与命名有系统级信息交叉印证，可信。

## 二、A 级：一手核实来源（subagent 直接抓取）

### 评测
- Terminal-Bench 全榜单数字（官网后端 API 实拉，2026-10-13）：https://www.tbench.ai/blog/terminal-bench-4-0
- Harbor-Index 1.0：https://www.tbench.ai/blog/harbor-index
- TB 完整性政策与作弊案例：https://www.tbench.ai/blog/leaderboard-integrity-update
- OpenAI 弃用 SWE-bench Verified 原文（Playwright 实读）
- Cursor reward hacking 审计：https://cursor.com/blog/reward-hacking-coding-benchmarks
- 腾讯 107 天评测平台复盘全文：https://news.qq.com/rain/a/20260827A0ACFF00

### 沙箱
- E2B / Daytona / Modal / Vercel 定价页；Cloudflare Sandbox 安全文档；Fly.io 对比文
- Claude Code on the web 安全模型（凭证代理持有原文）：https://code.claude.com/docs/en/claude-code-on-the-web
- Copilot agent firewall 文档；K8s agent-sandbox 文档：https://kubernetes-sigs.github.io/agent-sandbox/

### 上下文/协议
- Anthropic 三篇工程博客（context engineering / writing tools / advanced tool use）：anthropic.com/engineering
- Cursor 三篇官方博客：cursor.com/blog（dynamic-context-discovery / secure-codebase-indexing / fast-regex-search）
- Claude Code 大仓文档：https://code.claude.com/docs/en/large-codebases
- MCP 规范 changelog：https://modelcontextprotocol.io/specification/2026-07-28/changelog
- A2A 官方博客（加入 AAIF）；ACP 文档：https://agentclientprotocol.com
- Cognition SWE-grep：https://cognition.ai/blog/swe-grep

### 安全/治理
- GitHub Changelog（Agent control plane 2026-02-26；managed permissions 2026-09-09）
- Anthropic Enterprise Frontier Safeguards 公告；cursor.com/security
- OTel GenAI semconv 仓库：https://github.com/open-telemetry/semantic-conventions-genai

### 学术/独立评测
- GrepRAG：https://arxiv.org/abs/2601.23254 （ISSTA 2026）
- ETH AGENTbench（AGENTS.md 评测）：https://arxiv.org/abs/2602.11988
- SoK（prompt injection 攻击面）：arXiv 2601.17548
- reward hack 量化：arXiv 2606.16062；统计显著性：arXiv 2609.17394；SandboxEscapeBench：arXiv 2603.02277
- METR 更新（2026-02-24）：https://metr.org/blog/2026-02-24-uplift-update/ ；DORA：https://dora.dev

## 三、B 级：专业媒体/分析机构（可引用，重大数字回源）

Artificial Analysis（经 TechRepublic/amplifying.ai 转述）、CSIS/CSA Labs 白皮书、InfoQ、The Register、Security Boulevard、InfoWorld、Elastic/New Relic/LangChain 调研、Accenture AI Tokenomics 报告、Northflank 指南、Fly.io 博文。

## 四、C 级：已知低置信条目（引用前必须回源）

| 条目 | 问题 |
|---|---|
| Haiku 5.5 定价 $0.10/$0.50 | 来自厂商向博客转述，Anthropic 官方定价页未直接复核 |
| Snyk ToxicSkills 精确比例（36.8%/13.4%） | 单源，未交叉 |
| 「93% 权限提示被放行」 | 弱来源，仅作趋势指示 |
| SWE-bench Pro V2 各项数字（642 题、公开/私有分差等） | scale.com 被 Cloudflare 拦截，未能一手复验 |
| OpenAI Codex 沙箱架构细节（Cloud Hypervisor/快照/路由） | 早期读到的工程分享，复验被 403 拦截 |
| GKE Agent Sandbox 宣称指标（300 沙箱/s 等） | 厂商口径 |
| Meta「Muse Glimmer」重新开源 | 单源，可信度低 |
| 各家 ARR / Fortune 500 渗透率 | 聚合站点，口径混乱 |
| LangGraph「2.0」（2026-02） | 仅博客类来源，官方公告未确认 |
| Langfuse 被 ClickHouse 收购 | 背景信息，未复验 |
| ~~HarnessTax「$0.08 vs $1.86」~~ | 2026-10-13 一手核查未找到该数字，已从全部文档移除；HarnessTax 一手数据（97.8%/96.7%、$1.33/$0.67 等）见 [01](01-models-and-orchestration.md) |

## 五、已知信息缺口（如需继续深挖）

- Cursor 向量库/分块细节（仅第三方披露，官方未确认 Turbopuffer）
- Copilot 索引的 ANN 与重排细节（官方未公开）
- Devin 索引内部架构（无公开文档）
- A2A v1.0.1 与 ACP v2 的最新推进（需跟踪官方 release notes）
- MCP Registry 的 GA 时间（官方未承诺）
- Anthropic 官方定价页对 5.5 世代各型号的逐项复核

## 六、维护建议

1. 本领域以周为单位变化：**超过 1 个月的引用，先查各节正文的来源链接是否已更新**
2. 数字冲突时：一手 > 独立 > 三方 > 厂商 > 二手
3. 榜单类数字（Terminal-Bench、Harbor、SWE-bench）**永远回官方源**——本次调研中搜索引擎摘要曾给出与官方 API 完全不符的 Terminal-Bench 数字
4. 新增结论请沿用标签体系；回源核实过的【二手】升级为【一手】并注明核验时间
