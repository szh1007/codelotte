# Python 技术栈事实笔记（2026-10-13）

> 用于：codelotte 技术底座（第 2 轮 Q6/Q7）｜ 方法：PyPI JSON API / GitHub raw / 官方文档 curl 直取 + 搜索交叉 ｜ 版本类为高置信度

## 0. 选型结论（候选，待用户确认）

| 项 | 选择 | 依据 |
|---|---|---|
| TUI | **Textual 8.2.8**（MIT） | 2026 Python agent 事实标准；内置 `Markdown.get_stream` 流式渲染；Windows 有官方支持路径 |
| HTTP | **httpx2**（pydantic 维护，2.13.1），**而非 httpx** | httpx stable 停在 0.28.1 已 22 个月；OpenAI/Anthropic SDK 均已依赖 httpx2 |
| SSE | **内联解码器**（~100 行，参考 OpenAI SDK vendored 版） | httpx-sse 仍硬依赖 httpx，与 httpx2 不兼容 |
| 包管理 | **uv 0.13.0**（本机 0.12.3 需升级） | `uv init` 自带 `[project.scripts]` + uv_build 后端 |
| Python | **3.13 起步**（本机 3.13.13） | 3.15.0 刚发布 6 天，生态先行不追新 |
| diff 渲染 | difflib.unified_diff + `rich.syntax.Syntax(lexer="diff")` 自建 widget | Python 生态无标准库方案 |

## 1. TUI 框架现状

| 框架 | 最新版 | 定位 | 知名采用者 |
|---|---|---|---|
| **Textual** | 8.2.8（2026-06，MIT） | 全屏组件式（TCSS、35+ widget、reactive、DevTools、可 serve 到浏览器）；也支持 inline 非全屏 | **OpenHands CLI**、**LangChain deepagents code**、Toad（Textual 作者）、huggingface/tau |
| prompt_toolkit | 3.0.53 | 行式输入为主；补全/键位最强 | **Aider**（+Rich Live 分区流式）、gptme |
| Rich（渲染层） | 15.0.0（Aider 仍 pin 14.3.3） | Textual 底座 | 几乎所有 Python CLI |
| urwid | 4.2.5 | 维护模式（~3k stars vs Textual ~37k） | 老项目，有迁移趋势 |

- Textual 关键能力：`Markdown.get_stream`（5.0+，专为 LLM 流式设计）、textual-autocomplete、pytest-textual-snapshot（快照测试）
- Textualize 公司 2025-05 关停，框架继续开源维护
- **Windows**：Textual 官方推荐 **Windows Terminal**（legacy conhost 非支持目标）

### Windows 关键陷阱（中置信度）

- Windows 默认 `ProactorEventLoop` **不实现 add_reader/add_writer**；`SelectorEventLoop` 支持 add_reader 但**不支持 subprocess**
- prompt_toolkit 的 input hook 用 SelectorEventLoop → 「行式输入 + asyncio 子进程」在 Windows 存在结构性冲突（gptme 曾靠线程规避）
- **Textual 自带 Win32 console driver，规避该问题**——选 Textual 的隐藏红利

## 2. HTTP / 流式（最大发现：httpx 生态分裂）

| 库 | 版本 | 状态 |
|---|---|---|
| httpx | 0.28.1（2024-12）；1.0 一直 dev | **stable 近 22 个月未发版**，社区迁移潮（争议中置信度） |
| **httpx2** | **2.13.1（2026-09-23）**，github.com/pydantic/httpx2 | pydantic 维护的继任者，API 兼容；**openai 3.29 依赖 `httpx2>=2.12`，anthropic 1.13 依赖 `httpx2>=2.0`** |
| aiohttp | 3.14.5 | 活跃；无 HTTP/2 客户端 |
| httpx-sse | 0.4.3 | **源码硬依赖 httpx，未适配 httpx2** |
| litellm | 1.105.0 | 主依赖仍 httpx + openai |

- **OpenAI-compatible SSE 2026 做法**：官方 SDK 把 httpx-sse 解码器 vendored 内联（基于 `response.iter_bytes()` 自解析 SSE 与 `[DONE]`）——我们照此自写 ~100 行即可
- 结论：上 httpx2；不引 httpx-sse；SSE 解码内联自研

## 3. uv

- 最新 **0.13.0（2026-10-09）**：默认 Python 3.15、cache 格式变更、Windows ARM64 改进
- `uv init` 生成的 pyproject 已含 `[project.scripts]` 入口 + `uv_build` 后端
- 开发：`uv add` / `uv run` / `uv lock`；开发依赖用 PEP 735 `[dependency-groups]`
- 分发：`uv build` → wheel；`uv publish`；`uv tool install`（独立环境 + PATH）

## 4. 主流 Python agent 技术栈（参考样本）

| 项目 | TUI | HTTP/LLM | 现状 |
|---|---|---|---|
| OpenHands CLI | Textual（+autocomplete/serve、pytest-textual-snapshot） | 后端 FastAPI + litellm | 活跃 |
| Aider | prompt_toolkit + Rich Live | httpx + aiohttp 并存 | **停摆**（最后提交 ~2026-05，fork 接手） |
| mini-swe-agent | typer + rich（依赖含 textual） | litellm + subprocess | 活跃 |
| open-interpreter | **官方已重写为 Rust**（fork 自 Codex） | Rust 核心 + Python SDK | 活跃 |
| deepagents code（LangChain） | Textual 8.2.8 + prompt-toolkit + rich；自维护 diff widget | — | 活跃 |
| Toad（Textual 作者） | Textual；经 ACP 统一多家前端 | — | 2025-12 发布 |

## 5. diff 与 markdown 渲染

- **diff 无标准库**：`difflib.unified_diff()` + `rich.Syntax(lexer="diff")`（Pygments 上色）是通行做法；Rich 官方明确不做内置 diff 模块
- 辅助库：`moreorless`（彩色输出）、`whatthepatch`（解析/apply unified diff）、`diff-match-patch`（Aider 用于编辑应用）
- Textual 无内置 Diff widget → 自实现（deepagents 的 `tui/widgets/diff.py` 可参考）
- markdown：`rich.markdown.Markdown`（markdown-it-py 4.2.0 + pygments 2.21.0）；Textual 流式用 `Markdown.get_stream`

## 6. 未核验项

httpx-sse 是否计划支持 httpx2（未找到）；mini-swe-agent 中 textual 的具体用途；open-interpreter Rust 重写细节（第三方来源）；uv CI 细节。
