# 15: 客户端与演示（远程 CLI + 单页 HTML）

**What to build:** serve 需要客户端，但**不新增 UI 体系**——复用现有事件流。

1. **事件编解码**：`TextDelta` / `ReasoningDelta` / `ToolRequested` / `ToolFinished` /
   `CostRecorded` / `CompactionEvent` / `GuardrailTriggered` / `RunEnded` 的 JSON 双向序列化。
   事件结构以 [loop.py](../../../../src/codelotte/loop.py) 的定义为准，不在 serve 侧重造一套。
2. **远程 CLI**：`codelotte --remote <url> -p "..."`。把 [run.py](../../../../src/codelotte/run.py)
   里 `AgentLoop.run()` 这个事件源换成「SSE 异步迭代器」，`_Presenter` 一行不改。
3. **单页 HTML**：`deploy/web/index.html`，vanilla JS + `EventSource`，无构建、无框架。
   功能只有四件：填 key 与 prompt、提交、看 job 状态、看流式输出。
4. **断线重连**：`Last-Event-ID` 续传，重连后不重复渲染已显示的事件。
5. **录屏脚本**：一条命令起服务 + 打开页面 + 提交示例任务的演示流程。

**明确不做**：远程 Textual TUI（审批弹层在 fail-closed 服务端没有对应交互）、SPA / 登录页 /
会话列表页、SSE 压缩（保持纯文本 `text/event-stream`，便于抓包与调试）。

🗣 大白话：界面不重写，只是给同一条事件流换个入口——终端一个、浏览器一个。

**Blocked by:** 11

**Status:** ready-for-agent

- [ ] `serve/events_codec.py`：8 种事件的 to_dict / from_dict，与 loop 的 dataclass 一一对应
- [ ] 往返测试：事件 → JSON → 事件，类型与字段完全一致（含可选字段缺省）
- [ ] `codelotte --remote <url> -p "..."`：走 SSE 事件源；`_Presenter` 不改
- [ ] 远程 `-p` 与本地 `-p` 在同一 fake provider 脚本下输出结构一致（文本/工具/用量三段）
- [ ] `deploy/web/index.html`：提交 → 轮询状态 → EventSource 渲染；无外链、无构建
- [ ] `deploy/web/README.md`：怎么起、怎么用、后端地址从哪来
- [ ] 断线重连：手动断开再连，`Last-Event-ID` 续传，事件不重不漏
- [ ] SSE 不启用压缩；响应头不含 `Content-Encoding`
- [ ] 录屏脚本 `deploy/demo.sh`：起服务 + 种子数据 + 提交示例 + 打印提示
- [ ] 测试：远程客户端在服务端 503（队列饱和）时给出可读错误，而不是崩栈
