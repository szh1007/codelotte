# 02 上下文工程与代码智能

> 信息截止 2026-10-13 ｜ 标签：`【一手】`官方文档/原文、`【独立】`学术/独立评测、`【三方】`专业媒体、`【厂商】`厂商自述、`【社区】`逆向/汇总

## 一、代码检索路线：2026 年不是二选一

### 1.1 主流产品技术路线对照

| 产品 | 检索/上下文机制 | 索引 | 关键证据 |
|---|---|---|---|
| **Claude Code** | agentic search：ripgrep/glob 即时检索；CLAUDE.md 静态前置 + JIT 动态加载；compaction + 记忆文件 + 子代理隔离 | **无代码库索引** | 【一手】Anthropic《Effective context engineering》2025-09：「naively dropped CLAUDE.md 前置，glob/grep JIT 检索，绕开 stale indexing」；负责人公开表述「早期用过 RAG+本地向量库，很快发现 agentic search 更好」 |
| **Cursor** | 语义索引 + agentic 检索 + 动态上下文发现；2026-03 起新增 regex/trigram 索引（Instant Grep） | Merkle tree + 语法分块 + embeddings（按 chunk 缓存）+ simhash 索引复用；A/B 自测语义检索 +12.5% 准确率 | 【一手】cursor.com/blog（2026-01-06 / 01-27 / 03-23） |
| **GitHub Copilot** | 仓库级向量索引 + 语义搜索，叠加 agentic 多工具循环 | 服务端嵌入索引（Instant indexing 2025-03 GA） | 【一手】Microsoft Learn《How Copilot Chat uses context》2026-02 更新 |
| **OpenAI Codex** | **无索引**：shell + apply_patch，系统提示明确「优先 rg」 | 无 | 【一手】openai/codex 开源仓库（Rust） |
| **Devin / Windsurf** | RAG context engine（全库索引）+ DeepWiki 宏观图 + **SWE-grep** RL 检索子代理 | 专有；DeepWiki 以文件=节点/关系=边的图表示 | 【一手】docs.devin.ai、cognition.ai/blog/swe-grep |
| **Amp / Sourcegraph** | 确定性代码搜索（跨仓/全分支/全版本）+ SCIP 代码智能 + Deep Search，经 MCP 暴露 | 全量确定性索引 | 【一手】sourcegraph.com/blog/agentic-coding（2026-05-21） |
| **Aider**（开源） | repo map：tree-sitter tags + PageRank + token 预算二分拟合（默认 1,024） | 每请求重建 | 【一手】aider.chat/docs/repomap.html |

### 1.2 共识与证据

**结论：不存单一共识；实际收敛为「按任务分层」，话语权已从 embedding 转向 agentic search。**

- **交互式编码默认 agentic search**（Claude Code / Codex 均无向量库）
- **独立学术证据站 grep 一侧**：GrepRAG（ISSTA 2026，arXiv 2601.23254）——朴素「LLM 自主生成 ripgrep 命令」已与图/嵌入检索基线相当（RepoEval Python EM 38.61% vs Vanilla RAG 24.99%），加 identifier 重排后相对提升 7.04–15.58%；效率 0.40s vs 3–7s + 91s 索引。机理：**约 95% 检索关键词是标识符**（方法名 41%、类名 36%、变量名 18%），精确匹配天然占优【独立】
- **反方**：大 monorepo 中 rg 调用常 >15s；grep 在大仓库的 token 效率问题被多方记录【三方/社区】
- **2026 的新增量 = 为 agent 专门造索引/模型**（而非回到 2023 式 RAG）：
  - Cursor Fast Regex Search：为 agent 的 regex 查询建 trigram 倒排索引（「Instant Grep」）【一手】
  - Cognition SWE-grep / SWE-grep-mini：RL 训练的多轮检索模型（8 并行工具调用 × 4 轮，输出文件+行号），Windsurf 以此实现 Fast Context（快至 20x）【一手】
  - GitHub Blackbird（Rust trigram 关键词引擎）与 Copilot 语义索引并存

### 1.3 索引与 repo map 技术要点

- **Cursor 索引管线**（官方披露）：Merkle tree 逐文件 SHA-256（50k 文件 ≈3.2MB 哈希）→ 变更文件语法分块 → embedding（异步、按 chunk 内容哈希缓存）→ 新用户用 simhash 在组织内复用相似索引（平均 92% 相似），time-to-first-query 中位 7.87s→525ms、P99 4.03h→21s；Merkle 内容证明做**访问证明**防跨用户结果泄漏【一手】
- **repo map**：Aider 的 tree-sitter + PageRank 是引用最多的开源实现；2026 生态大量 MCP server 复刻该思路并宣称 token 节省 60–96%（【厂商/社区】，需打折）
- **研究侧**：CodeRAG-Bench（NAACL 2025）repo 级 RAG 评测；cAST 分块（EMNLP 2025 Findings）Recall@5 +4.3；微信工业界结论：**BM25 + 向量混合最优**（arXiv 2507.18515）【独立】

## 二、代码智能基础设施

### 2.1 tree-sitter（结构层，事实标准）

- 角色：增量解析、按语法边界分块（函数/类不被打断）、tags 提取、repo map、导入/调用图
- **边界**：无类型语义、名称解析是近似的——适合做快速结构层，与 LSP/SCIP 互补而非替代【社区】

### 2.2 LSP（从编辑器标准变成 agent 工具）

- 【一手】Claude Code 官方上架 **TypeScript / Python / Go / Rust 等 code intelligence 插件**（`/plugin install typescript-lsp@claude-plugins-official`），用语言服务器做 go-to-definition / find-references / 类型错误，替代大量 grep+读文件
- 【一手】Serena（开源 MCP server）：LSP 支撑的 `find_symbol` / `find_referencing_symbols` / `replace_symbol_body`，支持 30–40+ 语言，适配 Claude Code、Codex、Copilot、Cursor
- Thoughtworks 技术雷达（2026-04）收录「Code intelligence as agentic tooling」；GitHub Copilot CLI 已接入真实 LSP 做类型感知导航【三方/一手】
- **争议**：LSP 为编辑器设计、原子调用粒度对 agent 不友好（需链式多次调用）；实践分工 = **grep 用于探索、LSP 用于定位/引用**【三方/社区】

### 2.3 SCIP（精确索引层）

- SCIP（Sourcegraph Code Intelligence Protocol）是 LSIF 后继（Protobuf、全局符号 ID、体积约 LSIF 的 1/4）；**2026-03-25 转独立社区治理**，Core Steering Committee 首发：Meta、Uber、Sourcegraph【一手】
- LSIF 已实质弃用（GitLab 将 indexer 从 lsif-go 换为 scip-go，提交信息明示 deprecated）
- 索引器覆盖（2026 中）：scip-java（Java/Kotlin/Scala，GA）、rust-analyzer 内置（Rust，GA）、scip-python（Pyright fork，GA）、scip-typescript、scip-clang、scip-go、scip-ruby、scip-dotnet、scip-php、scip-dart
- GitHub stack-graphs（tree-sitter + TSG 规则）：有社区信号称疑似停止维护——**置信度低，不作定论**【社区】

### 2.4 各语言 symbol/graph 提取速查

| 语言 | 精确索引 | 结构层 | 备注 |
|---|---|---|---|
| Java/Kotlin/Scala | scip-java（GA） | tree-sitter | Uber scip-lsp 生产案例 |
| Rust | rust-analyzer 内置 SCIP | tree-sitter | 无独立发布物 |
| Python | scip-python（GA） | tree-sitter | 另有 ruff/pyright LSP |
| TS/JS | scip-typescript | tree-sitter | Copilot 索引独立于 SCIP |
| Go | scip-go | tree-sitter | GitLab 已迁移 |
| C/C++/CUDA | scip-clang | tree-sitter | |
| Ruby / C# / PHP / Dart | scip-ruby / scip-dotnet / scip-php / scip-dart | tree-sitter | |

## 三、长上下文（1M 级）之后，检索被削弱了吗

**没有。1M 窗口改变了 RAG 的角色（从「唯一入口」变成「守门员/加速器」），但未使其退场。**

- 能力侧：1M 上下文 2026 年已主流化；但 context rot（Chroma）与 lost-in-the-middle（Liu et al.）仍是公认约束
- **成本锚点**：500K token 全仓直塞约 $2.95 vs 10K token RAG agent $0.33（约 9x）；全上下文比 RAG 贵 8–200x；RAG 基础设施 $500–1,500/月
- 工程做法：检索先选出 8K–16K 高信号切片再进大窗口；按请求路由（95% 流量给 200K 模型，超阈值才落长窗口）；四层记忆（repo 图 / 决策记忆 / agent 暂存 / 团队记忆）
- 长窗口真正赢的场景：跨文件深依赖重构、多小时调试、整仓架构理解、整 PR review（A/B 称减少 15–25% 漏改点）【三方/厂商】
- 一句话：检索演化为 **agentic grep + regex 索引 + 符号级代码智能 + 语义索引 + 检索子代理**的组合拳

## 四、企业大仓与内部集成

### 4.1 大仓上下文策略（以 Claude Code 官方文档为最完整样本，【一手】）

- **分层 AGENTS.md / CLAUDE.md**：启动时加载 cwd 及全部父目录的文件，子目录按需加载；根文件管通用规范、每包/子系统各写各的；`claudeMdExcludes` 排除不工作的包；managed policy 不可排除
- **禁读无关内容**：`permissions.deny` 的 Read 规则屏蔽 `node_modules`/dist/generated/vendored
- **代码智能替代扫描**：装 TS/Python/Go/Rust LSP 插件做符号定位
- **worktree 瘦身**：`worktree.sparsePaths`（git sparse-checkout 只检出任务所需目录）+ `symlinkDirectories`
- **跨包/跨仓**：`--add-dir` / `additionalDirectories`；内部 marketplace 插件统一下发团队规范

### 4.2 Sourcegraph「80% 问题」

agent 可靠完成「可见的 80%」，漏掉跨仓/跨层的 20%（auth 中间件、DTO、审计日志、兄弟仓集成测试、前端权限守卫）；调研称 AI 上线后 84% 的大型企业账户 LOC 持续上涨、开发者搜索行为反而增加——**「agent 生产力上限由它能看见什么决定」**【厂商，被广泛引用】

### 4.3 内部代码检索/知识库与 agent 集成三模式

1. **Agent + 内部代码搜索 MCP**（最主流）：Sourcegraph MCP Server 暴露 `keyword_search` / `nls_search` / `code_finder` / `deepsearch` / `go_to_definition` / `find_references` 等，OAuth 2.0 + RBAC，管理员可禁用单工具；案例：Stripe 的 agent 群经 MCP 获取内部文档、ticket、构建状态与代码智能【一手】
2. **Agent + 企业知识图谱 MCP**：Glean Developer Platform——文档/决策/人员/ticket/代码统一为 permission-aware 知识层，单端点对接 20+ host【一手】
3. **自建私有注册表 + 内部插件市场**：MCP 官方 registry 明确不支持私有 server，企业需自建（实现其 OpenAPI），配合 managed policy 下发插件与权限【一手】

## 五、对「上下文文件」的独立校正（重要）

ETH Zurich《Evaluating AGENTS.md》（arXiv 2602.11988，AGENTbench 138 任务）【独立】：

| 发现 | 数据 |
|---|---|
| LLM 生成的 context 文件 | 成功率 **-3%**，成本 +20–23% |
| 人工撰写的 context 文件 | 成功率 +4%（SWE-bench Lite 上无增益），成本仍 +19% |
| 正确用法 | 只写「模型推断不出的」：构建/测试命令、本仓工具链（提及 `uv` 使使用率 ×160）；冗余架构描述无益 |

→ 上下文文件要当**运维手册**写，不要当**架构文档**写。

## 主要来源

- Anthropic《Effective context engineering for AI agents》（2025-09-29）：https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents 【一手】
- Cursor 三篇官方博客（动态上下文发现 / 安全索引 / Fast regex search）：cursor.com/blog 【一手】
- Claude Code 大仓文档：https://code.claude.com/docs/en/large-codebases 【一手】
- GrepRAG：https://arxiv.org/abs/2601.23254 （ISSTA 2026）【独立】
- ETH Zurich AGENTbench：https://arxiv.org/abs/2602.11988 【独立】
- Sourcegraph《Agentic Coding in 2026》（80% 问题）：https://sourcegraph.com/blog/agentic-coding 【一手】
- Cognition SWE-grep：https://cognition.ai/blog/swe-grep 【一手】
- SCIP 独立治理公告：https://sourcegraph.com/blog/the-future-of-scip 【一手】
