# codelotte 与 Pi agent、Claude Code 的关系

> 用途：面试前理解「设计来源 → 取舍 → 横向位置」，回答“为什么这么做”“和 Pi 有什么关系”
> “和 Claude Code 比怎么样”。
>
> 事实口径：
> - Pi agent 的事实来自仓库调研笔记 [pi-agent-design.md](../docs/research/pi-agent-design.md)
>   与其中列出的一手来源（pi.dev、GitHub、npm、作者博客、本机安装包），调研日期 **2026-10-13**。
> - Claude Code 是闭源商业产品，内部实现不公开；本文只比较**公开可见的设计选择**，
>   不推测内部机制。
> - 性能对比引用 HarnessTax（UC Berkeley Sky Computing，2026-09）时保留其样本与复跑争议，
>   不把单一 benchmark 当成结论。

## 1. Pi agent：极简主义 harness 的样本

### 1.1 它是什么

| 项 | 事实 |
|---|---|
| 身份 | Earendil Inc. 出品的开源 coding agent harness，CLI 名 `pi` |
| 作者 | Mario Zechner（badlogic，libGDX 作者）；npm 维护者含 Armin Ronacher（mitsuhiko） |
| 仓库 / 许可 | [pi.dev](https://pi.dev) · `github.com/earendil-works/pi` · MIT · TypeScript ESM monorepo |
| 版本 | Pi 1.0 于 2026-10-01 发布；调研时 npm `@earendil-works/pi-coding-agent` v1.2.0（2026-10-12） |
| 规模 | 114,791 stars（2026-10-13 调研值；会变化） |
| 定位 | 官网原文：**“Pi is a minimal agent harness. Adapt Pi to your workflows, not the other way around.”** |

Pi 不是“又一个 agent 框架”，而是对主流 coding agent 的一次反向设计：它把
“模型之外的全部系统”压到尽可能小，把可组合性交给 bash、文件和外部工具。

### 1.2 它反对什么

Pi 的起点是对 Claude Code 一类产品的批评：

- **“变成了飞船”**：作者的原话大意是，Claude Code 80% 的功能他用不上；
- **不可观测**：用户不知道每轮到底往模型发了什么、为什么这么贵；
- **隐藏注入**：系统会在背后注入用户看不见的内容；
- **原则**：**“If I don't need it, it won't be built.”**

这条批评线很重要：Pi 的极简不是审美，而是对**成本、可观测性与控制权**的回应。
理解这一点，才能理解它为什么连 grep/find/ls 都不做成内置工具。

### 1.3 八条核心设计

**① 最小内核**

- 仅 4 个内置工具：`read` / `write` / `edit` / `bash`。
- 系统提示 + 工具定义合计目标 **< 1000 tokens**。
- 只读工具（grep / find / ls）默认关闭，按需白名单开启
  （`pi --tools read,grep,find,ls`）——搜索本质上可以走 bash。

**② “What we didn't build” 与替代方案**

Pi 官网专门有一节讲“我们没做什么”，并给出替代路径：

| 没做 | 替代方案 |
|---|---|
| 权限弹窗 | 容器 / VM 隔离（立场：approval 弹窗不是安全模型） |
| sub-agents | 在 bash 里 spawn 自己（`pi --print`）+ tmux |
| plan mode | 写 `PLAN.md` |
| todo | 写 `TODO.md` |
| 后台 bash | tmux |

这套替代方案的共同点是：**用文件系统和 shell 这些通用原语，替代内建功能**。

**③ MCP 与 Codemode（2026-09 立场反转）**

Pi 早期明确不做 MCP，后来把 MCP 放进核心，并引入 **Codemode**：harness 侧的
JS 沙箱（quickjs-wasi）用来组合/编排工具调用；MCP 工具 schema 按需加载，
避免一次吃掉 7–9% 上下文。

这条反转很值得注意：**极简的边界不是教条，而是随真实需求移动的**。面试时如果被问
“极简是不是不做功能”，这是最好的反例。

**④ 成本哲学**

- prompt 与工具定义是“每轮重复支付的固定成本”，所以要把它们压到最小。
- skills 按需加载，并且不破坏 prompt cache。
- 反对“用 sub-agent 省上下文”：先把 context gathering 做成 artifact，再开新会话。

**⑤ 会话即数据结构**

- append-only JSONL，entry 带 `id/parentId` 构成树。
- 分支 / fork / clone / compaction 都在同一模型里。
- **compaction 本身是一条 entry**（summary + `firstKeptEntryId`）。
- 会话可导出 HTML 回放。

**⑥ 上下文一等公民**

- `AGENTS.md` / `SYSTEM.md` 发现。
- 按需 skills。
- `context_edit`：对历史条目的追加式编辑，只影响后续请求，不改原始记录。

**⑦ 多模型 = wire protocol + 数据化元模型**

- 10 个内置 api 实现，按 wire protocol 归约（例如 `anthropic-messages` /
  `openai-completions` / `openai-responses` / `google-generative-ai` /
  `bedrock-converse-stream` / `pi-messages` 等）。
- 模型成本、上下文窗口、缓存寿命可被 `models.json` 覆盖。

**⑧ 四种消费接口，headless 优先**

- interactive TUI / print（`-p`）/ JSON event stream / RPC。
- headless 优先，便于 CI 与编排。

### 1.4 它的代价与边界

- **极简本身不构成差异化**：仓库的生态调研结论是，极简已经是竞争激烈的位置
  （mini-swe-agent 用 100 行就证明了这一点）；Pi 的差异化在于**极简 + 可组合 + 成本/可观测性**的组合。
- **边界会移动**：MCP 的反转说明“不做”是当时的取舍，不是永久教条。
- **benchmark 不宜过度引用**：HarnessTax 的样本小（30 题 × 3 次重复），且有复跑反驳
  （KISS Sorcar 报 pi 68.9%）。另一个流传的“$0.08 vs $1.86”数字未能在一手来源中找到，
  **不要引用**。

## 2. codelotte 参考了 Pi 的哪些机制

### 2.1 直接参考（有 ADR / 代码对应）

| Pi 的机制 | codelotte 的对应 | 参考程度 | 证据 |
|---|---|---|---|
| 4 工具 minimal core | `read` / `write` / `edit` / `bash`；grep/find/ls 不走专用工具，统一走 bash | **直接参考** | [README](../README.md) · [SPEC §D](../docs/dev/v1/SPEC.md) |
| 系统提示 + 工具定义 <1000 token | 同一目标：把每轮固定成本压低 | **目标参考** | [SPEC §B](../docs/dev/v1/SPEC.md) |
| append-only JSONL + `id/parentId` 树 | 同构；`--continue` / `--resume` / `--fork` | **直接参考** | [ADR-0003](../docs/adr/0003-session-model.md) · [session/store.py](../src/codelotte/session/store.py#L270) |
| compaction 即 entry | 同构；存 `summary` / `firstKeptEntryId` / `constraints` | **直接参考** | [ADR-0003](../docs/adr/0003-session-model.md) · [compaction/](../src/codelotte/compaction/) |
| HTML 导出回放 | 自包含 HTML / Markdown 导出，纯函数、逐字来自会话 | **直接参考** | [export.py](../src/codelotte/export.py#L339) |
| headless 优先 | `-p` + TUI；未实现 JSON event stream / RPC | **部分参考** | [cli.py](../src/codelotte/cli.py) |
| 成本可观测 | 每次调用记 token / 缓存命中 / 峰谷价；会话账单 | **参考并扩展** | [cost.py](../src/codelotte/cost.py) · [E2](../docs/experiments/e2-cost-curve.md) |
| 数据化模型元数据 + 薄 adapter | `models.json` + 自研 adapter（httpx2 + 内联 SSE） | **参考并收窄** | [ADR-0004](../docs/adr/0004-self-built-llm-adapter.md) |
| “审批弹窗不是安全模型” | Docker 沙箱是边界；但保留权限层做策略与审计（两层） | **参考并调整** | [ADR-0005](../docs/adr/0005-two-layer-execution-security.md) · [SECURITY.md](../SECURITY.md) |

### 2.2 有意不同（为什么没有照搬）

| Pi 的做法 | codelotte 的选择 | 原因 |
|---|---|---|
| TypeScript ESM monorepo | Python 3.13 + uv | 目标岗位以 Python 为主；Textual 在 Windows 终端成熟（[ADR-0002](../docs/adr/0002-python-over-typescript.md)） |
| 10 个 api / 4 种 wire protocol | 只实现 `openai-completions`；`anthropic-messages` 预留 | 没有第二把 key；先把一条路径做透，协议抽象留槽（[ADR-0004 实现状态](../docs/adr/0004-self-built-llm-adapter.md)） |
| MCP + Codemode | v1 不做 MCP | SPEC 明确列为 Out of Scope；先把 minimal core 与评测做扎实（[ROADMAP](../docs/dev/v1/ROADMAP.md)） |
| AGENTS.md / skills / `context_edit` | v1 不做 | 同上；压缩与 checkpoint 先落地 |
| 反对权限弹窗 | 保留权限层 + Docker 两层 | 同意“弹窗不是安全边界”，但规则层仍用于**策略表达与审计**；Docker 才是后果边界 |
| 极简作为产品卖点 | 极简作为**测量底座** | 仓库调研结论：极简本身不构成差异化；差异化是评测与实验（[ADR-0001](../docs/adr/0001-portfolio-positioning.md)） |

### 2.3 codelotte 在 Pi 之外加的东西

- **评测闭环**：9 条通用任务 + 3 条 judge + 3 条注入 + 1 条死循环压力；
  pass^k、控制 agent（oracle / no-op / cheating）、失败归因、回归任务、防御审计。
  - 入口：[evals/README.md](../evals/README.md)
  - 实验：[E1](../docs/experiments/e1-compaction-curve.md) · [E2](../docs/experiments/e2-cost-curve.md) ·
    [E3](../docs/experiments/e3-attribution-accuracy.md) · [E4](../docs/experiments/e4-scaffolding-tax.md) ·
    [E5](../docs/experiments/e5-defense-effectiveness.md)
- **峰谷价记账**：PLAN 的调研结论指出 Pi 的内置目录只建模峰价；codelotte 把低谷五折
  也纳入逐次记账，并用反事实重算成本（E2）。
- **Docker 默认沙箱**：Pi 的立场是容器/VM 隔离；codelotte 把它落成默认 Docker 长驻容器。
- **失败归因与防御用例**：五类病位 + 证据 + 置信度；注入/死循环做成可复现任务。
- **材料包**：数据表、20 分钟 walkthrough、简历项目经历——把工程变成可讲的证据。

### 2.4 一句话总结

> **Pi 是方法论来源，codelotte 是测量作品。**
> codelotte 借了 Pi 的“最小内核 + 会话即数据结构 + 成本可观测 + headless 优先”，
> 但没有复刻它的产品形态；它把省下来的复杂度预算投入到评测与实验上，
> 回答“改了什么、好了多少、为什么”。

## 3. 横向对比：Claude Code 这种复杂但成熟的 agent

### 3.1 对比口径

Claude Code 是 Anthropic 的官方终端 coding agent，闭源、产品化、跨平台，
并延伸到 IDE / 桌面 / Web。下面的对比只基于公开可见的能力与设计取向，
不推断其内部实现；重点不是“谁更强”，而是**它们各自优化什么**。

### 3.2 机制对照

| 维度 | Pi agent | codelotte | Claude Code |
|---|---|---|---|
| 定位 | 极简 harness，可组合 | 可测量的 harness 作品 | 成熟商业产品 |
| 工具面 | 4 内置；只读工具按需开启 | 4 内置；搜索走 bash | 大而全：文件搜索、网页、子 agent、待办、notebook 等 |
| 上下文 | 固定成本 <1000 token；skills 按需 | 同一目标；双触发压缩 + checkpoint | 复杂上下文工程；初始上下文显著更大 |
| 会话 | JSONL 树 + fork + compaction | 同构 + HTML/Markdown 导出 | 会话/transcript；内部结构不公开 |
| 安全 | 容器/VM 隔离，反对弹窗 | 权限层 + Docker 两层 | 权限模式 + hooks + 沙箱/审批等成熟体系 |
| 扩展 | MCP + Codemode + extensions | v1 无 MCP | MCP、skills、subagents、hooks、IDE 集成 |
| 模型 | 多协议 / 多模型 | 自研 adapter；当前 DeepSeek | Anthropic 模型为主，云平台集成 |
| 观测 | 成本/usage + HTML | 会话 JSONL 单一数据源 + 成本面板 + 导出 | usage/cost、transcript、hooks |
| 评测 | 公开材料更强调 harness 本身 | E1–E5 + 控制 agent + 归因/防御 | 内部评测不公开；公开 benchmark 数据有限 |
| 成熟度 | 1.x，社区活跃 | 0.1.1，599 测试 | 生产级，跨平台/IDE/企业部署 |

### 3.3 HarnessTax 的数字与读法

调研笔记引用的 HarnessTax（2026-09）给出了同模型、不同 harness 的对照：

| 对比 | 结果 |
|---|---|
| Fable 5，SWE-bench Lite | Claude Code 97.8% @ $1.33/任务 vs pi 96.7% @ $0.67 |
| GPT-5.6 Sol，Terminal-Bench 2.0 | pi 83.3% @ $0.42 vs Codex 78.9% @ $0.76 |
| 初始上下文 | Claude Code 平均 > pi 的 10 倍 |
| 平均 turn 数 | 15.3 vs 15.4（几乎相同） |

**必须同时说的限制：**

- 样本小：每个 benchmark 30 题 × 3 次重复；
- 有复跑反驳：KISS Sorcar 报 pi 68.9% 成功率；
- 不能把一个 benchmark 当成普遍结论；
- 流传的“$0.08 vs $1.86”数字**没有一手来源，不要引用**。

这些数字适合用来说明“harness 的固定成本值得测量”，不适合用来宣称“pi 全面优于
Claude Code”或“codelotte 优于谁”。

### 3.4 为什么 Claude Code 的复杂是合理的

Claude Code 面向的是**产品**，不是教学样本：

- 要覆盖搜索、网页、子 agent、notebook、IDE、企业权限等真实工作流；
- 要把安全、审计、跨平台、可维护性做到生产级；
- 要为大量用户提供一致的行为与支持。

复杂度是这些目标的代价。Pi 的批评——“80% 的功能用不上”——对**个人工作流**成立，
对**产品覆盖面**不成立。两者不是同一道题。

### 3.5 codelotte 的位置

codelotte 既不试图成为 Pi，也不试图成为 Claude Code：

- 它借 Pi 的 minimal core，因为**小内核让每一轮成本与行为可解释**；
- 它不复制 Claude Code 的功能面，因为**作品的目标是证明测量能力，不是覆盖产品需求**；
- 它把 Claude Code 当作“复杂但成熟”的参照：理解它的权限、hooks、MCP、skills
  为什么存在，但不把“功能多”当成工程能力的证明。

### 3.6 面试话术（30 秒）

> “Pi agent 是我的方法论来源：4 工具、<1000 token 固定成本、会话即数据结构、
> 成本可观测、headless 优先。我没有复刻它——我用了 Python，只实现一条 wire protocol，
> v1 不做 MCP；Pi 自己在 2026-09 也把 MCP 加回来了，说明极简的边界是随需求移动的。
>
> Claude Code 是另一端的样本：复杂但成熟，适合产品。我的作品不是和它比功能，
> 而是证明我能把 harness 的改动量化——成功率、成本、失败归因、防御拦截，
> 每一项都有分母和‘不能证明什么’。”

## 4. 关键词索引

| 关键词 | 跳转 | 说明 |
|---|---|---|
| Pi agent 调研原文 | [docs/research/pi-agent-design.md](../docs/research/pi-agent-design.md) | 八条设计、一手来源、引用注意 |
| 作品定位 | [ADR-0001](../docs/adr/0001-portfolio-positioning.md) | 为什么是“可验证的 harness 工程” |
| 语言选择 | [ADR-0002](../docs/adr/0002-python-over-typescript.md) | 为什么 Python 不是 TypeScript |
| 会话模型 | [ADR-0003](../docs/adr/0003-session-model.md) | JSONL 树 + compaction 即 entry |
| LLM adapter | [ADR-0004](../docs/adr/0004-self-built-llm-adapter.md) | 自研 adapter 与协议实现状态 |
| 双层安全 | [ADR-0005](../docs/adr/0005-two-layer-execution-security.md) | 权限层 × 沙箱层 |
| 技术规格 | [SPEC.md](../docs/dev/v1/SPEC.md) | Minimal Core、工具、压缩、评测 |
| 四工具 | [src/codelotte/tools/](../src/codelotte/tools/) | `read` / `write` / `edit` / `bash` |
| 会话树 | [session/store.py](../src/codelotte/session/store.py#L270) | append-only JSONL、分支 |
| 压缩 | [compaction/trigger.py](../src/codelotte/compaction/trigger.py#L178) | 双触发与切点 |
| 成本 | [cost.py](../src/codelotte/cost.py) | 峰谷价、缓存命中 |
| 评测 | [evals/README.md](../evals/README.md) | 九个命令与报表 |
| E1–E5 | [docs/experiments/](../docs/experiments/README.md) | 实验报告索引 |
| E4 对照 | [e4-scaffolding-tax.md](../docs/experiments/e4-scaffolding-tax.md) | codelotte / mini / 裸 API |
| 安全模型 | [SECURITY.md](../SECURITY.md) | 威胁模型与已知限制 |
| 数据表 | [data-sheet.md](data-sheet.md) | 面试屏幕共享 |
| 20 分钟 walkthrough | [walkthrough.md](walkthrough.md) | 动线 + 追问答案 |
| 项目经历 v1 | [project-experience-v1.md](project-experience-v1.md) | 简历版描述 |

## 5. 版本记录

| 版本 | 日期 | 变化 |
|---|---|---|
| v1 | 2026-10-19 | 首版：Pi agent 设计介绍、codelotte 参考点、Claude Code 横向对比 |
| v2 | 待定 | Pi / Claude Code 有新公开资料或 codelotte 补齐 MCP、第二协议后更新 |
