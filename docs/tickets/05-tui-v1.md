# 05: TUI v1（Textual 终端界面）

**What to build:** 给命令行套上交互式终端界面：上方滚动区展示对话流（模型文本流式渲染、代码高亮）；工具调用以可折叠区块显示（工具名 + 参数 + 结果摘要）；底部输入框与状态栏（当前模型、token 用量）；Ctrl+C 中断当前回合但不退出会话，状态完好可 `--continue` 恢复。架构纪律：界面只消费循环广播的结构化事件流，不直接读取内部状态——保证"界面所见"与"无头模式行为"一致。

🗣 大白话：装上仪表盘——看得见 agent 正在干什么（而不是干等黑屏），出问题随时能叫停。

**Blocked by:** 04（write / edit / bash 工具 + 本地执行器）

**Status:** done（2026-10-15；自动化全绿 + Windows Terminal 真机人工验证通过）

- [x] `codelotte`（无参数）进入交互界面，能完成一次真实的多工具任务（自动化：脚本化模型 + 真实工具全链路；真机人工验证通过）
- [x] 工具调用以折叠块展示（默认收起，展开见参数与结果摘要）
- [x] Ctrl+C 中断当前回合后 `--continue` 恢复，轨迹完整无重复无丢失（组件测试 + 无头 e2e 双覆盖）
- [x] 渲染快照测试就位（首批快照：空会话 / 流式文本 / 工具块 / 中断态）
- [x] 在 Windows Terminal 中人工验证运行通畅（目标环境）——2026-10-15 用户真机确认可用

## 实施记录（2026-10-15）

- **架构：循环事件流落地（SPEC §A 的欠账还上）**。原 `run.py` 把循环与打印混在一起；本票抽出 [loop.py](../../src/codelotte/loop.py)：`AgentLoop.run_turn()` 是异步生成器，广播两类事件——`TextDelta/ReasoningDelta/UsageEvent`（Provider 层直通）+ `ToolRequested/ToolFinished/TurnEnded`（本层）。`run.py` 变成无头模式的一个"呈现消费者"（终端行为逐字保持，原 e2e 测试零改动全数通过）；`tui/` 是第二个消费者。同一套事件、两种呈现——"界面所见 = 无头行为"是结构保证而不是口号。中断路径补强：Ctrl+C 时已看到的文本先落盘（stopReason=interrupted）再放行取消（原来只有 ProviderError 落盘，取消会丢——"轨迹完整"验收把它补上了）。
- **TUI**（[tui/app.py](../../src/codelotte/tui/app.py) 单文件）：上方滚动区 = `Markdown` + `MarkdownStream` 流式渲染；工具调用是 `Collapsible` 子类 `ToolCallBlock`（默认收起；标题=工具名+参数预览+✓/✗，展开体=完整参数与结果摘要；耗时放展开体——收起标题必须可快照）；底部状态栏（就绪/运行中、模型、token、缓存命中率、会话名）+ `Input`。Ctrl+C 以 priority 抢占 Textual 默认行为：回合中=中断、空闲=退出。v1 不渲染思考过程（-r 语义保留给无头；会话文件里都在）。
- **`--continue`（本票先做线性版，票据 06 升级为树）**：`SessionStore.resume`（同一文件续写、id 链接上）+ `latest_session_path`（本项目目录按 mtime 取最近）；新增 [session/context.py](../../src/codelotte/session/context.py)`::messages_from_entries` 做上下文装配——重建规则：interrupted 的 assistant 跳过（原进程里它从未发给模型）、缺 tool_result 的 tool_call 补"中断说明"（协议要求每个 tool_call 都有 tool 消息，缺一个整体 400）、键序固定保证前缀可复现。CLI 加 `-c/--continue`（TUI 与 `-p` 通用）。
- **测试**：pytest-textual-snapshot 四张首批快照进 `tests/__snapshots__/`；组件测试用 pilot 驱动 + Provider 缝脚本化假客户端（[tests/fake_client.py](../../tests/fake_client.py)，含 PAUSE 与"就地抛 ProviderError"两种剧本控制流）。新增：loop 7、TUI 7（含 4 快照）、会话恢复 6、`--continue` 无头 e2e 1、CLI 3。
- **快照测试当场抓到两个真 bug（价值证明）**：① 回合结束后状态栏仍显示"运行中"——`_refresh_status` 在任务自己的 finally 里跑，基于 `task.done()` 的判断此刻还没翻；改为显式状态位。② 该状态位最初命名 `_running`，撞了 Textual `MessagePump` 的内部字段（消息泵直接卡死，6 个测试挂掉）；改名 `_turn_active`。教训入册：**给 App 子类加私有字段前先查基类。**
- **两轴代码审查（Standards / Spec）后修正**。Spec 轴实测抓到两个真缺口：① **取消落在工具执行中**时，`messages` 里 assistant 声明的 tool_calls 缺 tool 应答——同进程下一回合请求整个 400（`--continue` 换进程没事，context 重建会补，但 TUI 不退出会话）。修法：占位应答先于一切挂起点落进 `messages`、执行完原地回填（`_run_call`），TUI 侧把未完成的块标"⏸ 已中断"、回放同理。② **配置失败的启动留下"只有会话头"的空文件**，`--continue` 按 mtime 会挑中它把真实历史跳过。修法：装配顺序改为"先读配置、后建会话文件"。其余修正：`--continue` 回放把记录里的 usage 带回状态栏；assistant 消息的 wire 形状收拢到 `providers/base.assistant_message`（实时与恢复两条路径共用一处）；无 tty 时启动 TUI 给可读错误而不是往管道喷全屏转义码。新增回归测试 3 项。
- 测试：全套 162 项全绿（4 张快照稳定通过）；ruff / pyright 干净。

## 真机验证记录（Windows Terminal，2026-10-15）

用户真机确认可用，核对过的流程：

1. `codelotte` → 输入真实多工具任务，流式渲染与折叠块正常。
2. 回合中 Ctrl+C → 中断标记出现、界面不退出；`codelotte --continue` 带历史继续。
3. 视觉打磨（配色/间距）不阻塞本票验收。
