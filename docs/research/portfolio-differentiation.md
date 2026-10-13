# Coding Agent 求职作品：生态与差异化扫描（2026-10-13）

> 方法：GitHub API 直连实测 star（★ 为 2026-10-13 实测）；firecrawl 额度耗尽 + WebFetch 被拦，部分叙事依赖搜索摘要（标注「二手」）。用途：codelotte 作品定位与差异化决策的依据。

**结论先行**：agent 主循环已完全商品化（"Agent = Model + Harness" 是 2026 行业共识语汇）；差异化不在「我能写 agent 循环」，而在 harness 周边工程：评测闭环、权限/沙箱、成本、上下文质量、轨迹可观测、工具供应链治理。教程型作品形态高度同质，面试官「一句话问穿」。

---

## 1. 「从零构建 coding agent」已泛滥的形态

### 1.1 教程谱系

| 教程 | 时间 | 形态 | 量级 |
|---|---|---|---|
| Thorsten Ball《How to Build an Agent》(amp) | 2025-04 | Go，<400 行，read/list/edit 三工具 + 循环 | 被称年度博文 |
| Geoffrey Huntley workshop | 2025-07 | Go，6 个递进 agent | 5,880★ |
| CodeCrafters "Build your own Claude Code" | 2025–2026 | 6 stage，10 语言支持 | beta 课程（二手） |
| mini-swe-agent + minimal-agent.com | 2025–2026 | 实现 ~100 行 / 教程版 ~60 行 | 8,467★ |
| 「280 行 Python 复刻 Claude Code」 | 2025-09 | 单文件 | HN 热帖 |
| 12-factor-agents | 2025 | 原则清单 | 26,662★ |
| Anthropic《Building Effective Agents》 | 2024–2025 | 已教科书化 | — |

**关键一句话**（280 行那位作者在 HN）：「agent 本体是 trivial 的，真正的魔法在 Claude Code 约 1200 行 prompt 里」。**2026 年「我实现了 read/write/bash 循环」的信号值 ≈ 0。**

### 1.2 面试官已见过 N 遍的形态

1. 四工具 + while 循环 + 官方 SDK（= 教程复刻）
2. Claude Code 逆向/行为复刻（claude-code-reverse 2,437★ 等）
3. RAG + Agent 客服/问答（中文侧最典型）
4. 多 agent 编排 demo（planner/executor/reviewer 三角）
5. 聊天壳 + 工具调用：无失败处理、无评测、无真实使用

### 1.3 「像跟随教程」的风险点清单

- 能力集合与某条教程一一对应，无超出教程的设计决策
- 无 eval、无失败数据，只有 happy-path demo
- 系统 prompt 抄教程/逆向产物
- 讲不出「最坏一次怎么跑飞、怎么定位」
- 自无日常使用证据
- 无 ADR/取舍记录；README 复述教程而非自己的坑

## 2. 成熟开源生态快照（2026-10-13，GitHub API 实测）

| 项目 | ★ | 状态/定位 | 备注 |
|---|---|---|---|
| anomalyco/opencode | 213,085 | 终端 TUI，model-agnostic（75+ provider） | 2026 年初因 OAuth 被 Anthropic 封锁第三方订阅；OpenAI 反向官方合作（二手） |
| openai/codex | 128,971 | Rust CLI | 三档 sandbox（read-only/workspace-write/danger-full-access），网络默认关 |
| google-gemini/gemini-cli | 107,308 | 终端 agent | — |
| OpenHands/OpenHands | 90,787 | 自动修 issue、沙箱运行 | org 已更名 |
| cline/cline | 70,267 | VS Code + CLI/SDK | Plan/Act、并行 agents+Kanban |
| aaif-goose/goose（原 block/goose） | 55,231 | Rust 通用 agent，2026-04 迁入 Linux Foundation AAIF | MCP-native、70+ extensions |
| Aider-AI/aider | 49,522 | **事实停摆**：bus factor 1（96.3% commits 一人）、最后 commit 2026-05 | 编辑格式（diff）重新定义 AI 编程 |
| continuedev/continue | 36,208 | **争议状态**：二手称被 Cursor 收购后冻结（API 显示仍有 push，未核验） | — |
| langfuse/langfuse | 35,750 | LLM/agent observability | 生态参照 |
| huggingface/smolagents | 29,815 | code-as-action 极简库 | "think in code" |
| charmbracelet/crush | 28,618 | Go TUI 精致派 | — |
| QwenLM/qwen-code | 28,460 | 终端 agent | — |
| RooCodeInc/Roo-Code | 24,282 | **archived（2026-05）**；团队转云侧，「IDE era is over」 | 多模式/编排曾是其卖点 |
| SWE-agent/SWE-agent | 20,543 | ACI 时代开创者 | — |
| e2b-dev/E2B | 14,309 | agent 沙箱云 | — |
| SWE-agent/mini-swe-agent | 8,467 | 100 行、只用 bash、线性历史；被 Meta/NVIDIA/IBM 采用；SWE-bench Verified >74% | 无 tool-calling 接口、任意模型 |
| IBM/mcp-context-forge / docker/mcp-gateway | 4,612 / 1,598 | MCP 网关/注册中心 | RBAC/虚拟服务器/OTel vs 本地容器隔离 |
| dagger/container-use | 4,070 | agent 容器化 dev env | 多 agent 安全并行 |
| harbor-framework/terminal-bench | 2,600 | TB3 2026-07、TB4 2026-08 | Docker 沙箱长任务评测 |
| openai/openai-agents-python | 30,006 | Agents SDK | — |
| daytonaio/daytona | 71,556 | **2026-10-03 归档**（2026-06 宣布闭源） | 曾是 OSS agent 沙箱标杆 |
| open-interpreter | 68,566 | 转型「面向开源模型的 coding agent」 | 战略转向（二手） |

### 2.2 2025→2026 结构性变化（可借力窗口）

1. **治理迁移**：MCP、goose、AGENTS.md 捐入 Linux Foundation 的 AAIF（2025-12 成立，2026 达 170 成员）；MCP server 1 万+、AGENTS.md 6 万+ repo 采用
2. **商业化/关闭潮**：Roo 归档、Continue 冻结、Daytona 闭源、Aider 停摆——**「可持续性与治理」本身成为稀缺品**；单维护者/单公司战略是主要死因
3. opencode 213k★：终端 TUI + 模型自由形态已被极致占据，巨头开始用 OAuth/生态封锁互钳
4. **隔离层闭源化**（Daytona 事件）→ 开源可自托管的 agent 沙箱/权限层存在真空

### 2.3 极简派对比（pi 除外）

mini-swe-agent（100 行、纯 bash、无 tool-calling）证明：**极简本身已是被占据的差异化位**——复刻极简无价值；极简只能当方法论（先小、可评测），不能当卖点。术语侧「harness engineering」2025-11→2026-02 成为显学（LangChain 语："If you're not the model, you're the harness"；同模型换 harness：Terminal-Bench 2.0 上 52.8%→66.5%；Manus 6 个月重写 harness 5 次）。

## 3. 差异化空间：8 个「大多数作品没做、企业很在意」的方向

| # | 方向 | 关键证据 | 最小可信证据（作品要做出来什么） | 单人可行性 |
|---|---|---|---|---|
| D1 | **评测闭环** | OpenAI 停报 SWE-bench Verified（59.4% 题目有缺陷）；evals 出现在 **56%** 的 JD | 20–50 条自建任务 + 固定 harness 的 pass^1/pass^5 + 与 baseline 对照 + CI 回归；**scaffolding tax 意识**（别把模型功劳算自己的） | ★★★ 最高杠杆 |
| D2 | **权限/沙箱/注入治理** | Replit agent 删生产库（2025-07）；CVE 集群（CurXecute、EscapeRoute）；「Comment and Control」PR 注入（CVSS 9.4）；Anthropic sandbox-runtime 已开源可参照 | 默认拒绝写 + 网络白名单执行层；危险操作审批；**把注入攻击做成测试用例**（恶意 README/issue 验证不执行）；审计日志 | ★★★ |
| D3 | **成本工程** | Uber 4 个月烧完全年 AI coding 预算；Gartner：23% 技术负责人人均月花 $200–500；Manus「don't break the cache」 | token/美元硬上限；前缀稳定性（缓存命中率报表）；模型路由；per-task 成本报表；**成本-成功率曲线** | ★★ 数字最强 |
| D4 | **上下文压缩质量** | context rot（18 模型随输入变长退化）；修 bug 29%@32K → 3%@256K；smart/dumb zone（~100K 实用区间，Claude Code auto-compact 在 ~95% 才触发） | **压缩质量回归测试**（经 N 次压缩后的成功率/状态保留率）；状态外置（PLAN.md）；压缩决策可观测 | ★★★ 几乎没人做 |
| D5 | **轨迹级 observability 与失败归因** | OTel GenAI 仍 experimental；SWE-bench 跑批 75% 耗尽迭代上限（多为推理循环）；招聘点名 attribution 能力 | 结构化轨迹（工具/参数/结果/token/耗时/成本）；**失败分类器**（模型误判/工具 schema/上下文丢失/循环/环境）；失败轨迹一键转回归 case | ★★★ |
| D6 | **MCP 网关与工具供应链治理** | AAIF 治理；IBM ContextForge vs Docker MCP Gateway；tool poisoning 事件 | 本地代理网关（白名单 + 按工具授权 + 审计 + 工具描述漂移检测）；「恶意 MCP server」测试用例 | ★★ 重 |
| D7 | **长任务可靠性与恢复** | Terminal-Bench 以长任务为基准；container-use 成标配 | checkpoint/resume + 幂等工具 + 确定性重放 + 故障注入测试 | ★★ 重 |
| D8 | **真实使用证据与可持续性** | 招聘红榜点名「stars 是虚荣指标」；生态教训：项目死得快 | 连续 N 周真实自用数据（合并 PR 数/省时/翻车率）；对抗性自评（何时不该用它）；治理文档（ADR/roadmap/security policy） | ★★★ |

## 4. 招聘/评估视角

### 4.1 英文侧公开言论（多源一致）

- 4 维筛选：上下文工程（会写带约束的 prompt）、批判性审查 AI 产出、知道何时**不**用 AI、文档纪律；必问「讲一次 AI 自信地错了而你发现了」
- senior 信号 = 能谈 eval 套件、成本意识、「一个自己负责的线上失败」；红旗 = notebook-only、stars 当战绩、「主要技能是配 prompt」
- **experiments beat demos**：任务集、baseline、干预、评测/grader、traces、可复现脚本；最有价值能力是 **attribution（归因）**：「失败是模型、工具 schema、上下文丢失还是记忆的问题」
- 明确不建议把「多 agent 编排/微调」当首个作品；「20 分钟内可克隆检视」
- 约 1% 初级岗（390 份 JD 统计）

### 4.2 中文侧（面试官视角）

- 问穿句：**「你这个系统，怎么验证它有效？」**——没有评测集 = 直接出局；真跑过的坑（REPEAT_LOOP、多 agent 随机性、评测系统自身偏差）才是区分度
- 不堆名词，写「为什么这么设计」、量化指标、完整链路、可复现 demo 与异常兜底
- 同质化 demo 供给过剩（注：相关高赞文部分为教培软广，取面试官视角即可）

### 4.3 Green / Red flags

- **Green**：任务集+baseline+指标；traces/失败归因；权限/沙箱设计；成本报表；失败模式文档；真实自用数据；ADR；20 分钟可跑通；知道何时不用 AI
- **Red**：与教程等价的功能集；无评测；只演示 happy path；stars/功能数量当卖点；多 agent 炫技无数据；prompt 抄的；「shipped at scale」无数字

### 4.4 自测问题（面试前自查）

1. 换一个更差的模型，你的 harness 值多少分？（scaffolding tax 意识）
2. 评测集怎么构造、怎么防止自己骗自己？
3. 一次失败轨迹，能否精确指出是哪一层的问题（模型/工具/上下文/环境）？
4. 成本上界？缓存命中率？最贵一次 run 为什么贵？
5. 恶意 README/issue 注入进来会发生什么？
6. 进程被杀 / 第 200 步上下文爆了怎么恢复？压缩后是否回归测试过？
7. 连续 4 周你用它干了什么真实的事？

## 5. 低置信度清单

Continue 状态矛盾（收购传闻 vs API 显示仍在 push）、「Frontier-Bench」更名（单 commit 证据）、部分 2026 benchmark 分数（疑似自动生成聚合站）、部分事故 CVE 编号（二手安全博客）、OpenHands/Kilo 融资收购信息（二手聚合）。

## 6. 净结论（给作品定位）

1. **别做「又一个能读文件能跑 bash 的 agent」**——该形态 2026 年信号值 ≈ 0
2. 单人可用窗口：**D1 评测闭环、D2 权限沙箱、D4 压缩质量、D5 轨迹归因**，可组合成「可验证的 harness 工程」作品，直接命中招聘方公开筛选标准
3. 呈现方式 = **实验报告**：任务集/基线/干预/指标/轨迹/复现脚本/失败分析；叙事从「我实现了 X」改成**「我把 X 的成本/成功率/失败率从 A 改到 B，并知道为什么」**
4. 附加加分：对生态动荡的判断力（Aider/Roo/Continue/Daytona 的死法与 AAIF 治理迁移、沙箱层开源真空）——「资深感」的直接来源
