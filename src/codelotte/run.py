"""无头单次执行（-p 模式）：消费 AgentLoop 的事件流，按终端约定呈现（票据 02 起冻结的行为）。

终端约定：真终端（stdout 是 tty）里模型文本实时流式输出（人要看进度）；管道/重定向时
不实时写，轮末才决定去向——**终轮的文本（答案）进 stdout，中间轮次的过渡叙述进 stderr**，
管道拿到的是纯净答案。思考过程（reasoning_content）、工具活动、用量总结与分项账单
（票据 07：按模型/时段/缓存三类）始终走 stderr；账单是**会话累计**口径（从记录读，
与 TUI 状态栏同源），失败/中断路径也照打——钱花了就得报账。
工具失败不是异常：错误文本作为工具结果回传模型自纠，循环继续（SPEC §D）。

除了"怎么呈现"，这里不做任何业务逻辑——落盘、工具执行、循环控制都在 loop.py；
计价是 loop 落盘时算好的（usage 记录里的 period/cost），这里只累计与渲染。
"""

from __future__ import annotations

import json
import sys

from codelotte.cost import Ledger, call_record_from_entry
from codelotte.display import compaction_after_share, compaction_title, guardrail_notice
from codelotte.guardrails import STOP_CIRCUIT, STOP_PLANNING
from codelotte.loop import (
    MAX_ITERATIONS,
    AgentLoop,
    CompactionEvent,
    CostRecorded,
    GuardrailTriggered,
    ToolFinished,
    ToolRequested,
    RunEnded,
)
from codelotte.providers.base import ReasoningDelta, TextDelta
from codelotte.session.store import load_branch

__all__ = ["run_once"]

_ANSI_DIM = "\x1b[2m"
_ANSI_RESET = "\x1b[0m"
_PREVIEW_LIMIT = 200  # stderr 上工具参数/错误文本的显示上限


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


class _Presenter:
    """事件流 → 终端输出。行为自票据 02/03 冻结，改动等于改验收，须连带改 e2e 测试。"""

    def __init__(self) -> None:
        self.live = sys.stdout.isatty()
        # 思考事件只在思考开启（reasoning_effort 非 none）时才会出现——来了就展示，没有展示开关；
        # 颜色才看是不是真终端
        dim = _ANSI_DIM if sys.stderr.isatty() else ""
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

    def on_guardrail(self, event: GuardrailTriggered) -> None:
        self._close_reasoning()
        sys.stderr.write(f"[codelotte] {guardrail_notice(event.layer, event.message)}\n")
        sys.stderr.flush()

    def on_compaction(self, event: CompactionEvent) -> None:
        self._close_reasoning()
        after_share = compaction_after_share(event.after_tokens, event.window)
        sys.stderr.write(
            f"[codelotte] {compaction_title(event.mode, event.utilization, after_share)}\n"
        )
        if event.warning:
            sys.stderr.write(f"[codelotte] 警告：{event.warning}\n")
        sys.stderr.flush()

    def on_run_ended(self) -> None:
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


async def run_once(loop: AgentLoop, prompt: str) -> int:
    """跑一个 run 并按终端约定呈现。loop 由调用方装配（cli._build_agent）。"""
    presenter = _Presenter()
    ledger = Ledger()
    stop_reason: str | None = None
    hit_cap = False
    guardrail_stop: str | None = None
    calls_made = 0
    try:
        async for event in loop.run(prompt):
            if isinstance(event, TextDelta):
                presenter.on_text(event.text)
            elif isinstance(event, ReasoningDelta):
                presenter.on_reasoning(event.text)
            elif isinstance(event, CostRecorded):
                ledger.record(event.record)
            elif isinstance(event, ToolRequested):
                presenter.on_tool_requested(event)
            elif isinstance(event, ToolFinished):
                presenter.on_tool_finished(event)
            elif isinstance(event, GuardrailTriggered):
                presenter.on_guardrail(event)
            elif isinstance(event, CompactionEvent):
                presenter.on_compaction(event)
            elif isinstance(event, RunEnded):
                presenter.on_run_ended()
                stop_reason = event.stop_reason
                hit_cap = event.hit_iteration_cap
                guardrail_stop = event.guardrail_stop
                calls_made = event.calls_made
    finally:
        presenter.close()  # 失败/中断路径：思考块与残留文本也要收尾
        _report(
            loop,
            ledger,
            stop_reason=stop_reason,
            hit_cap=hit_cap,
            guardrail_stop=guardrail_stop,
            calls_made=calls_made,
        )  # 账单是事实：失败/中断也照打（审查修正）
    return 1 if (hit_cap or guardrail_stop is not None) else 0


def _report(
    loop: AgentLoop,
    ledger: Ledger,
    *,
    stop_reason: str | None,
    hit_cap: bool,
    guardrail_stop: str | None,
    calls_made: int,
) -> None:
    """收尾汇总：警告 + 本次运行的 token 行 + 会话累计分项账单。"""
    if guardrail_stop == STOP_CIRCUIT:
        sys.stderr.write(
            "[codelotte] 警告：连续工具失败，已熔断本回合（模型已总结现状）\n"
        )
    elif guardrail_stop == STOP_PLANNING:
        sys.stderr.write(
            "[codelotte] 警告：重复操作未纠正，本回合已被规划层温和终止\n"
        )
    elif hit_cap:
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
    total_in = ledger.input_tokens if ledger.calls else "?"
    total_out = ledger.output_tokens if ledger.calls else "?"
    total_hit = ledger.cache_hit_tokens if ledger.calls else "?"
    sys.stderr.write(
        f"\n[codelotte] tokens in={total_in} out={total_out} cache_hit={total_hit}"
        f" calls={calls_made}（本次运行） | session: {loop.session_path}\n"
    )
    print_session_invoice(loop)
    sys.stderr.write("\n")
    sys.stderr.flush()


def print_session_invoice(loop: AgentLoop) -> None:
    """分项账单（会话累计，票据 07 验收）：从记录（活动分支）读，不依赖本次运行的事件。

    文件才是事实源：失败/中断路径也能报账（usage 已落盘），--continue 后覆盖之前各次运行；
    TUI 退出时由 cli 调同一个函数，两种界面同一口径。
    """
    ledger = Ledger()
    for entry in load_branch(loop.session_path, loop.leaf_id):
        if entry.get("type") == "usage":
            ledger.record(call_record_from_entry(entry))
    for line in ledger.invoice(loop.catalog):
        sys.stderr.write(f"[codelotte] {line}\n")
