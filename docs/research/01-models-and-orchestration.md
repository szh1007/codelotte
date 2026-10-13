# 01 模型层与 Agent 编排

> 信息截止 2026-10-13 ｜ 标签：`【一手】`官方文档/原文、`【三方】`独立媒体/研究、`【厂商】`厂商自述、`【二手】`聚合低置信、`【待核验】`单源待证

## 一、基座模型层

### 1.1 闭源三强现役型号（2026-10）

| 厂商 | 型号 | 发布 | 输入/输出价（每 M token） | 上下文 | agentic 定位 |
|---|---|---|---|---|---|
| Anthropic | Fable 5.1（前沿档） | 2026-09 | $10 / $50（缓存读 $0.25） | 1M | 最强长程 agent；自适应思考常开 |
| Anthropic | Opus 5.5 | 2026-09 | $4 / $20（缓存读 $0.20） | 1M | 复杂开放任务第一梯队 |
| Anthropic | Sonnet 5.5 | 2026-09 | $2 / $10 | 1M | 默认 high effort；比 Opus 快 30%+ |
| Anthropic | Haiku 5.5 | 2026-10 | ~$0.10 / $0.50【待核验】 | 1M | 走量档 |
| OpenAI | GPT-6 Astra（旗舰） | 2026-09 | $10 / $50（>272K 输入重定价） | ~1.05M | computer use 最强（OSWorld 2.0 72.6%） |
| OpenAI | GPT-6.1 Sol（Codex 默认） | 2026-09-29 | $2 / $10（缓存输入 $0.10） | 1M | DeepSWE v1.1 比 GPT-6 Sol +6.4 分 |
| Google | Gemini 4 Argon | 2026-09-30 | ~$2 / $10（推广价） | ≥1M | DeepSWE 自报最高，但 Terminal-Bench 4.0 仅 57.4%【厂商口径】 |
| Google | Gemini 3.7 Flash | 2026-08 | $0.75 / $3.75（2027-01 翻倍） | 1M | 性价比工作马 |

**Anthropic 5.5 世代迁移是破坏性的**（迁移前必读，【一手】）：
- `tool_choice: "required"/"any"/指定工具` 全部移除（返回 400），改用 `auto` + 工具 `strict: true`
- 工具间文本改放 thinking block（需 `thinking.display: "updates"` beta 才能流式可见）
- thinking block 与模型/会话/账号绑定，跨 Opus/Sonnet 5.5 路由会**静默丢弃**
- `temperature/top_p/top_k` 非默认值被拒；最小可缓存前缀降至 512 token（Opus 5 起）

### 1.2 独立评测（区分厂商宣传）

Artificial Analysis Coding Agent Index v1.5（2026-10-07，衡量「模型 + harness」完整系统）：

| 排名 | 组合 | 分数 | 每任务成本 / 耗时 |
|---|---|---|---|
| 1 | Claude Code + Sonnet 5.5 (max) | 68.4 | $14.19 / ~1.5h（27.7M token） |
| 2 | Claude Code + Opus 5.5 (max) | 66.0 | — |
| 3 | Antigravity CLI + Gemini 4 Argon (high) | ~63.8 | — |
| 4 | Codex + GPT-6.1 Sol (xhigh) | 62.9–63 | **$1.04 / 15.5min（3.2M token）** |

关键结论：
- Claude Code 的领先**主要来自默认高 effort**；拉平到同档 xhigh 时与 Codex 同为 63 分，成本差约 13 倍
- Sonnet 5.5 用默认 medium effort 只有 ~46 分——effort 档位对结果影响巨大
- 组件分：Codex 赢 DeepSWE v1.1（73% vs 72%），Claude Code 赢 Terminal-Bench 4.0（66% vs 55%）与 SWE-Atlas-QnA（67% vs 61%）
- SWE-bench Verified 已饱和（Opus 5 达 96–97%），不再有区分度

### 1.3 开源 / 可自部署

| 模型 | 规模/架构 | 许可 | 上下文 | 关键成绩（混合口径） |
|---|---|---|---|---|
| DeepSeek V4-Pro | 1.6T 总参 / 49B 激活 | MIT | 1M | SWE-bench Verified 80.6% |
| GLM-5.2（智谱） | ~750B / ~40B 激活 | MIT | 1M | AA Intelligence 开源第一；SWE-bench Pro 62.1% |
| Qwen3.5-397B-A17B | 397B / 17B 激活，原生多模态 | Apache 2.0 | 262K | LiveCodeBench v6 ~83 |
| Kimi K3（Moonshot） | 2.8T MoE / ~104B 激活 | 修改版 MIT | 1M | SWE-Marathon #1、Frontend Arena #1 |
| MiniMax M3 | 428B / 23B 激活 | 社区许可（非 MIT） | 1M | SWE-bench Pro 59.0% |
| Llama 系 | 停在 2025-04 | — | — | 已停止迭代，选型表可移除 |

- 头部开源已进入 60–76% 区间，落后闭源头部约 3–6 个月
- **Harness 口径警告**：同一 Qwen3-Coder 在 mini-SWE-agent harness 下 SWE-bench Verified 只有 55.4%，换 harness 后 69.6%——跨模型比较必须同 harness【三方】

### 1.4 自部署经济性（2026 实操结论）

- 参考栈：K8s + 可缩容 GPU 池 + vLLM + KubeAI/Ray Serve + LiteLLM 网关（按 agent 发 key、预算、限流）
- **盈亏平衡点 ≈ 10 亿 token/月**；多数团队低于此值，托管 API 更划算
- 硬件参考：8×H200 云租 $21–36k/月，自持摊薄 $3–5k/月；AMD MI300X 单卡可跑 Qwen3-Coder-Next FP8 256K
- 自部署真实理由排序：**合规/数据驻留 > 模型钉版 > 持续高吞吐；省钱很少是首要理由**
- 战略信号：DeepSeek V4 训练即用昇腾（首批不依赖 Nvidia 的前沿模型）【三方】

### 1.5 推理引擎（2026-10）

| 维度 | vLLM v0.31.0 | SGLang v0.5.21 |
|---|---|---|
| 缓存机制 | PagedAttention + 前缀缓存（opt-in） | RadixAttention（默认开；≥60% 前缀重叠时 TTFT 低 30–44%） |
| 结构化输出 | xgrammar，CPU 侧掩码，batch≥8 吞吐退化 | 掩码与 GPU 前向重叠，batch≥32 基本零开销 |
| 其他 | 投机解码（EAGLE3）成熟、Blackwell 支持最先 | 多 LoRA（50+）、分离式 serving（Mooncake/NIXL） |
| 已知风险 | v0.30/0.31 SM120 + prefix cache + NVFP4 输出损坏 bug（建议暂留 v0.29） | — |

选型规则：前缀重叠 >60% 选 SGLang，否则 vLLM 是安全默认；两者各约两周一个版本，收敛趋势明显。

### 1.6 成本三杠杆（影响最大，优先做）

1. **Prompt caching**：缓存读约 0.1x 原价；真实案例：50K 前缀复用 1000 次，Sonnet 成本 $150 → $15.17（缓存）→ $7.59（叠加 Batch），**-95%**
2. **Batch API**：三大厂均 50% off，可与缓存叠加
3. **effort 与模型分层**：thinking token 按输出计费；`output_config.effort` / `reasoning.effort` 降档可大幅降本（但会掉分，见 §1.2）
- 注意：prompt cache 以「模型 + 前缀」为键，**切模型即 cache miss**；多 agent 场景下「路由到便宜模型」的决策必须考虑缓存失效成本

## 二、Agent 编排框架

### 2.1 主流方案对比（2026-10）

| 方案 | 版本/状态 | 定位与差异点 | 短板 |
|---|---|---|---|
| **自持精简 loop** | — | 2026 主流答案：核心循环自写，控制成本与上下文策略 | 状态/可观测需自己补 |
| **Claude Agent SDK** | v0.1.59 | subagents（per-agent 模型/工具/后台/maxTurns）、全套 hooks（PreToolUse/PreCompact/PermissionRequest 等）、4 种 MCP 传输（含 in-process）、审批门 | 深度绑定 Claude；托管档 Managed Agents（$0.08/session-hour） |
| **OpenAI Agents SDK** | 0.14.x | 原语：Agents/Handoffs/Guardrails/Sessions/Tracing；2026-04 加沙箱、MCP、AGENTS.md；可接 100+ 非 OpenAI 模型 | AgentKit 的 Builder/Evals 2026-11-30 关停；无内置持久状态 |
| **LangGraph** | 1.0（2025-10） | 生产默认：checkpointer 持久状态、time-travel 调试、interrupt 人审；官方称 9000 万月下载、35% Fortune 500 | 学习曲线陡；抽象层厚（harness tax 研究中常被点名成本高） |
| **Microsoft Agent Framework** | 1.0 GA（2026-04） | AutoGen + Semantic Kernel 合并 | 生态碎片化（AutoGen 已进维护模式） |
| **Google ADK** | 2.x | workflow runtime（fan-out/重试/HITL）、A2A 原生、内置 eval、Cloud Run/GKE 部署 | 离开 GCP 价值骤减 |
| **Mastra** | 1.0（2026-01） | TS 原生全家桶 + Model Router（3300+ 模型）+ Studio | 生产案例少于 LangGraph |
| **CrewAI** | 1.10+ | 角色/任务 crew 隐喻，上手最快；企业版 AMP（SSO/RBAC/VPC） | 粗粒度错误处理；3–5x token 开销；常见「原型 CrewAI → 生产迁 LangGraph」路径 |

### 2.2 自建 loop vs 用框架（2026 主流观点）

- **主流共识 = 混合**：平台组件（网关/eval/可观测/部署）买，领域 agent 自己建
- HarnessTax 硬数据（UC Berkeley Sky Computing，2026-09，harnesstax.github.io）：Fable 5 在 SWE-bench Lite 上 Claude Code 97.8% @ $1.33/次 vs **pi 96.7% @ $0.67**；GPT-5.6 Sol 在 Terminal-Bench 2.0 上 **pi 83.3% @ $0.42** vs Codex 78.9% @ $0.76；机制之一是 Claude Code 平均初始上下文 > pi 的 10 倍（harness 每轮重读系统提示 + 工具目录）。⚠️ 样本小（30 题 ×3）且有复跑反驳（KISS Sorcar 报 pi 68.9%），详见 [README](README.md#1-harness-与模型同等重要甚至更决定成本)
- 反方论据（MongoDB）：编排层尚未收敛，「2024 年自建编排层的团队 2026 年正在重写」；eval 是轨迹级独立系统，不是一个 sprint 的活
- 落地数据（LangChain《State of Agent Engineering》2026-06）：57.3% 团队有 agent 在生产（万人以上企业 67%）；**头号障碍是质量（32%）而非成本**；89% 有可观测、仅 52.4% 做离线 eval
- 反面数据：Camunda 调研 71% 组织在用 agent 但仅 11% 到生产；Gartner 预测 40% agentic 项目 2027 年前取消【三方】

### 2.3 Sub-agent / 多 agent 采用

- 生产形态 = **orchestrator + subagents**（各自独立上下文窗口、并行执行），而非对等 swarm
- Claude Code Agent Teams（2026-07 起 research preview，默认关闭）：lead + 3–5 个独立 session；**成本 2.5–4x**；社区评价「指向未来但尚未生产级」【一手文档】
- Kimi Agent Swarm：K2.6 扩到 300 subagent / 4000+ 工具调用，声称比单 agent 快 ~4.5x【厂商】
- MuleSoft 报告并行 sub-agent 延迟下降 26.5–42.1%【厂商】
- 典型失败模式：对话不终止、无共享状态原语导致命令竞争/状态幻觉、「两个 agent 是双倍故障而非双倍吞吐」

### 2.4 长任务执行与上下文压缩

- **厂商 API**：Anthropic Context Compaction（beta，阈值触发自动摘要，宣称 100 轮 web 搜索 token 削减 84%）；OpenAI Agents SDK compaction session；Google ADK interval summarization
- **工程模式**（多来源收敛）：
  1. 在任务/commit 边界压缩，而非仅按 token 阈值
  2. 保留可寻址原件（git SHA、hash ID）实现「可恢复压缩」
  3. 上下文利用率控制在 40–60%（context rot 在 25% 填充率起就影响所有模型）
  4. 硬约束钉在 summarizer 之外（ConstraintRot 实验：压缩丢策略导致 38% 违规率）
  5. 压缩前先落盘（write-before-compaction）；摘要由原始记录生成
  6. 用 subagent 隔离探索性搜索
  7. **缓存命中率是生产 agent 的最重要指标**（缓存输入便宜 10x；顶部压缩会作废整条 cache）
- 长程评测警示：MirrorCode 单次运行 19 天 / $2600——短 benchmark 严重低估真实工程能力

## 主要来源

- Anthropic 模型文档与定价（platform.claude.com）、OpenRouter 5.5 迁移指南【一手】
- Artificial Analysis Coding Agent Index v1.5 经 TechRepublic 转述（2026-10）【三方】
- HarnessTax（UC Berkeley Sky Computing，2026-09）：https://harnesstax.github.io 【独立】
- MongoDB《The Case Against Building Your Own Agent Platform》【三方】
- LangChain State of Agent Engineering（2026-06）【三方】
- Claude Code Agent Teams 官方文档：https://code.claude.com/docs/en/agent-teams 【一手】
- Qovery 开源模型自部署四层栈、GLM-5.2 自托管成本分析【三方】
