"""Agent 循环（SPEC §A）：组请求 → 流式 → 执行工具 → 回填 → 直到模型不再请求工具。

不变量：**记录是事实源**——凡广播出去的"事实"（工具调用/结果、assistant 回复、用量）
都先落盘再广播；流式增量文本是呈现侧事件（随到随发），它在流结束时由 assistant 记录
一次性落盘，失败或被中断（Ctrl+C）时已看到的部分同样落盘（stopReason=interrupted）——
无论从哪条路径离开回合，界面看到的都有记录兜底，不出现"终端看到了、会话里没有"的悬空状态。

对外只有一条结构化事件流：文本/思考增量沿用 Provider 层事件；用量在流结束时计价、
随 usage 记录落盘后以 CostRecorded 广播（计价是应用层事实，不放进 Provider 抽象）；
工具调用与回合边界是本层事件。TUI、无头模式（-p）与后续的导出/评测都消费它——
同一套事件、不同呈现，这是「界面所见」与「无头行为」一致的保证（SPEC §A）。

deepseek 雷区：带 tools 的请求必须把历史 assistant 的 reasoning_content 原样回传，
否则 400（docs/tech/deepseek-api.md §4）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from codelotte.cost import CallRecord, Catalog, price_call
from codelotte.providers.base import (
    ProviderError,
    ProviderEvent,
    ReasoningDelta,
    StreamEnd,
    StreamUsage,
    TextDelta,
    ToolCall,
    ToolCallsEvent,
    UsageEvent,
    assistant_message,
)
from codelotte.session.context import INTERRUPTED_TOOL_NOTE
from codelotte.session.store import SessionStore
from codelotte.tools import Tool, ToolResult, execute_tool, wire_tools

MAX_ITERATIONS = 50  # 迭代硬上限兜底（死循环三层防御是票据 11）


class StreamingClient(Protocol):
    """模型通信接口（Provider 缝的调用侧）：测试注入的脚本化假客户端也实现它。"""

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = ...,
    ) -> AsyncIterator[ProviderEvent]: ...


@dataclass(frozen=True)
class ToolRequested:
    """模型请求的一次工具调用（调用记录已先落盘）。parse_error 非空=参数畸形、不会执行。"""

    call_id: str
    name: str
    arguments: str  # 原始 JSON 文本；参数畸形时即模型的原始输出
    parse_error: str | None = None


@dataclass(frozen=True)
class ToolFinished:
    """一次工具执行结束（结果已先落盘）。"""

    call_id: str
    name: str
    ok: bool
    content: str
    duration_ms: int


@dataclass(frozen=True)
class TurnEnded:
    """一个回合结束。stop_reason 是最后一次模型调用的结束原因。"""

    stop_reason: str | None
    hit_iteration_cap: bool
    calls_made: int


@dataclass(frozen=True)
class CostRecorded:
    """一次模型调用的账单（时段判定与估价已随 usage 记录先落盘，票据 07）。"""

    record: CallRecord


LoopEvent = (
    TextDelta | ReasoningDelta | CostRecorded | ToolRequested | ToolFinished | TurnEnded
)


def _request_fingerprint(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> str:
    """请求指纹（sha256 前 16 位十六进制，SPEC §I）：同一状态两次运行指纹一致、
    历史一变就变——跨运行比对可排查缓存失效（跟 usage 一起落盘）。"""
    payload = json.dumps(
        {"messages": messages, "tools": tools},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Turn:
    """一轮模型回复的收集结果（失败时 failure 非空，其余字段为已收集到的部分）。"""

    content: str = ""
    reasoning: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: StreamUsage | None = None
    stop_reason: str | None = None
    failure: ProviderError | None = None


def _assistant_fields(turn: _Turn, model: str, *, interrupted: bool) -> dict[str, Any]:
    """一轮回复的会话记录字段。toolCalls 存原始参数 JSON 文本（回放时逐字节重建请求）。"""
    fields: dict[str, Any] = {
        "role": "assistant",
        "content": turn.content,
        "model": model,
        "stopReason": "interrupted" if interrupted else turn.stop_reason,
    }
    if turn.reasoning:
        fields["reasoningContent"] = turn.reasoning
    if turn.tool_calls:
        fields["toolCalls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in turn.tool_calls
        ]
    return fields


def _assistant_message(turn: _Turn) -> dict[str, Any]:
    """一轮回复转成协议消息（形状在 providers.base.assistant_message，与恢复路径共用）。

    reasoning_content 必须原样回传：带 tools 的请求缺它会 400（deepseek 雷区）。
    """
    return assistant_message(
        content=turn.content,
        reasoning=turn.reasoning or None,
        tool_calls=[(call.id, call.name, call.arguments) for call in turn.tool_calls]
        or None,
    )


class AgentLoop:
    """一次会话的循环与状态：消息数组与会话文件随对象走，跨回合累积（TUI 多轮对话）。"""

    def __init__(
        self,
        *,
        client: StreamingClient,
        tools: tuple[Tool, ...],
        store: SessionStore,
        model: str,
        catalog: Catalog,
        env: str = "local",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        self._client = client
        self._tools = tools
        self._store = store
        self._model = model
        self._env = env
        self._catalog = catalog
        self._tool_schemas = wire_tools(tools)
        self.messages: list[dict[str, Any]] = (
            list(messages) if messages is not None else []
        )

    @property
    def session_path(self) -> Path:
        return self._store.path

    @property
    def leaf_id(self) -> str | None:
        """当前活动分支的叶子记录 id（消费方按它取分支记录，如 TUI 的历史回放）。"""
        return self._store.leaf_id

    @property
    def catalog(self) -> Catalog:
        """本次运行的模型目录（账单/展示按它折算）。"""
        return self._catalog

    async def run_turn(self, prompt: str) -> AsyncIterator[LoopEvent]:
        """跑一个完整回合并广播事件。工具失败不中断（错误文本回传模型自纠）。

        ProviderError 在把已收集的部分落盘后向上抛，由消费方决定怎么呈现与退出码。
        """
        self._store.append("message", role="user", content=prompt)
        self.messages.append({"role": "user", "content": prompt})

        calls_made = 0
        stop_reason: str | None = None
        for _ in range(MAX_ITERATIONS):
            calls_made += 1
            turn = _Turn()
            async for event in self._consume_stream(turn):
                yield event
            if turn.failure is not None:
                raise turn.failure
            stop_reason = turn.stop_reason
            if not turn.tool_calls:
                # 答案也要进上下文（审查修正：原来只有带工具调用的 assistant 进 messages，
                # 同进程下一轮请求会缺上一条回答，与 --continue 重建的请求不一致——
                # 缓存前缀与请求指纹都会因此错位）。
                self.messages.append(_assistant_message(turn))
                yield TurnEnded(
                    stop_reason=stop_reason,
                    hit_iteration_cap=False,
                    calls_made=calls_made,
                )
                return
            self.messages.append(_assistant_message(turn))
            for call in turn.tool_calls:
                async for call_event in self._run_call(call):
                    yield call_event
        else:
            self._store.append(
                "event", kind="iterationLimit", iterations=MAX_ITERATIONS
            )
            yield TurnEnded(
                stop_reason=stop_reason, hit_iteration_cap=True, calls_made=calls_made
            )

    async def _consume_stream(self, turn: _Turn) -> AsyncIterator[LoopEvent]:
        """请求模型一次：边收边广播增量事件，收完落盘（turn 由调用方持有，回填收集结果）。

        增量（文本/思考/用量）是呈现用事件，随到随发；assistant 记录在流结束时一次性落盘
        （流式中途失败或被取消时，已看到的部分也落盘后再向上抛——记录是事实源）。
        """
        fingerprint = _request_fingerprint(self.messages, self._tool_schemas)
        parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            async for event in self._client.stream_chat(
                self.messages, tools=self._tool_schemas
            ):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield event
                elif isinstance(event, ReasoningDelta):
                    reasoning_parts.append(event.text)
                    yield event
                elif isinstance(event, ToolCallsEvent):
                    turn.tool_calls = event.calls
                elif isinstance(event, UsageEvent):
                    turn.usage = (
                        event.usage
                    )  # 收下备用；对外的用量事件是计价后的 CostRecorded
                elif isinstance(event, StreamEnd):
                    turn.stop_reason = event.reason
        except ProviderError as exc:
            turn.failure = exc
        except asyncio.CancelledError:
            # 中断（Ctrl+C）：已经看到的文本也要落盘，再放行取消让执行器清理子进程
            turn.content = "".join(parts)
            turn.reasoning = "".join(reasoning_parts)
            if turn.content or turn.reasoning or turn.tool_calls:
                self._store.append(
                    "message", **_assistant_fields(turn, self._model, interrupted=True)
                )
            if turn.usage is not None:
                # 用量已经收到 = 这次调用已经在计费了：取消也不能丢账（审查修正）
                self._record_usage(turn.usage, fingerprint)
            raise
        turn.content = "".join(parts)
        turn.reasoning = "".join(reasoning_parts)
        self._store.append(
            "message",
            **_assistant_fields(
                turn, self._model, interrupted=turn.failure is not None
            ),
        )
        if turn.usage is not None:
            yield self._record_usage(turn.usage, fingerprint)

    def _record_usage(self, usage: StreamUsage, fingerprint: str) -> CostRecorded:
        """计价 + 落盘 usage 记录（SPEC §I「每次模型调用记录一条 usage」），返回广播用事件。"""
        priced = price_call(
            self._catalog, self._model, usage, at=datetime.now(timezone.utc)
        )
        self._store.append(
            "usage",
            model=self._model,
            inputTokens=usage.input_tokens,
            outputTokens=usage.output_tokens,
            cacheHitTokens=usage.cache_hit_tokens,
            cacheMissTokens=usage.cache_miss_tokens,
            period=priced.period,  # 时段档（票据 07，SPEC §I）
            cost=priced.cost,  # 按当时价目表的估算（目录里没有这个模型时 None）
            currency=self._catalog.currency,  # 记录自描述：金额的货币随记录走（价格会变）
            requestFingerprint=fingerprint,  # 排查缓存失效用
        )
        return CostRecorded(
            record=CallRecord(
                model=self._model,
                period=priced.period,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_hit_tokens=priced.cache_hit_tokens,  # 计价口径（未拆缓存时补差额）
                cache_miss_tokens=priced.cache_miss_tokens,
                cost=priced.cost,
            )
        )

    async def _run_call(self, call: ToolCall) -> AsyncIterator[LoopEvent]:
        """一次工具调用：记录 → 占位应答 →（广播）→ 执行 → 原地回填 → 结果记录 →（广播）。

        参数畸形（模型输出缺陷）不执行：错误作为工具结果回传让它自纠（SPEC §D）。
        占位应答先于一切挂起点落进 messages：回合在任何时刻被取消（如工具执行中 Ctrl+C），
        assistant 声明的每个 tool_call 仍各有一条 tool 应答——缺一个，下一次请求整个 400。
        """
        arguments: dict[str, Any] | None = None
        if call.parse_error is not None:
            self._store.append(
                "tool_call",
                toolCallId=call.id,
                name=call.name,
                arguments=call.arguments,  # 无法解析时记原始文本，parseError 说明原因
                parseError=call.parse_error,
                env=self._env,
            )
        else:
            arguments = json.loads(call.arguments)  # 装配器已校验：合法 JSON 对象
            self._store.append(
                "tool_call",
                toolCallId=call.id,
                name=call.name,
                arguments=arguments,
                env=self._env,
            )

        reply: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": call.id,
            "content": INTERRUPTED_TOOL_NOTE,
        }
        self.messages.append(reply)
        yield ToolRequested(
            call_id=call.id,
            name=call.name,
            arguments=call.arguments,
            parse_error=call.parse_error,
        )

        if arguments is None:
            result = ToolResult(
                content=f"错误：工具 {call.name} 的{call.parse_error}",
                ok=False,
                duration_ms=0,
            )
        else:
            result = await execute_tool(call.name, arguments, tools=self._tools)
        reply["content"] = result.content  # 原地回填（同一条消息，取消也不会缺项）
        self._store.append(
            "tool_result",
            toolCallId=call.id,
            name=call.name,  # 自我描述：导出/归因按行读会话时不必回查 tool_call
            ok=result.ok,
            content=result.content,
            durationMs=result.duration_ms,
            env=self._env,
        )
        yield ToolFinished(
            call_id=call.id,
            name=call.name,
            ok=result.ok,
            content=result.content,
            duration_ms=result.duration_ms,
        )
