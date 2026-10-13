# 03 工具协议与工具生态

> 信息截止 2026-10-13 ｜ 标签：`【一手】`官方文档/规范原文、`【独立】`学术/独立研究、`【三方】`专业媒体、`【厂商】`厂商自述、`【二手】`低置信

## 一、MCP（Model Context Protocol）现状

### 1.1 治理与版本

- **治理**：2025-12 前后 Anthropic 将 MCP 移交 **AAIF（Agentic AI Foundation，Linux Foundation 旗下）**，规范进入正式弃用生命周期（激活→弃用→移除至少 12 个月）【一手/三方】
- **版本**：
  - stable **2025-11-25**（含 OIDC Discovery、增量 scope consent）
  - **latest 2026-07-28（无状态大改版）**——见下
- **官方 Registry**（registry.modelcontextprotocol.io）：官方页面明示**仍为 preview，GA 前可能破坏性变更或数据重置**；metadata-only、reverse-DNS 命名空间、**明确不支持私有 server**，建议企业自建私有 registry 并实现其 OpenAPI【一手】

### 1.2 2026-07-28 无状态改版要点（当前 latest）

| 变更 | 内容 |
|---|---|
| 移除会话 | 删除 `initialize`/`initialized` 握手与 `Mcp-Session-Id`；每次请求在 `_meta` 自包含版本与能力（SEP-2567/2575） |
| 服务发现 | 新增可选 `server/discover` RPC 宣告版本/能力/身份（服务端应实现、客户端可选） |
| 服务端回问 | MRTR（Multi Round-Trip Requests，SEP-2322）取代 elicitation/sampling/roots：返回 `input_required`，客户端带 `inputResponses` 重试 |
| 传输 | HTTP 头镜像 JSON-RPC 字段（`Mcp-Method`/`Mcp-Name`/`Mcp-Param-*`），错误分层（真实 HTTP 状态码）；移除 ping、SSE 续传 |
| 缓存 | 列表/读结果带 `ttlMs`/`cacheScope`，工具顺序确定化 |
| 扩展机制 | 版本化 reverse-DNS 扩展（如 tasks、MCP Apps UI）；Roots/Sampling/Logging/DCR 弃用（12 个月窗口） |
| 授权硬化 | 6 个 SEP 对齐生产 OAuth 2.0/OIDC；企业托管授权（Identity Assertion Authorization Grant）；禁止 token passthrough，推荐 RFC 8693 |
| 影响 | 无粘性会话 → 可部署在 serverless/edge/K8s 标准 LB 之后；状态以显式「handle」工具参数传递 |

采用度量级：约 400M 月 SDK 下载；Tier 1 SDK（TS/Python/Go/C#）发布日同步上线。

### 1.3 MCP 攻击面（详情时间线见 [05](05-security-and-platform.md#二prompt-injection与攻击面)）

- **根因**：MCP 把「工具描述与工具输出」作为模型可信指令消费，**传统 prompt 过滤不覆盖元数据层投毒**
- 关键实测：**MCPTox 基准（2026-04）**——45 个真实 MCP server × 20 个 LLM，工具投毒平均攻击成功率 **36.5%**（单模型最高 72.8%）；2026-01~04 披露 40+ MCP 相关 CVE【独立】
- 真实事件：postmark-mcp 后门（15 个正常版本后 v1.0.16 静默 BCC 攻击者域名）；OX Security 发现官方 SDK STDIO transport RCE（约 150M 下载 / 最高 20 万安装受影响）；MCPoison（Cursor 配置交换漏洞 CVE-2025-54136）；Azure DevOps MCP CVE-2026-32211（CVSS 9.1）
- 生态统计：41% 注册 server 零认证；2026-03 扫描 5,618 个 server 仅 2.5% 验证安全【三方】
- **防御共识**：注册表来源验证 + 运行时拦截（pre-tool hook、fail-closed allowlist）+ 沙箱（microVM/最小权限）+ **工具定义哈希固定（防 rug pull）** + 对工具定义变更检测 + 逐调用日志
- 治理框架：OWASP MCP Top 10（MCP03=Tool Poisoning via Description Injection，Phase 3 beta）、NSA《MCP: Security Design Considerations》（2026-05-20，定性 MCP "flexible and underspecified"）、CSA《Sandboxing Agentic AI》（2026-05-30）

## 二、互操作标准矩阵（四件套 + 一层）

| 标准 | 定位 | 2026 状态 |
|---|---|---|
| **MCP** | agent → 工具/数据（纵向） | 事实标准；2026-07-28 无状态版；AAIF 治理 |
| **A2A** | agent ↔ agent（横向） | v1.0（2026-03，多绑定/多租户/签名 Agent Card）；2026-08-27 加入 AAIF（Growth Stage）；官方称 150+ 组织、5 语言 SDK；Google Cloud / Azure AI Foundry / Bedrock AgentCore 原生支持；IBM ACP 已并入；AP2 支付扩展 |
| **AGENTS.md** | 项目知识 | AAIF 治理；官方自报 60,000+ 项目、23–25+ 工具；**Claude Code 2.1.277（2026-09-18）加入 fallback**（无 CLAUDE.md 时读取）；实测数据集：38% 仓库带 agent 指令文件，AGENTS.md(217) 已超 CLAUDE.md(179) |
| **Agent Skills** | 能力包（SKILL.md + 渐进披露） | Anthropic 2025-10 发布、2025-12 开放规范 v1.0（agentskills.io）；至 2026-03 被 27–32 个工具采纳；Claude Code 已用 `.claude/skills/` 取代 commands |
| **ACP**（Agent Client Protocol） | editor ↔ agent（「LSP for agents」） | Zed + JetBrains 共建；v1 稳定、v2 草案；本地 stdio JSON-RPC / 远程 HTTP-WS（WIP）；有 ACP Registry；Copilot CLI 支持 `--acp` |

共识：**MCP 管内（agent→工具），A2A 管外（agent↔agent），生产要同时上**；治理成熟度仍是主要拦路虎（仅 7–8% 企业有成熟 agent 治理）【三方】。

## 三、工具经济学（2026 年新显学）

### 3.1 工具定义的 token 成本（Anthropic 官方实测，【一手】）

| 事实 | 数据 |
|---|---|
| 常见 MCP server 工具定义规模 | GitHub 35 工具 ≈26K tokens；Slack 11 ≈21K；Jira ≈17K；5 个 server 58 工具 ≈55K tokens 起步 |
| 见过的最坏案例 | 优化前 134K tokens 常驻 |
| 失败模式 | 多为选错工具/参数，尤其是名字相近的工具 |

### 3.2 Tool Search（`defer_loading`）方案

- 工具标 `defer_loading: true`，仅保留 ~500 tokens 的搜索工具常驻；按需装配 3–5 个工具（~3K tokens）
- 总成本 ~8.7K vs 传统 ~72K+，**节省 85%**；工具选择准确率 **Opus 4: 49%→74%，Opus 4.5: 79.5%→88.1%**
- 兼容 prompt caching；提供 regex 与 BM25 两种搜索工具；`mcp_toolset` 可按 server 粒度 defer
- 启用阈值（官方口径）：工具定义 >10K tokens，或工具数 >10 且有选择困难时
- Claude Code / Agent SDK：`ENABLE_TOOL_SEARCH=auto` 默认在可延迟定义达上下文窗口 10% 时启用

### 3.3 其他编排优化

- **Programmatic Tool Calling**（`code_execution`，`allowed_callers`）：让模型写 Python 编排多工具，中间结果不进上下文——复杂研究任务 token 43,588→27,297（**-37%**），减少 19+ 次推理往返
- **Cursor 对照方案**：不做扁平 tool search，而是**每个 MCP server 一个文件夹**同步工具描述，模型用 rg/jq 按需查——A/B 测 token **-46.9%**；「文件是最简单的动态上下文原语」
- **Tool Use Examples**：JSON Schema 表达不了使用模式，用规范化的调用示例补

## 四、工具设计最佳实践（Anthropic 两篇官方博客为行业基准）

1. 选对工具边界；**命名空间化避免重叠**（名字相近工具是选错的高发区）
2. 返回有意义的上下文、token 高效响应（长输出写文件，别灌进上下文）
3. **把工具描述当 prompt 工程打磨**，用 eval 驱动迭代（留出集评测）
4. 复杂使用模式用 examples 表达
5. 工具数量上去了就上 defer/search（§3）

## 主要来源

- MCP 规范与 changelog：https://modelcontextprotocol.io/specification/2026-07-28/changelog 【一手】
- AAIF《MCP 2026 changes the rules》：https://aaif.io/blog/mcp-2026-changes-the-rules 【一手】
- A2A 加入 AAIF：https://a2a-protocol.org （2026-08-27 博文）【一手】
- Anthropic《Introducing advanced tool use》（2025-11-24）：https://www.anthropic.com/engineering/advanced-tool-use 【一手】
- Anthropic《Writing effective tools for agents》（2025-09-11）【一手】
- Cursor 工具文件夹方案（2026-01-06）：https://cursor.com/blog/dynamic-context-discovery 【一手】
- MCPTox 基准（2026-04）与 OWASP MCP Top 10【独立/三方】
- CSA《AI Coding Agents as Attack Surface》(2026-06)：https://labs.cloudsecurityalliance.org/research/ai-coding-agent-attack-surface-mcp-repository-poisoning-v1-0/ 【三方】
