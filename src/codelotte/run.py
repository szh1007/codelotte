"""无头单次执行（-p 模式）：消费 AgentLoop 的事件流，按终端约定呈现（票据 02 起冻结的行为）。

终端约定：真终端（stdout 是 tty）里模型文本实时流式输出（人要看进度）；管道/重定向时
不实时写，轮末才决定去向——**终轮的文本（答案）进 stdout，中间轮次的过渡叙述进 stderr**，
管道拿到的是纯净答案。思考过程（reasoning_content）、工具活动与用量总结始终走 stderr。
工具失败不是异常：错误文本作为工具结果回传模型自纠，循环继续（SPEC §D）。

除了"怎么呈现"，这里不做任何业务逻辑——落盘、工具执行、循环控制都在 loop.py。
"""

from __future__ import annotations

import json
import sys

from codelotte.loop import (
    MAX_ITERATIONS,
    AgentLoop,
    ToolFinished,
    ToolRequested,
    TurnEnded,
)
from codelotte.providers.base import ReasoningDelta, TextDelta, UsageEvent

__all__ = ["run_once"]

_ANSI_DIM = "\x1b[2m"
_ANSI_RESET = "\x1b[0m"
_PREVIEW_LIMIT = 200  # stderr 上工具参数/错误文本的显示上限


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class _Presenter:
    """事件流 → 终端输出。行为自票据 02/03 冻结，改动等于改验收，须连带改 e2e 测试。"""

    def __init__(self, *, show_reasoning: bool) -> None:
        self.live = sys.stdout.isatty()
        self._show_reasoning = show_reasoning  # 打印与否看开关；颜色才看是不是真终端
        dim = _ANSI_DIM if (show_reasoning and sys.stderr.isatty()) else ""
        self._dim = dim
        self._reset = _ANSI_RESET if dim else ""
        self._reasoning_open = False
        self._text: list[str] = []  # 当前模型调用的文本（非 live 时轮末才决定去向）

    # ---- 事件入口 ----

    def on_text(self, text: str) -> None:
        self._close_reasoning()
        self._text.append(text)
        if self.live:
            sys.stdout.write(text)
            sys.stdout.flush()

    def on_reasoning(self, text: str) -> None:
        if not self._show_reasoning:
            return  # 未开启 -r：思考过程只落盘不打印
        if not self._reasoning_open:
            sys.stderr.write(self._dim)
            self._reasoning_open = True
        sys.stderr.write(text)
        sys.stderr.flush()

    def on_tool_requested(self, event: ToolRequested) -> None:
        self._close_reasoning()
        self._finish_text(intermediate=True)  # 带工具调用的轮次：文本是过渡叙述
        if event.parse_error is not None:
            sys.stderr.write(f"[codelotte] → {event.name}（参数畸形，未执行）\n")
        else:
            display = json.dumps(
                json.loads(event.arguments), ensure_ascii=False, separators=(",", ":")
            )
            sys.stderr.write(f"[codelotte] → {event.name}({_preview(display)})\n")
        sys.stderr.flush()

    def on_tool_finished(self, event: ToolFinished) -> None:
        if event.ok:
            size = len(event.content)
            sys.stderr.write(
                f"[codelotte] ← {event.name} {event.duration_ms}ms，结果 {size} 字符\n"
            )
        else:
            sys.stderr.write(
                f"[codelotte] ← {event.name} 失败：{_preview(event.content)}\n"
            )
        sys.stderr.flush()

    def on_turn_ended(self) -> None:
        self._close_reasoning()
        self._finish_text(intermediate=False)  # 终轮文本：答案

    def close(self) -> None:
        """收尾（失败/中断路径也要跑）：思考块收行、残留文本按终轮路由。"""
        self._close_reasoning()
        self._finish_text(intermediate=False)

    # ---- 内部 ----

    def _close_reasoning(self) -> None:
        if self._reasoning_open:
            sys.stderr.write(self._reset + "\n\n")
            sys.stderr.flush()
            self._reasoning_open = False

    def _finish_text(self, *, intermediate: bool) -> None:
        if not self._text:
            return
        content = "".join(self._text)
        self._text.clear()
        if self.live:
            if not content.endswith("\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
            return
        target = sys.stderr if intermediate else sys.stdout
        tail = "" if content.endswith("\n") else "\n"
        target.write(content + tail)
        target.flush()


async def run_once(
    loop: AgentLoop, prompt: str, *, show_reasoning: bool = False
) -> int:
    """跑一个回合并按终端约定呈现。loop 由调用方装配（cli._build_agent）。"""
    presenter = _Presenter(show_reasoning=show_reasoning)
    usage_seen = False
    in_tokens = out_tokens = hit_tokens = 0
    stop_reason: str | None = None
    hit_cap = False
    calls_made = 0
    try:
        async for event in loop.run_turn(prompt):
            if isinstance(event, TextDelta):
                presenter.on_text(event.text)
            elif isinstance(event, ReasoningDelta):
                presenter.on_reasoning(event.text)
            elif isinstance(event, UsageEvent):
                usage_seen = True
                in_tokens += event.usage.input_tokens
                out_tokens += event.usage.output_tokens
                hit_tokens += event.usage.cache_hit_tokens
            elif isinstance(event, ToolRequested):
                presenter.on_tool_requested(event)
            elif isinstance(event, ToolFinished):
                presenter.on_tool_finished(event)
            elif isinstance(event, TurnEnded):
                presenter.on_turn_ended()
                stop_reason = event.stop_reason
                hit_cap = event.hit_iteration_cap
                calls_made = event.calls_made
    finally:
        presenter.close()  # 失败/中断路径：思考块与残留文本也要收尾

    if hit_cap:
        sys.stderr.write(
            f"[codelotte] 警告：已达迭代上限 {MAX_ITERATIONS} 轮，回合强制结束\n"
        )
    elif stop_reason is None:
        sys.stderr.write(
            "[codelotte] 警告：响应未正常结束（无 stop 标记），回答可能不完整\n"
        )
    elif stop_reason == "length":
        sys.stderr.write(
            "[codelotte] 警告：输出被 max_tokens 截断（finish_reason=length）\n"
        )
    total_in = in_tokens if usage_seen else "?"
    total_out = out_tokens if usage_seen else "?"
    total_hit = hit_tokens if usage_seen else "?"
    sys.stderr.write(
        f"\n[codelotte] tokens in={total_in} out={total_out} cache_hit={total_hit}"
        f" calls={calls_made} | session: {loop.session_path}\n\n"
    )
    sys.stderr.flush()
    return 1 if hit_cap else 0
