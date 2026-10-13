# 05 安全治理、可观测性与平台化

> 信息截止 2026-10-13 ｜ 标签：`【一手】`官方文档/原文、`【独立】`学术/独立研究、`【三方】`专业媒体、`【厂商】`厂商自述、`【二手】`聚合低置信（数字请回源）

## 一、Agent 权限模型（企业落地门槛）

### 1.1 主流设计：分层强制 + 有界自治（bounded autonomy）

**已收敛的模式**：managed 企业配置（不可被用户弱化）> 项目配置 > 用户配置；**deny > ask > allow** 优先级；沙箱兜底；人类审批只留给越界动作。

| 产品 | 要点 |
|---|---|
| **Claude Code** | 6 种权限模式；deny/ask/allow 分层合并，任一层的 deny 不可被下层覆盖；Bash 参数模式（`Bash(npm *)`）、WebFetch 域名规则；企业网关统一分发 managed settings / hooks / 托管 MCP server；PreToolUse hooks 是确定性拦截点【一手】 |
| **GitHub Copilot** | **Enterprise managed permissions（2026-09-09）**：管理员对 agent 操作（shell、文件读写、网络域名）统一设 blocked / require approval / proceed；managed 限制不可被用户或历史批准弱化【一手】 |
| **GitLab Duo** | 工具治理按 Read/Write/Delete 分类，Always Allow/Ask/Deny，项目→组级联只能更严、fail-closed（已知缺口：CI/CD runner 中的 flows 不受治理）【一手】 |
| **Cursor** | agent loop 内 classifier 自动审查（auto-review），低于风险阈值自动放行；带 Hook 的 JIT 授权（allow/warn/step-up/deny + 审计）【三方/厂商】 |
| **Devin** | 托管部署需明确人工批准；合并门默认仅供参考；企业版 VPC + teamspace 隔离【三方】 |

### 1.2 已知失效模式（设计时直接规避）

- **审批疲劳是公开事实**：有研究称用户放行约 93% 的权限提示，沦为橡皮图章——行业修复方向即 bounded autonomy（沙箱 + allowlist + classifier 处理常规审批，人类只管边界穿越）【二手，数字请回源】
- **CI/headless 场景是最大事故来源**：交互式提示被预授权 allowlist 取代；`Bash(git *)` 类 glob 会放行破坏性命令——**禁止对破坏性动词通配**，搭配 denylist + PreToolUse hook
- **GhostApproval 漏洞（Wiz，2026-07）**：symlink 攻击影响 6 款助手（Amazon Q、Claude Code、Augment、Cursor、Antigravity、Windsurf）；agent 推理已识别危险目标（如 `~/.ssh/authorized_keys`），但审批弹窗隐藏该信息（CWE-451）——**HITL 的审批循环本身可被喂假信息**【三方】
- **旗舰产品也持续爆出沙箱绕过类 CVE**：Claude Code 2026 年多次修复（WebFetch 域名校验缺陷、`cd`/管道命令注入绕过写保护、settings.json 持久化 hook 注入实现沙箱逃逸、路径校验 TOCTOU 等）——没有一劳永逸，需持续打补丁
- **运行时治理新层（2026 集中出现）**：Microsoft Execution Containers（策略在 agent 控制范围之外强制执行）、Varonis Agent Intent-Based Access Control（比对声明意图 vs 实际动作，漂移即告警）、Obot pre-tool-hook 强制（fail-closed allowlist）、Backslash（跨工具 Skills 治理与漂移检测）

## 二、Prompt Injection 与攻击面

### 2.1 结论先行

**Prompt 层过滤被证明不足；行业共识转向 containment over prevention**（OWASP 2026 方向：Minimal Agency、Strong Observability、Deterministic Checkpoints）。

- 系统性度量：SoK（arXiv 2601.17548）梳理 78 篇研究、42 种攻击技术；**自适应策略下对 SOTA 防御成功率 >85%**，18 个受调查防御多数缓解率 <50%【独立】

### 2.2 真实攻击链时间线（压缩版）

| 时间 | 事件 |
|---|---|
| 2025-03 | Rules File Backdoor：`.cursorrules` / copilot-instructions 中不可见 Unicode 注入 |
| 2025-04 | Invariant Labs 首次披露 MCP tool poisoning（含 tool shadowing 与 rug pull） |
| 2025-08/09 | Nx s1ngularity（武器化 AI CLI 搜刮凭证）；Shai-Hulud 蠕虫（500+/796 个 npm 包，窃取 `ANTHROPIC_API_KEY`）；**postmark-mcp 后门**（15 个正常版本后静默 BCC ~15,000 邮件/天） |
| 2026-01/02 | ClawHavoc（恶意 skill 批量投放）；Clinejection（issue 标题注入 → RCE → 缓存投毒 → 发布恶意包）；Snyk ToxicSkills 扫描：3,984 个 skill 中 36.8% 至少 1 个缺陷、13.4% 严重 |
| 2026-05/06 | **Miasma 蠕虫**：在仓库植入 `.claude/` `.gemini/` `.cursor/` `.vscode/` 配置文件（73 个微软 GitHub 仓库下线）；Hades Wave 投毒 37 个 PyPI 包 |
| 2026-07 | **Microsoft GuardFall**：10/11 开源 coding agent（Aider、Cline、Goose、OpenHands、Roo-Code、SWE-agent）可被引号/展开重写绕过硬编码文本过滤，执行破坏性 shell |
| 2026-08 | **CHAINDROP**：蠕虫提交恶意 `.claude/settings.json` 与 `.vscode/tasks.json`，打开仓库或跑一次 Claude Code 即中招 |
| 2026-04 | OX Security：官方 MCP SDK STDIO transport RCE，污染 9/11 MCP registry（详见 [03](03-tool-protocols.md#13-mcp-攻击面)） |

其他向量：记忆投毒（多篇论文报告记忆注入率最高 ~98%）、Gemini/ChatGPT 被诱导推荐假 MCP server 投递窃密程序。

### 2.3 框架与监管

- **OWASP Top 10 for Agentic Applications（ASI01–ASI10）**：Agent Goal Hijack / Tool Misuse / Identity & Privilege Abuse / Agentic Supply Chain / Unexpected Code Execution / Memory & Context Poisoning / Insecure Inter-Agent Comm / Cascading Failures / Human-Agent Trust Exploitation / Rogue Agents
- **OWASP MCP Top 10**（MCP03=工具投毒）；OWASP AISVS（C10 授权、C12 日志）
- NSA AISC MCP 指引（2026-05-20）；Five Eyes agentic AI 采用指引（2026-05-01）；MITRE ATLAS 新增 AML.T0080 Context Poisoning
- **企业落地建议**（Northflank 等）：microVM 隔离、agent PR 强制走 PR gate 并标注 session ID、SIEM 接入审计日志、四阶段铺开

## 三、审计与合规

- **SOC 2**：CC6/CC7.2/CC8.1 直接适用（技术中立——agent 发起的变更需与人类变更同等证据）；审计师新要求：每个 agent 唯一非人类身份（NHI）、人类批准者 ≠ 作者、**日志防篡改且存放于 agent 无法写入之处**；普通 transcript 不够，需绑定代码/策略哈希、由 agent 不可访问的密钥签名、可独立验证【三方】
- **ISO/IEC 42001**：Annex A 控制 **A.6.2.8（AI 系统事件日志记录）为强制项**；企业共识为 **SOC 2 + ISO 42001 双认证**
- **EU AI Act 第 12 条**：高风险系统自动、防篡改记录（高风险义务 2026-08 生效；罚款至 €35M / 7% 营收）
- **产品侧审计能力**：
  - GitHub：审计日志 `actor_is_agent` 标识 + `agent_session.task` 事件，可查近 24h 全部 cloud agent session，日志流式进 SIEM（2026-02 GA）【一手】
  - Claude Code Enterprise：OTel 导出 session/token/cost 指标；Bedrock/Vertex 部署只能靠 OTel push 取数（需 `OTEL_RESOURCE_ATTRIBUTES=user.email=...` 做用户归因）【一手】
  - GitLab：19.2 新增 AI Audit Event Report（beta）；工具治理 fail-closed

## 四、代码/数据路径控制

### 4.1 模型供应商数据政策（2026-10）

| 供应商 | 保留/训练政策要点 |
|---|---|
| **Anthropic** | API 默认 30 天保留、商业数据不用于训练；ZDR 需审批；**2026-06 起 Covered Models（Fable/Mythos 级）强制 30 天保留**（覆盖既有 ZDR 协议）；T&S 标记会话最长 2 年；Claude Code Enterprise 开 ZDR 会禁用服务端功能；因企业反弹推出 **Enterprise Frontier Safeguards（EFS）**：监控日志存于客户自有云账户（S3/Blob/GCS）与客户密钥（2026 秋分阶段，未 GA） |
| **OpenAI** | API 默认 30 天滥用监控；合格企业端点可申请 ZDR；**Codex cloud（托管容器）与 ZDR 不兼容**（本地 CLI/IDE 可用）；Business/Enterprise/Edu 默认不用于训练 |
| **Google** | 无独立 ZDR 品牌；Vertex 支持 ZDR 配置 + 不训练承诺；付费 API 滥用监控窗口可配（7/14/28/55 天）；Grounding 有 carve-out |

**关键含义**：ZDR 已变成 **per-model 属性**——法院保全令可覆盖删除承诺（仅 ZDR 客户例外）；企业采购必须按「模型清单 + 路径（API/Bedrock/Vertex）」审批，不能按「产品」审批。

### 4.2 部署路径（SaaS / VPC / 混合）

主流产品均无原生 air-gapped GA；实践是「agent 在厂商云、执行环境在企业边界内」：

| 形态 | 代表 | 要点 |
|---|---|---|
| 云托管落 VPC | Claude Code 经 Bedrock/Vertex/Foundry | 继承 IAM/CloudTrail/VPC 配置；企业版含集中 managed settings、SSO/SCIM（~$150/座/月） |
| 云 agent + 自托管执行 | Coder Agent Relay（2026-09） | 厂商托管 agent + Coder workspace 内自托管执行，代码/凭证留边界内，含身份归因 |
| VPC 内自托管推理 | Cast AI Kimchi | 自有云 VPC 内自跑编码模型；盈亏平衡约 $3–5k/月推理支出 |
| 全 air-gapped | Factory Private（2026-09，Private Preview）；GitLab Duo Self-Hosted（offline，GA） | BYOK 模型、网内 OTel collector |

## 五、可观测性

### 5.1 OpenTelemetry GenAI semantic conventions

- **现状（2026-10）**：所有 GenAI span/metric/attribute 均为 **Development 状态**（低于 Alpha，「SHOULD NOT be used in production」，可无通知变更）；2026-06 起迁至独立仓库 `open-telemetry/semantic-conventions-genai`，从 main 直接发布、无 tag；稳定化无时间表
- **Agent span 模型**：操作含 `create_agent` / `invoke_agent` / `execute_tool` / `plan` / memory 操作；span 命名 `{operation} {gen_ai.agent.name}`；`gen_ai.system` 弃用改 `gen_ai.provider.name`；典型 trace 树：session → invoke_agent → chat + execute_tool → 子 agent
- **标准盲区**：semconv 有意不覆盖评估结论、agent 身份/授权、数据敏感度分级——须外部 join
- **实务告警**：2026 各版本 attribute 改名已多次破坏 instrumentation——**埋点层 pin schema 版本、属性字符串置于映射层**
- 采用信号：New Relic 2026（n=2,575）35% 主动监控生产 AI agent、24.6% 完全无监控；LangChain 报告 89% 有 agent 可观测、62% 有完整 step/tool-call tracing

### 5.2 工具选型（市场已分化，非收敛）

| 工具 | 定位 | 注意 |
|---|---|---|
| Langfuse | OSS（MIT）、唯一有真实自托管能力的 | 计费按 trace+observation+score 单元 |
| LangSmith | LangChain/LangGraph 栈追踪最深 | 闭源 SaaS；非 LangChain 栈最弱 |
| Braintrust | eval 优先（生产 trace→数据集→CI 回归门） | 按 score 计量；SaaS-only |
| Datadog LLM Obs | 已有 Datadog 栈时占优 | **按 LLM span 计费**，多轮 agent 成本随话痨度上升 |

**共性架构**：OTel 原生 tracing 层 + 独立 eval/质量层；tracer 是事后视角，部分团队额外加实时逐轮分类层（循环/越狱检测）回写同一 OTel span。

## 六、成本治理

- **归因先行**：showback 第 2 级必须能与账单对账（tagged + 显式 UNTAGGED 桶；untagged >5% 先修 tagging）；第 3 级换算 per-outcome 单元成本（例：$4.18/merged PR）；>90% 支出一一对应所有者后再推 chargeback
- **关键陷阱「cache writer pays for everyone」**：朴素 caller-pays 归因让预热共享 prompt cache 的团队单次成本虚高约 12.5 倍，激励其关闭缓存、公司总账单反升约 20%；正确做法是把共享前缀视为平台成本再按调用摊销
- **量化参考**：Accenture 报告完整 chargeback 下每 $1 token 支出可证明价值从 ~20¢ 升至 ~32¢；某企业 1 万座模拟中路由回收 13–21% 模型支出；Uber 2026 年将员工 AI 支出上限定为 $1,500/人/月（agentic 任务 token 消耗是代码问答的 ~1000 倍，同任务运行间方差达 30 倍）
- **执行层**：网关级 per-key 预算（超限直接拒绝而非事后告警）；per-agent/per-user/per-team 归因；上下文压缩；双表预算（席位 + 用量）、80% 告警

## 七、平台化与集成

### 7.1 触发面与集成

- **Intake surfaces**：Slack / Linear / Jira / GitHub / GitLab / Teams 中 `@agent` 提及触发，结果回写原 surface（PR 关联 issue）；Codegen 等支持「Checks Auto-fixer」监控 CI 失败自动修复
- **安全要点「two-plane rule」**：intake 访问 ≠ 代码访问
- **CI/CD**：`anthropics/claude-code-action` 做 issue→PR 与逐 PR review；Copilot agentic autofix 指派 Code Quality 发现
- **Agent HQ（GitHub，2026-02）**：把多厂商 agent（Copilot/Claude/Codex）纳入 repository workflows，企业控制允许的 agent/模型；伴随争议：低质量 AI 生成 PR 泛滥引发维护者反弹（curl 因此关闭 bug bounty）
- **GitLab Duo Agent Platform**：2026-01 GA；内置 agent + 自定义 agent（AI Catalog）+ **外部 agent（Claude Code、Codex CLI）**；计费转 per-request Credits 池
- **IDE**：VS Code Agent Host（受企业 managed permissions 覆盖）、各 IDE 插件；IDE 安全是独立议题（IDEsaster：30+ 漏洞、24 个 CVE）

### 7.2 企业产品格局（2026-10，定价为检索时点）

| 产品 | 定价参考 | 部署 | 治理/合规要点 |
|---|---|---|---|
| Claude Code Enterprise | ~$150/座/月（5 座起） | SaaS + Bedrock/Vertex/Foundry | managed settings、OTel、SSO/SCIM、ZDR 申请制、EFS |
| GitHub Copilot Enterprise | 按座 + premium requests | SaaS（GHE 集成） | AI Controls/agent control plane、managed permissions、`actor_is_agent` 审计、MCP allowlist |
| Cursor | Teams $40/座/月；Enterprise 定制定价 | SaaS only | SOC 2 II / ISO 27001 / ISO 42001 / AIUC-1；Privacy Mode 强制；**被 SpaceX 以 $60B 收购（2026-06-16 宣布）** |
| Devin | ACU 计费，企业单价不公开 | SaaS + Enterprise VPC | SSO、teamspace 隔离；自托管处维护模式 |
| Factory（Droid） | 未公开标准价 | Managed / Hybrid / Air-gapped（preview） | BYOK、permission rules、Droid Shield、客户自有 OTel |
| Amp（Sourcegraph 分拆） | Individual ~$20/月；Enterprise 激活费 + 用量 | CLI + IDE + cloud orbs | SSO/SCIM、审计日志、ZDR、MCP allowlist |
| GitLab Duo | per-request Credits（Self-Managed 按座） | SaaS + Self-Managed + offline | 工具治理 fail-closed、AI Audit Report |

商业模式共性：从「按座」转向「**座 + 用量双层**」；治理功能（SSO/SCIM/审计/驻留/ZDR/MCP 控制）几乎全部锁在 Enterprise 档。市场：Gartner 2026-05 首评该品类 MQ（Leaders 由 AI 原生厂商占据，AWS/GCP 被挤出 Leader 象限；MCP 支持列为硬性要求）；前三名占收入 ~75–80%。

## 八、跨领域研判

1. 治理重心 2026 年从「静态权限」转向「运行时强制 + 意图校验」（pre-tool hook、沙箱、intent-based access control、跨工具治理层集中出现）
2. Prompt injection 无银弹：防线必须在沙箱、凭证、供应链与行为监控层
3. 数据政策分化为 per-model：采购按「模型清单 + 路径」审批
4. 可观测性标准「事实可用但未稳定」：tracing 层与 eval 层分离成默认架构
5. 成本治理的最大坑是归因语义（cache writer 陷阱）而非工具
6. 部署趋势 = agent 与执行平面分离（SaaS 控制面 + 边界内执行 + K8s sandbox 原语）
7. 风险：agent 生成 PR 泛滥正在引发开源生态反噬（质量治理议题）

## 主要来源

- GitHub Changelog（AI Controls 2026-02-26 / managed permissions 2026-09-09）【一手】
- Anthropic EFS 公告与保留政策、Claude Code gateway 配置文档【一手】
- OWASP Agentic Top 10 / MCP Top 10 / AISVS；NSA MCP 指南（2026-05-20）【一手/三方】
- SoK（arXiv 2601.17548）；AAA 论文（Zenodo 19743420）【独立】
- Cursor / Cursor 安全页：https://cursor.com/security 【一手】
- Gartner MQ 报道：https://github.blog/ai-and-ml/github-copilot/github-recognized-as-a-leader-in-the-gartner-magic-quadrant-for-enterprise-ai-coding-agents-for-the-third-year-in-a-row/ 【三方】
- SpaceX 收购 Cursor：https://fortune.com/2026/06/17/spacex-acquire-cursor-60-billion/ 【三方】
- OTel GenAI semconv 仓库：https://github.com/open-telemetry/semantic-conventions-genai 【一手】
- Accenture AI Tokenomics 报告；Uber 预算上限报道【三方】
