"""Textual TUI（票据 05）：只消费 AgentLoop 的事件流，不做业务逻辑（SPEC §J）。

架构纪律：界面所见 = 无头行为——同一套事件（loop.py），不同呈现；会话文件始终是唯一事实源。
本模块负责：把事件渲染成对话流（流式 Markdown、可折叠工具块）、收集输入、Ctrl+C 中断当前回合。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Collapsible, Input, Markdown, Static
from textual.widgets.markdown import MarkdownStream

from codelotte.loop import AgentLoop, ToolFinished, ToolRequested, TurnEnded
from codelotte.providers.base import (
    ProviderError,
    ReasoningDelta,
    TextDelta,
    UsageEvent,
)
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
"""

_ARG_PREVIEW_MAX = 60
_BODY_MAX = 1600
_RESULT_MAX = 700


def _short(text: str, limit: int) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _args_preview(name: str, arguments: str) -> str:
    """工具块标题上的参数预览：常用工具取关键字段，其他给压缩后的原始文本。"""
    try:
        args = json.loads(arguments)
    except ValueError:
        return _short(arguments, _ARG_PREVIEW_MAX)
    if not isinstance(args, dict):
        return _short(arguments, _ARG_PREVIEW_MAX)
    if name == "bash" and "command" in args:
        return _short(str(args["command"]), _ARG_PREVIEW_MAX)
    if "path" in args:
        return _short(str(args["path"]), _ARG_PREVIEW_MAX)
    return _short(json.dumps(args, ensure_ascii=False), _ARG_PREVIEW_MAX)


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
        self._preview = _args_preview(name, arguments)
        super().__init__(
            Static(_args_body(arguments, parse_error), classes="tool-args"),
            Static("运行中…", classes="tool-result"),
            title=self._title_text("…"),
            collapsed=True,
        )

    def _title_text(self, status: str) -> str:
        return f"⚙ {self.tool_name}  {self._preview}  {status}"

    def mark_finished(self, *, ok: bool, content: str, duration_ms: int) -> None:
        self.finished = True
        # 标题不带耗时/随机内容：收起标题要可快照（耗时放展开体里）
        self.title = self._title_text("✓" if ok else "✗")
        if not ok:
            self.add_class("tool-failed")  # 标题变红的样式钩子（CSS 里接）
        head = f"（{duration_ms}ms）\n"
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
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._model = model
        self._history = history or []
        self._turn_task: asyncio.Task[None] | None = None
        self._turn_active = False  # 显式状态位：任务自己的 finally 里刷新时，"任务还没正式结束"不算运行中
        self._interrupt_requested = False
        self._markdown: Markdown | None = None
        self._stream: MarkdownStream | None = None
        self._tool_blocks: dict[str, ToolCallBlock] = {}
        self._in_tokens = self._out_tokens = self._hit_tokens = self._miss_tokens = 0

    # ---- 组装与启动 ----

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="transcript")
        yield Static(self._status_text(), id="status")
        yield Input(
            placeholder="输入任务，Enter 发送 · Ctrl+C 中断当前回合（空闲时再按一次退出）",
            id="prompt",
        )

    async def on_mount(self) -> None:
        self.query_one(Input).focus()
        if self._history:
            await self._render_history()

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

    async def action_interrupt_or_quit(self) -> None:
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
            await self._end_markdown()
            self._turn_active = False
            self._refresh_status()

    async def _handle(self, event: object) -> None:
        if isinstance(event, TextDelta):
            await self._write_markdown(event.text)
        elif isinstance(event, ReasoningDelta):
            pass  # v1 不显示思考过程（-r 的语义保留给无头模式；会话文件里有）
        elif isinstance(event, UsageEvent):
            usage = event.usage
            self._in_tokens += usage.input_tokens
            self._out_tokens += usage.output_tokens
            self._hit_tokens += usage.cache_hit_tokens
            self._miss_tokens += usage.cache_miss_tokens
            self._refresh_status()
        elif isinstance(event, ToolRequested):
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
        elif isinstance(event, TurnEnded):
            await self._end_markdown()
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
            elif (
                kind == "usage"
            ):  # 恢复会话后状态栏要把已有用量也带上（记录里有的，界面也要有）
                self._in_tokens += int(entry.get("inputTokens", 0))
                self._out_tokens += int(entry.get("outputTokens", 0))
                self._hit_tokens += int(entry.get("cacheHitTokens", 0))
                self._miss_tokens += int(entry.get("cacheMissTokens", 0))
        self._mark_unfinished_tools()  # 中断在工具执行中的旧调用：回放不能显示"运行中"
        self._refresh_status()

    def _status_text(self) -> Text:
        text = Text()
        if self.turn_running:
            text.append("▶ 运行中", style="bold green")
        else:
            text.append("● 就绪", style="dim")
        text.append(f"  │  {self._model}")
        if self._in_tokens or self._out_tokens:
            cached = self._hit_tokens + self._miss_tokens
            rate = f"{self._hit_tokens / cached:.0%}" if cached else "—"
            text.append(
                f"  │  tokens in={self._in_tokens} out={self._out_tokens} 缓存命中 {rate}"
            )
        text.append(f"  │  {Path(self._agent.session_path).name}")
        return text

    def _mark_unfinished_tools(self) -> None:
        for block in self._tool_blocks.values():
            block.mark_interrupted()

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self._status_text())
