# PI agent（pi）设计笔记

> 2026-10-13 调研 ｜ 用途：codelotte 求职作品的模仿对象参考 ｜ 事实来源以一手为主（pi.dev、GitHub、npm registry、作者博客、本机安装包内文档与源码）
>
> 面向面试的对比文档：[interview/pi-agent-and-claude-code.md](../../interview/pi-agent-and-claude-code.md)
>（Pi 设计 → codelotte 参考点 → Claude Code 横向对比）。

## pi 是什么

| 项 | 事实 |
|---|---|
| 身份 | Earendil Inc. 出品的开源 coding agent harness，CLI 名 `pi` |
| 作者 | Mario Zechner（badlogic，libGDX 作者）；npm 维护者含 Armin Ronacher（mitsuhiko） |
| 官网 / 仓库 | https://pi.dev ／ github.com/earendil-works/pi（原 badlogic/pi-mono） ｜ MIT ｜ TypeScript ESM monorepo |
| 规模 | 114,791 stars（2026-10-13）｜ npm `@earendil-works/pi-coding-agent` v1.2.0（2026-10-12）｜ Pi 1.0 于 2026-10-01 发布 |
| 定位 | 官网原文：**"Pi is a minimal agent harness. Adapt Pi to your workflows, not the other way around."** |
| 起源 | 作者嫌 Claude Code「变成了飞船」（80% 功能用不上）+ 不可观测 + 背后注入不可见内容；原则："if I don't need it, it won't be built" |

## 设计哲学（八条核心）

1. **最小内核**：仅 4 个内置工具（read / write / edit / bash）；系统提示 + 工具定义合计 **<1000 tokens**；只读工具（grep/find/ls）默认关闭，按需白名单开启（`pi --tools read,grep,find,ls`）
2. **"What we didn't build"**（官网专节）及替代方案：
   - 权限弹窗 → 容器/VM 隔离（原话立场：approval 弹窗不是安全模型）
   - sub-agents → bash 里 spawn 自己（`pi --print`）+ tmux
   - plan mode → 写 PLAN.md；todo → TODO.md；后台 bash → tmux
3. **2026-09 立场反转**：MCP 进核心 + **Codemode**——harness 侧的 JS 沙箱（quickjs-wasi）组合/编排工具调用；MCP 工具 schema 按需加载（避免吃掉 7–9% 上下文）
4. **成本哲学**：prompt 与工具定义是「每轮重复支付的固定成本」；skills 按需加载且不破坏 prompt cache；**反对用 sub-agent 省上下文**——先把 context gathering 做成 artifact，再开新会话
5. **会话即数据结构**：append-only JSONL，entry 带 `id/parentId` 构成树；分支 / fork / clone / compaction（一条 entry 含 summary + firstKeptEntryId）都在同一模型里；可导出 HTML 回放
6. **上下文一等公民**：AGENTS.md / SYSTEM.md、按需 skills、`context_edit`（对历史条目的追加式编辑，只影响后续请求）
7. **多模型 = 4 种 wire protocol + 数据化元模型**：10 个内置 api 实现（anthropic-messages / openai-completions / openai-responses / google-generative-ai / bedrock-converse-stream / pi-messages 等）；模型成本、上下文、缓存寿命均可被 models.json 覆盖
8. **四种消费接口**：interactive TUI / print（`-p`）/ JSON event stream / RPC —— headless 优先，便于 CI 与编排

## 一手性能数据（HarnessTax，UC Berkeley Sky Computing，2026-09）

| 对比 | 结果 |
|---|---|
| Fable 5，SWE-bench Lite | Claude Code 97.8% @ $1.33/任务 vs **pi 96.7% @ $0.67** |
| GPT-5.6 Sol，Terminal-Bench 2.0 | **pi 83.3% @ $0.42** vs Codex 78.9% @ $0.76 |
| 上下文规模 | Claude Code 平均初始上下文 **> pi 的 10 倍**；平均 turn 数几乎相同（15.3 vs 15.4） |

⚠️ 引用注意：样本小（每 benchmark 30 题 × 3 次重复）；有复跑反驳（KISS Sorcar 报 pi 68.9% 成功率）。另：流传的「$0.08 vs $1.86」数字**未能在一手来源中找到，不要引用**（本笔记写作时已同步修正 `docs/research` 中的对应表述）。

## 可迁移到 codelotte 的设计点（候选清单，待访谈第 2 轮讨论取舍）

1. **最小内核 + 最大可组合性**（primitives, not features）：核心只留不可再分的原语（loop + 4 工具 + 会话存储），其余走扩展
2. **prompt / tool schema 当「每轮固定成本」设计**：给出 token 预算指标与对照基准
3. **bash 优先 + CLI 工具 + README 渐进披露**；只读工具白名单化
4. **会话即数据结构**：JSONL + id/parentId 树 + fork + HTML 导出（HTML 导出同时是面试演示面）
5. **上下文一等公民**：AGENTS.md 发现、按需 skills、追加式 context_edit、可替换 compaction
6. **成本 / 缓存可观测**：每条 usage 记 token + USD（含 cache 读写），会话级账单
7. **显式安全模型而非弹窗**：容器/VM + 最小凭据；project trust 只管「加载什么」
8. **adapter + 元数据驱动的多模型层**：统一少量 wire protocol，模型目录数据化
9. **多消费接口**：TUI / print / JSON / RPC，headless 优先
10. **自举闭环 demo**：agent 给自己写扩展（`/reload` 热加载 + 扩展打包分发）

## 本机事实与待办

- 本机已装 pi 1.2.0（全局 npm）；`~/.pi/agent/sessions/--D--__WorkSpace__-codelotte--/` 为空目录（尚无会话）
- ⚠️ **本机 `~/.pi/agent/models.json` 的 `"api": "PI"` 无效**：内置 api id 全为小写并被精确匹配，未命中会报 `No API provider registered for api: PI`；应改为 **`"openai-completions"`**（DeepSeek 官方 API 即 OpenAI 兼容协议）
- ⚠️ API key 为明文存放；pi 支持 `$DEEPSEEK_API_KEY` 环境变量插值——建议改用环境变量并轮换 key
- `auth.json` / `models-store.json` 为空对象；`sessions` 与会话内容未读取

## 主要来源

pi.dev 首页（2026-10-13 抓取）；github.com/earendil-works/pi README 与 GitHub API；registry.npmjs.org（`@earendil-works/pi-coding-agent` 与旧包 `@mariozechner/pi-coding-agent`）；mariozechner.at/posts/2025-11-30-pi-coding-agent/；earendil.com posts（pi-1-0 / you-said-no-mcp）；harnesstax.github.io（2026-09，含 blog JSON 数据）；本机安装包内 `docs/*.md`、`schemas/*.json` 与 pi-ai 源码（compat.js、providers/deepseek.js）。
