"""Textual TUI（票据 05）：只消费 AgentLoop 的事件流，不做业务逻辑（SPEC §J）。

架构纪律：界面所见 = 无头行为——同一套事件（loop.py），不同呈现；会话文件始终是唯一事实源。
本模块负责：把事件渲染成对话流（流式 Markdown、可折叠工具块）、收集输入、Ctrl+C 中断当前回合。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Markdown, Static
from textual.widgets.markdown import MarkdownStream

from codelotte.cost import Ledger, call_record_from_entry, format_money
from codelotte.display import (
    args_preview,
    compaction_after_share,
    compaction_title,
    compaction_utilization,
    duration_text,
    guardrail_notice,
    guardrail_stop_text,
    preview_text,
    tool_title,
)
from codelotte.loop import (
    AgentLoop,
    CompactionEvent,
    CostRecorded,
    GuardrailTriggered,
    ToolFinished,
    ToolRequested,
    TurnEnded,
)
from codelotte.permissions import (
    DECISION_ALWAYS,
    DECISION_DENY,
    DECISION_ONCE,
    DECISION_SESSION,
    PermissionRequest,
)
from codelotte.guardrails import EVENT_GUARDRAIL
from codelotte.providers.base import ProviderError, ReasoningDelta, TextDelta
from codelotte.session.context import INTERRUPTED_TOOL_NOTE

_CSS = """
#transcript { height: 1fr; padding: 0 1; }
#status { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
#prompt { border: none; }
ToolCallBlock { margin: 0 0 1 0; }
ToolCallBlock > .tool-args { color: $text-muted; }
ToolCallBlock > .tool-result { padding: 0 0 1 0; }
ToolCallBlock.tool-failed CollapsibleTitle { color: $error; }
ToolCallBlock.tool-interrupted CollapsibleTitle { color: $warning; }
CompactionBlock { margin: 0 0 1 0; }
CompactionBlock CollapsibleTitle { color: $warning; }
#approval-box { width: 90%; max-width: 100; background: $surface; border: round $warning; padding: 1 2; }
#approval-box .approval-line { margin: 0 0 1 0; }
#approval-buttons { height: auto; }
/* 单行色块按钮（compact：无边框）：默认档的 ▔/▁ 字形边条在部分终端里会错位/缺字，
   这里一律不依赖特殊字形——底色即按钮，等宽平分一行，悬停/焦点只换文字样式 */
#approval-buttons Button { width: 1fr; min-width: 0; height: 1; margin-right: 1; }
#approval-buttons .approval-plain { background: $surface-lighten-1; }
#approval-buttons .approval-plain:hover { background: $surface-lighten-2; }
#approval-buttons .approval-strong { background: white; color: black; }
#approval-buttons .approval-strong:focus { text-style: bold; }  /* 白底上不用反色焦点，反色会盖掉白底 */
#approval-buttons Button:focus { text-style: bold reverse; }
"""

_ARG_PREVIEW_MAX = 60
_BODY_MAX = 1600
_RESULT_MAX = 700


def _args_body(arguments: str, parse_error: str | None) -> Text:
    if parse_error is not None:
        return Text(f"（参数畸形：{parse_error}）\n{arguments}", style="yellow")
    try:
        pretty = json.dumps(json.loads(arguments), ensure_ascii=False, indent=2)
    except ValueError:
        pretty = arguments
    return Text(_short_multiline(pretty, _BODY_MAX))


def _short_multiline(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…（共 {len(text)} 字符）"


class ToolCallBlock(Collapsible):
    """一次工具调用：默认收起，标题带状态；展开可见参数与结果摘要（票据 05 验收）。"""

    def __init__(
        self, *, call_id: str, name: str, arguments: str, parse_error: str | None
    ) -> None:
        self.call_id = call_id
        self.tool_name = name
        self.finished = False
        self._preview = args_preview(name, arguments, limit=_ARG_PREVIEW_MAX)
        super().__init__(
            Static(_args_body(arguments, parse_error), classes="tool-args"),
            Static("运行中…", classes="tool-result"),
            title=self._title_text("…"),
            collapsed=True,
        )

    def _title_text(self, status: str) -> str:
        return tool_title(self.tool_name, self._preview, status)

    def mark_finished(self, *, ok: bool, content: str, duration_ms: int) -> None:
        self.finished = True
        # 标题不带耗时/随机内容：收起标题要可快照（耗时放展开体里）
        self.title = self._title_text("✓" if ok else "✗")
        if not ok:
            self.add_class("tool-failed")  # 标题变红的样式钩子（CSS 里接）
        head = duration_text(duration_ms) + "\n"
        body = _short_multiline(content, _RESULT_MAX)
        result = self.query_one(".tool-result", Static)
        result.update(Text(head + body, style="" if ok else "red"))

    def mark_interrupted(self) -> None:
        """回合被中断、这次调用没有结果：块停在"运行中…"会误导——给明确的收尾。"""
        if self.finished:
            return
        self.finished = True
        self.title = self._title_text("⏸ 已中断")
        self.add_class("tool-interrupted")
        self.query_one(".tool-result", Static).update(
            Text(INTERRUPTED_TOOL_NOTE, style="yellow")
        )


class CompactionBlock(Collapsible):
    """一次上下文压缩：收起标题带触发方式与前后占比，展开可看摘要（票据 12）。"""

    def __init__(
        self,
        *,
        mode: str,
        utilization: float,
        window: int,
        after_tokens: int,
        summary: str,
        warning: str | None,
    ) -> None:
        text = (f"⚠ {warning}\n\n" if warning else "") + summary
        title = compaction_title(
            mode, utilization, compaction_after_share(after_tokens, window)
        )
        super().__init__(
            Static(Text(text, style="dim"), classes="compaction-summary"),
            title=f"⚠ {title}" if warning else title,
            collapsed=True,
        )


class ApprovalScreen(ModalScreen[str | None]):
    """权限审批弹层（票据 09）：四档 = 本次 / 本会话 / 始终（写用户级）/ 拒绝。

    返回值即决策常量；Esc / 关闭弹层视为拒绝。键位：y / s / a / n。
    """

    # 注意：Textual 的 Binding action 必须是字面量，无法内插 DECISION_* 常量——
    # 改常量名时这里要连带改（按钮用常量 id，见 compose）
    BINDINGS = [
        Binding("y", "decide('once')", "本次允许"),
        Binding("s", "decide('session')", "本会话允许"),
        Binding("a", "decide('always')", "始终允许"),
        Binding("n", "decide('deny')", "拒绝"),
        Binding("escape", "decide('deny')", "拒绝"),
    ]

    def __init__(self, request: PermissionRequest) -> None:
        super().__init__()
        self._request = request

    def compose(self) -> ComposeResult:
        request = self._request
        what = request.subject if request.subject is not None else json.dumps(
            request.arguments, ensure_ascii=False
        )
        matched = (
            f"匹配规则：{request.rule.text}（{request.rule.source}，ask）"
            if request.rule is not None
            else "匹配规则：无（默认询问）"
        )
        with Vertical(id="approval-box"):
            yield Static(Text("🔒 权限请求：模型想执行一个操作", style="bold"))
            yield Static(
                Text.assemble(
                    ("工具  ", "dim"), (request.tool, "bold"),
                ),
                classes="approval-line",
            )
            yield Static(
                Text.assemble(("内容  ", "dim"), (preview_text(what, 400), "")),
                classes="approval-line",
            )
            yield Static(Text(matched, style="dim"), classes="approval-line")
            with Horizontal(id="approval-buttons"):
                # compact：无边框单行色块（不用 ▔/▁ 边条——部分终端字体下会错位，见 CSS 注释）；
                # approval-strong：本次允许 = 最常用的默认档，白底黑字最显眼
                yield Button("本次允许 (y)", id=DECISION_ONCE, compact=True, classes="approval-strong")
                # approval-plain：default 档没有自己的底色，给个可见的（见 CSS）
                yield Button("本会话允许 (s)", id=DECISION_SESSION, compact=True, classes="approval-plain")
                yield Button("始终允许 (a)", id=DECISION_ALWAYS, variant="warning", compact=True)
                yield Button("拒绝 (n)", id=DECISION_DENY, variant="error", compact=True)

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_decide(self, decision: str) -> None:
        self.dismiss(decision)


class TuiApp(App[None]):
    """交互式界面：上方对话流（流式 Markdown + 折叠工具块），底部状态栏与输入框。"""

    TITLE = "codelotte"
    CSS = _CSS
    BINDINGS = [
        Binding("ctrl+c", "interrupt_or_quit", "中断当前回合 / 退出", priority=True)
    ]

    def __init__(
        self,
        *,
        agent: AgentLoop,
        model: str,
        context_window: int | None = None,
        startup_notices: Sequence[str] = (),
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._model = model  # 展示名（随包目录的名字，用户级 models.json 可覆盖）
        self._context_window = context_window  # 上下文占用百分比的分母（state 栏）
        self._startup_notices = list(startup_notices)
        self._history = history or []
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_active = False  # 显式状态位：任务自己的 finally 里刷新时，"任务还没正式结束"不算运行中
        self._interrupt_requested = False
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        self._reasoning: Static | None = None  # 当前思考块（文本一出现就收尾，下次思考新开一块）
        self._reasoning_parts: list[str] = []
        self._tool_blocks: dict[str, ToolCallBlock] = {}
        self._ledger = Ledger()  # 账单累计（历史回放 + 实时事件同一本账，票据 07）
        # 压缩后的上下文占用估算（票据 12）：摘要调用的 usage 是"压缩前"的大小，
        # 下一次正常调用的 CostRecorded 到来前，状态栏先用压缩后的估算值。
        self._context_override: int | None = None
        agent.approver = self._approve  # 权限审批走弹层（票据 09）；-p 模式没有此处、fail-closed

    # ---- 组装与启动 ----

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="transcript")
        yield Static(self._status_text(), id="status")
        yield Input(
            placeholder="输入任务，Enter 发送 · Ctrl+C 中断当前回合（空闲时再按一次退出）",
            id="prompt",
        )

    async def on_mount(self) -> None:
        for note in self._startup_notices:  # 启动提示（如更新内容）：完整文本挂进对话流
            await self._mount_notice(note)
        for note in self._agent.permissions.notices:  # 权限层加载提示（如未信任的项目规则被忽略）
            await self._mount_notice(f"⚠ {note}")
        self.query_one(Input).focus()
        if self._history:
            await self._render_history()

    async def _approve(self, request: PermissionRequest) -> str:
        """审批者（注入 AgentLoop）：弹层拿决策；弹层被异常关闭时按拒绝处理。"""
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        def _done(value: str | None) -> None:
            if not future.done():
                future.set_result(value or DECISION_DENY)

        self.push_screen(ApprovalScreen(request), _done)
        return await future

    @property
    def turn_running(self) -> bool:
        return self._turn_active

    # ---- 输入 ----

    @on(Input.Submitted)
    async def _on_submit(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return
        if self.turn_running:
            await self._mount_notice("（上一回合还在运行：Ctrl+C 可中断，然后再来）")
            return
        event.input.clear()
        await self._mount(self._user_widget(prompt))
        self._turn_active = True
        self._turn_task = asyncio.create_task(self._run_turn(prompt))

    def _close_approval(self) -> None:
        """关掉还开着的审批弹层（None → 拒绝）；取消/中断路径收尾共用。"""
        if isinstance(self.screen, ApprovalScreen):
            self.screen.dismiss(None)

    async def action_interrupt_or_quit(self) -> None:
        self._close_approval()  # 审批弹层里按 Ctrl+C：该调用按拒绝处理
        if self.turn_running:
            self._interrupt_requested = True
            assert self._turn_task is not None
            self._turn_task.cancel()
            try:
                await self._turn_task
            except (
                asyncio.CancelledError
            ):  # pragma: no cover - 兜底，正常在 _run_turn 内消化
                pass
            self._turn_task = None
            self.query_one(Input).focus()
            self._refresh_status()
            return
        self.exit()  # 空闲时 Ctrl+C = 退出（会话文件已落盘，可 --continue 回来）

    # ---- 回合消费 ----

    async def _run_turn(self, prompt: str) -> None:
        self._interrupt_requested = False
        self._refresh_status()
        try:
            async for event in self._agent.run_turn(prompt):
                await self._handle(event)
        except asyncio.CancelledError:
            self._close_approval()  # 取消时弹层还开着：关掉（按拒绝）
            await self._end_markdown()
            self._mark_unfinished_tools()  # 停在"运行中…"的块要给明确收尾，别骗人
            if self._interrupt_requested:
                await self._mount_notice(
                    "⏸ 已中断（Ctrl+C）——会话已保存，可继续输入或稍后 --continue"
                )
            return
        except ProviderError as exc:
            await self._end_markdown()
            await self._mount_notice(f"⚠ 模型调用失败：{exc}")
        finally:
            # 回合结束一律收掉思考块：失败/中断路径不收尾的话，下一回合的思考会拼进旧块（审查修正）
            self._close_reasoning()
            await self._end_markdown()
            self._turn_active = False
            self._refresh_status()

    async def _handle(self, event: object) -> None:
        if isinstance(event, TextDelta):
            self._close_reasoning()  # 正文出现：思考块收尾（下次思考新开一块）
            await self._write_markdown(event.text)
        elif isinstance(event, ReasoningDelta):
            # 思考事件只在开启时出现（reasoning_effort 为 none 时接口不产生）——来了就展示
            await self._write_reasoning(event.text)
        elif isinstance(event, CostRecorded):
            self._context_override = None  # 新的真实 usage 已到，压缩估算不再是当前值
            self._ledger.record(event.record)  # 计价在 loop 落盘时算好，界面只累计
            self._refresh_status()
        elif isinstance(event, ToolRequested):
            self._close_reasoning()
            await self._end_markdown()
            block = self._new_tool_block(
                call_id=event.call_id,
                name=event.name,
                arguments=event.arguments,
                parse_error=event.parse_error,
            )
            await self._mount(block)
        elif isinstance(event, ToolFinished):
            block = self._tool_blocks.get(event.call_id)
            if block is not None:
                block.mark_finished(
                    ok=event.ok, content=event.content, duration_ms=event.duration_ms
                )
                self._scroll_end()
        elif isinstance(event, GuardrailTriggered):
            await self._mount_guardrail(event.layer, event.message)
        elif isinstance(event, CompactionEvent):
            self._context_override = event.after_tokens
            await self._end_markdown()
            if event.warning:
                await self._mount_notice(f"⚠ {event.warning}")  # 折叠块外可见
            await self._mount(
                CompactionBlock(
                    mode=event.mode,
                    utilization=event.utilization,
                    window=event.window,
                    after_tokens=event.after_tokens,
                    summary=event.summary,
                    warning=event.warning,
                )
            )
            self._refresh_status()
        elif isinstance(event, TurnEnded):
            self._close_reasoning()
            await self._end_markdown()
            if event.guardrail_stop is not None:
                await self._mount_notice(
                    f"⚠ 本回合已被死循环防御终止"
                    f"（{guardrail_stop_text(event.guardrail_stop)}）——"
                    "会话已保存，可继续输入或稍后 --continue"
                )
            if event.hit_iteration_cap:
                await self._mount_notice(
                    "⚠ 已达迭代上限，回合被强制结束（详见会话记录）"
                )

    # ---- 渲染 ----

    @staticmethod
    def _user_widget(text: str) -> Static:
        return Static(Text.assemble(("❯ ", "bold cyan"), (text, "bold")))

    def _new_tool_block(
        self, *, call_id: str, name: str, arguments: str, parse_error: str | None
    ) -> ToolCallBlock:
        """建块并登记到按 call_id 索引的表里（ToolFinished / 历史回放都靠它对上号）。"""
        block = ToolCallBlock(
            call_id=call_id, name=name, arguments=arguments, parse_error=parse_error
        )
        self._tool_blocks[call_id] = block
        return block

    async def _mount(self, widget: Any) -> None:
        await self.query_one("#transcript", VerticalScroll).mount(widget)
        self._scroll_end()

    def _scroll_end(self) -> None:
        self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    async def _mount_notice(self, text: str) -> None:
        await self._end_markdown()
        await self._mount(Static(Text(text, style="yellow")))

    async def _mount_guardrail(self, layer: str, message: str) -> None:
        """死循环防御事件（票据 11）：比普通提示更醒目（加粗黄）；TUI 与导出口径一致。"""
        await self._end_markdown()
        await self._mount(Static(Text(guardrail_notice(layer, message), style="bold yellow")))

    async def _write_reasoning(self, text: str) -> None:
        """思考增量：懒建一块暗色 Static，随到随刷（正文/工具出现时收尾，见 _close_reasoning）。"""
        if self._reasoning is None:
            self._reasoning = Static(Text("", style="dim"))
            self._reasoning_parts = []
            await self._mount(self._reasoning)
        self._reasoning_parts.append(text)
        self._reasoning.update(Text("".join(self._reasoning_parts), style="dim"))
        self._scroll_end()

    def _close_reasoning(self) -> None:
        if self._reasoning is not None:
            self._reasoning = None
            self._reasoning_parts = []

    async def _write_markdown(self, text: str) -> None:
        stream = self._stream
        if stream is None:
            self._markdown = Markdown()
            await self._mount(self._markdown)
            stream = Markdown.get_stream(self._markdown)
            self._stream = stream
        await stream.write(text)
        self._scroll_end()

    async def _end_markdown(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
        self._stream = None
        self._markdown = None

    async def _render_history(self) -> None:
        """--continue 启动时把既有轨迹回放出来（只读渲染；消息数组来自同一份记录）。"""
        for entry in self._history:
            kind = entry.get("type")
            if kind == "message" and entry.get("role") == "user":
                await self._mount(self._user_widget(entry.get("content", "")))
            elif kind == "message" and entry.get("role") == "assistant":
                if entry.get("content"):
                    await self._mount(Markdown(entry["content"]))
                if entry.get("stopReason") == "interrupted":
                    await self._mount_notice("⏸ 上一次运行在此中断")
            elif kind == "tool_call":
                arguments = entry.get("arguments", "")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                block = self._new_tool_block(
                    call_id=str(entry.get("toolCallId", "")),
                    name=str(entry.get("name", "?")),
                    arguments=arguments,
                    parse_error=(
                        str(entry["parseError"]) if entry.get("parseError") else None
                    ),
                )
                await self._mount(block)
            elif kind == "tool_result":
                block = self._tool_blocks.get(str(entry.get("toolCallId", "")))
                if block is not None:
                    block.mark_finished(
                        ok=bool(entry.get("ok")),
                        content=str(entry.get("content", "")),
                        duration_ms=int(entry.get("durationMs", 0)),
                    )
            elif kind == "event" and entry.get("kind") == EVENT_GUARDRAIL:
                # 回放历史拦截（票据 11）：与实时事件同一句话（display.guardrail_notice）
                await self._mount_guardrail(
                    str(entry.get("layer", "")), str(entry.get("message", ""))
                )
            elif kind == "compaction":
                # 压缩点（票据 12）：历史里也画出来，摘要可展开查看
                window = int(entry.get("window", 0) or 0)
                before_tokens = int(entry.get("beforeTokens", 0) or 0)
                after_tokens = int(entry.get("estimatedAfterTokens", 0) or 0)
                warning = str(entry["warning"]) if entry.get("warning") else None
                self._context_override = after_tokens or None
                if warning:
                    await self._mount_notice(f"⚠ {warning}")  # 折叠块外可见
                await self._mount(
                    CompactionBlock(
                        mode=str(entry.get("mode", "soft")),
                        utilization=compaction_utilization(
                            before_tokens, window, entry.get("utilization")
                        ),
                        window=window,
                        after_tokens=after_tokens,
                        summary=str(entry.get("summary", "")),
                        warning=warning,
                    )
                )
            elif (
                kind == "usage"
            ):  # 恢复会话后状态栏要把已有用量也带上（记录里有的，界面也要有）
                self._context_override = None
                self._ledger.record(call_record_from_entry(entry))
        self._mark_unfinished_tools()  # 中断在工具执行中的旧调用：回放不能显示"运行中"
        self._refresh_status()

    def _status_text(self) -> Text:
        text = Text()
        if self.turn_running:
            text.append("▶ 运行中", style="bold green")
        else:
            text.append("● 就绪", style="dim")
        text.append(f"  │  {self._model}")
        if (self._ledger.calls or self._context_override is not None) and self._context_window:
            # 上下文占用：最近一次请求的输入 tokens / 用户级生效窗口（与压缩阈值同源）。
            # 压缩后到下一次真实请求前，用压缩后的估算值（摘要调用的 usage 是压缩前的大小）。
            # >100% 是超**用户预算**（请求本身不会失败——真实上限是官方值），标"超预算"。
            used = (
                self._context_override
                if self._context_override is not None
                else self._ledger.calls[-1].input_tokens
            )
            share = used / self._context_window
            label = f"超预算 {share:.0%}" if share > 1 else f"{share:.1%}"
            text.append(f"  │  上下文 {label}")
        if self._ledger.calls:
            text.append(
                f"  │  tokens in={self._ledger.input_tokens} out={self._ledger.output_tokens}"
                f" 缓存命中 {self._ledger.hit_rate_text}"
            )
            if self._ledger.priced:  # 累计花费（票据 07 验收：token/花费/命中率并列）
                text.append(
                    f"  │  ≈{format_money(self._ledger.cost, self._agent.catalog.currency)}"
                )
        text.append(f"  │  {Path(self._agent.session_path).name}")
        return text

    def _mark_unfinished_tools(self) -> None:
        for block in self._tool_blocks.values():
            block.mark_interrupted()

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self._status_text())
