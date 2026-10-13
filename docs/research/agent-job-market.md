# Agent 开发岗位招聘与面试调研（2026-10）

> 2026-10-13 调研 ｜ 方法：WebSearch + curl 直抓一手页面（WebFetch 被拦、firecrawl 额度耗尽）｜ 用于：codelotte 求职作品的需求基线

## 来源分级（先看这个）

| 等级 | 含义 | 例子 |
|---|---|---|
| **A 一手**（当日抓取原文） | curl 拿到的活页面 | Glean 三个在招 JD、agentic-engineering-jobs.com 市场数据（534 listings）、Exponent/UPenn 面试指南、字节面经原文（llm-master 仓库） |
| **B 二手汇总**（含原文摘录） | 第三方整理、自标证据等级 | harrisliangsu/ai-agent-engineer-handbook（14 条国内 JD 原文摘录） |
| **C 二手转述**（仅搜索摘要） | 未见原文 | 智联/脉脉市场数据、阿里/美团/百度 JD 细节 |
| **D 商业营销性质** | 培训机构/面试产品/付费社区 | 方向可参考，**数字不可作硬事实** |

---

## 0. 一句话结论

2026 年 Agent 岗已从「会调 API」切换到「**能在非确定性系统里装上确定性安全阀**」——中外共同考：Agent 循环 + 记忆/上下文 + 工具协议（MCP 已必答）+ 可靠性工程（重试/熔断/循环检测）+ 可量化评测。海外额外把 evals、observability、model routing 独立化；**国内在 AI Coding / 客户端 Agent 方向，给自研 coding agent 类项目留了明确入口**（Agent Loop、上下文管理、权限模型、Hook/Skill 机制是这些 JD 的点名要求）。

## 1. 国内岗位

### 1.1 岗位分层与薪资带（B 级 + C 级交叉）

| 岗位类型 | 核心要求 | 薪资带 |
|---|---|---|
| 大模型算法（预训练/后训练） | 顶会一作 + RLHF/SFT + 千卡训练 | 应届 SSP 50–80W；社招 100–300W |
| Agent 应用算法工程师 | RAG + Tool Use + 多 Agent 编排 + 评测 | 35–60K·15-18 薪 |
| **LLM 应用/后端开发（人数最多）** | Python/Go + LangChain + 向量库 + Docker/K8s | 15–35K·13/14 薪 |
| **AI Coding Agent 产品/客户端工程师** | 见 §1.4 | 25–60K（字节移动 OS 架构师档 70–100K·15 薪） |
| 推理优化/Infra | vLLM/SGLang + CUDA + 算子 | 30–60K·15 薪 |
| Prompt 工程师（独立岗） | — | 15–30K；**岗位持续萎缩**（2025 较 2023 约 -70%） |

市场（C 级，新闻转述）：智联 2026 H1「AI agent 开发」职位同比 **+244%**；脉脉称 FDE 类岗位 +1523%。方向一致：**应用层/Agent 层岗位 2026 年爆发，模型层门槛仍高。**

### 1.2 硬性要求（频率从高到低）

1. **Python 近乎 100%**；第二语言按团队：Java（京东/字节/快手，Spring AI 生态）、Go（腾讯）、**TS/Node.js**（客户端/工具方向；百度昆仑芯 Agent 引擎明确要 TypeScript/Node.js + 安全沙箱）
2. **Agent 框架**：LangChain / LangGraph 最高频；国内特有 **Dify / Coze / Spring AI Alibaba**；AutoGen / CrewAI / LlamaIndex 次之
3. **RAG 全链路**：清洗、chunking、embedding、向量库（Milvus/Chroma/FAISS/Qdrant/pgvector）、混合检索、rerank、知识库更新
4. **Tool/Function Calling、多轮对话、任务规划、多 Agent 协同**——几乎每条 JD 必列
5. **Prompt 工程 / 上下文管理**（2026 起以「上下文工程」表述出现）
6. **工程底座**：Docker/K8s、FastAPI/Flask 服务化、高并发——不少岗本质是「后端岗 + Agent 技能」
7. **模型侧知识**：LLM 基础；中高级加 **微调（SFT/LoRA/DPO）** 与**推理部署（vLLM；私有化国产模型 DeepSeek/Qwen/GLM）**
8. **MCP**：2026 年 8–9 月起面试中**从加分题变必答题**（D 级但多源一致）
9. 学历：应用工程岗本科 + 3–5 年为主流；应届实习强调 GitHub 项目与 vibe coding 能力

### 1.3 加分项

顶会一作（算法岗硬筛）、ACM/Kaggle、开源贡献、垂域经验、**深度使用 Claude Code/Cursor/Codex 并有方法论**（多份 JD 点名）、AI 编程效率的量化证据（部分公司把「3–5 倍效率」当硬指标）。

### 1.4 AI Coding / Coding Agent 专项（与 codelotte 最相关，C 级）

- **服务端/Agent 侧**（阿里 Qoder AI Coding Agent 研发）：Java/Python/Golang + 复杂工程理解 + 自动化记忆感知 + Agent 系统设计 + RAG + MCP
- **客户端/IDE 侧**（滴滴 AI Coding、腾讯 WorkBuddy）：TypeScript/Java + **VS Code Extension API / IntelliJ Platform SDK** + LSP/MCP + Electron/Tauri/流式
- 加分项原文（滴滴专家岗）：**「深入理解 Claude Code/Codex 的 Agent Loop、上下文管理、工具调用编排、权限模型、Hook/Skill 扩展机制」**；腾讯要求「了解 Agent 架构/上下文管理/**Harness**，深度使用过 Codex/Claude Code/Cursor」

### 1.5 2026 年国内出现的三个新词（JD 化进行中）

- **上下文工程**：9 月面经题单已列为独立考点
- **Harness 工程**：被称为「2026 年才真正热起来的方向」；字节/快手/钉钉已问「Harness 和 LangChain 框架做的事有什么区别」「主流开源 Agent Harness 有哪些」
- **Skill（能力封装/渐进式披露）**：从概念题升级为设计题（「上百个候选 Skill 怎么管理」）

## 2. 海外岗位（AI Engineer / Agent Engineer / FDE）

- 岗位谱系：Research Engineer、Applied AI、FDE、Agent Engineer/Platform、AI Infra；FDE 普查（C 级）：Palantir 77、Databricks 100、OpenAI 21、Scale 18、Anthropic 7
- 薪资（B/A 级）：Anthropic Applied AI/FDE $200–320K；Glean Agentic Runtime $180–210K、Context Platform $210–300K
- **一手 JD 例证（A 级，Glean 原文摘录）**：
  - *Agentic Runtime*：multi-turn orchestration、tool calling、model routing、memory、streaming、safety；token/tool budgets；p50/p95 延迟；fault isolation、retries、timeouts、circuit-breaking、backpressure；tracing/OpenTelemetry；policy/guardrails、multi-tenant isolation、rate-limiting、cost optimization
  - *Evals 岗单独存在*：LLM applications、evals、tracing；同公司另招 Tech Lead Manager, AI Evaluations——**evals 与 context 平台已拆成独立岗位**
  - 所有 Glean JD 含流程说明：**「you'll complete a brief AI-focused exercise or discussion」**（AI 使用能力进入面试环节）

### 海内外差异（按证据）

| 维度 | 海外高频 | 国内高频 |
|---|---|---|
| 评估 | **evals 独立成岗**：LLM-as-judge 校准、golden set、轨迹级评测、CI 回归门禁、red-team | 评测多在职责内（Ragas/LangSmith），少独立岗 |
| 可观测 | LangSmith/Braintrust/**OTel** tracing、SLO/on-call（A 级原文） | Langfuse 等加分、逐步出现 |
| 上下文工程 | 明确写 "context engineering"：chunking、上下文预算、记忆分层、压缩淘汰 | 用「上下文管理/记忆机制」表述 |
| 模型路由 | model routing、KV cache、cost/latency SLA（A 级） | 主要在 Infra 岗 |
| 语言 | Python 主导（LangChain 生态岗 93.4%），TS 17.4% | Python 近 100%，Java/Go 按大厂栈 |
| 框架 | LangGraph 领先、厂商 SDK 上升；**最高薪岗不点名框架** | LangChain/LangGraph + Dify/Coze/Spring AI 并存 |
| 协议 | MCP 出现率 16.9% 且增速第一（A 级，534 listings） | MCP 面试先行，8 月后必答 |
| 工程底座 | K8s 27.2%、AWS 34.7%、Docker 32.4% | Docker/K8s + 私有化部署是特色 |

（市场数据样本：534 份 agentic 岗 listing，2026-04；LangChain 34.3%、LangGraph 22.1%、LlamaIndex 13.9%、CrewAI 10.9%；Senior 45.1%、Mid 37.6%、**Junior 仅 1.9%**）

## 3. 面试考察（2026 实际在考什么）

### 3.1 流程

- 国内：3–4 轮技术面 + HR，约 3–4 周；**简历项目深挖为绝对主线**（约 60 分钟追问「为什么这样设计/提升多少/多少人在用」）；**手撕分两类**：Agent 特色题（手写最小 ReAct Agent、上下文压缩、死循环检测器、多 Agent 消息路由器——2026 下半年高频）+ 通用算法（medium）
- 海外：Agent/RAG 系统设计 + 推理服务系统设计；**项目式 coding 允许用 AI 助手**但「每行都要能解释」

### 3.2 高频考点（中外对照）

- **概念选型**：Agent vs Workflow vs Chatbot 边界；ReAct vs Plan-and-Execute；字节会追 **ReAct 消息格式工程细节**（Thought/Action 用 assistant 角色、Observation 用 user 角色传回）
- **工具与协议**：Function Calling 原理（模型只决策不执行）与参数错误处理；MCP 原理/通信/vs FC/安全性；A2A 与 MCP 分层；Skill vs MCP vs Subagent 边界；**大规模工具集下降低工具调用幻觉**
- **记忆与上下文**：三层记忆（工作/短期/长期）；压缩触发阈值分档；压缩放链路哪一步；「任务目标迷失」防治；压缩失真与保真权衡
- **多 Agent**：主子通信链路与异常处理（超时/重试/降级/结果校验）；子 Agent 递归 Token 预算；跨 Agent 隔离
- **工程健壮性（2026 核心区分度）**：**死循环三层防御（工具层隔离 → 推理层熔断 → 规划层自修正）**；工具失败重试/超时/熔断；断点恢复 checkpoint；HITL 暂停恢复
- **评估与量化**：planning 与 hallucination 分开测；指标必须有 **baseline 对比**（「Recall@5=0.81 是好是坏？baseline 是什么？」）；「没有量化=没做核心工作」
- **安全**：Prompt Injection（直接/间接）；越权监控；高危操作四层防呆；沙箱；**凭证不进上下文**
- **系统设计压轴**（公司标签）：多 Agent 自动 PR 系统、AI 代码 Review「怎么保证只提意见不改代码」、企业知识库（权限隔离+评测）、运维 Agent（高危管控）、客服 Agent
- 公司风格：字节——工程细节连环追问；阿里——系统设计+量化；腾讯——协议与生态；百度——概率本质判断力；模型公司——推理框架细节

## 4. 技术需求清单（分级，综合中外）

**核心必备**：① Python 工程能力（+ 一门第二语言）；② Function Calling/结构化输出/多轮对话；③ RAG 全链路；④ Agent 循环 + 规划 + 记忆/上下文管理；⑤ **MCP（已必答）**；⑥ API 服务化 + Docker；⑦ **可靠性工程（超时/重试/熔断/循环检测/降级）**；⑧ 评估意识（指标 + baseline + 评测集）

**常见加分**：⑨ Evals 设施（judge/golden set/CI 回归）；⑩ 可观测性（Langfuse/OTel tracing）；⑪ 多 Agent 编排；⑫ 上下文工程进阶（压缩/token 预算/渐进披露）；⑬ 安全（注入防御/最小权限/沙箱/审计）；⑭ 微调；⑮ 推理优化；⑯ **Harness 工程认知 + Claude Code/Cursor 机制理解**；⑰ Java Spring AI / VS Code Extension；⑱ 模型路由、成本优化

**少见/特定**：RLHF/GRPO；CUDA/算子；端侧 Rust/Swift；顶会论文；A2A/Swarms；传统搜索/Ranking 结合

## 5. 面试高频考点清单（2026 频率排序）

1. 项目深挖（占时最长）：设计取舍、失败场景、量化口径、当场演示
2. Agent vs Workflow vs 单次调用的选型依据
3. ReAct 循环 + 消息格式工程细节（角色分配、终止条件）
4. **死循环/工具调用失败的检测与三层防御（2026 最经典）**
5. 记忆分层设计与上下文压缩管线（触发阈值、保真）
6. Function Calling 原理与参数错误处理；FC/MCP/Skill 三者边界
7. MCP（原理、通信、vs FC、Server 开发、安全）——必答
8. RAG 调优（分块、混合检索、rerank、评测与 baseline）
9. 评测体系设计 + 幻觉的定义/量化/治理
10. 多 Agent 通信/异常/隔离/Token 预算
11. 上下文漂移与目标迷失防治
12. Prompt Injection 与高危操作管控
13. 系统设计（客服/知识库/代码 Review/运维变种）
14. **Harness / Skill / 上下文工程三个 2026 新考区（会问设计动机）**
15. 传统 Web 应用 vs Agent 应用的架构差异
16. 手撕：最小 ReAct Agent / 压缩逻辑 / 死循环检测
17. （海外专有）推理批处理与 serving 设计、eval 设计、项目式 coding、价值观题

## 6. 置信度备注

- 国内官网 JD 原文多为 JS 渲染，未逐条抓取（C 级）；handbook 的 14 条 JD 摘录为第三方整理（B 级）
- 市场统计（+244%/+1523%/+255%）均来自新闻转述，未回溯原始报告
- D 级（培训机构/面试产品）方向与 A/B 级一致，但具体数字（阈值、指标、薪资）视为示意
- A 级来源：Glean Greenhouse JD（Agentic Runtime / Evals / APIs & Context Platform）、agentic-engineering-jobs.com（534 listings）、Exponent/UPenn 面试指南、llm-master 仓库面经原文
