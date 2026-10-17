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

from codelotte.compaction import (
    COMPACTION_CONSTRAINTS,
    CompactionLimits,
    CompactionMode,
    build_compaction_messages,
    build_summary_messages,
    context_tokens_from_entries,
    estimate_tokens,
    plan_compaction,
)
from codelotte.cost import CallRecord, Catalog, price_call
from codelotte.guardrails import (
    EVENT_GUARDRAIL,
    GUARD_CIRCUIT,
    GUARD_REINJECT,
    LAYER_PLANNING,
    LAYER_REASONING,
    LAYER_TOOL,
    STOP_CIRCUIT,
    STOP_PLANNING,
    GuardrailLimits,
    GuardrailTracker,
    circuit_reminder,
    planning_reminder,
    planning_terminate_message,
)
from codelotte.permissions import (
    ALLOW,
    ASK,
    DENY,
    DECISION_ALWAYS,
    DECISION_DENY,
    DECISION_ONCE,
    DECISION_SESSION,
    Approver,
    PermissionLayer,
    PermissionRequest,
)
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
from codelotte.session.context import INTERRUPTED_TOOL_NOTE, messages_from_entries
from codelotte.session.store import SessionStore, load_branch
from codelotte.tools import Tool, ToolResult, execute_tool, find_tool, wire_tools

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
    """一个 run（用户回合）结束。stop_reason 是最后一次模型调用的结束原因。

    guardrail_stop 非空表示这个 run 被死循环防御终止（"circuitBreaker" / "planning"），
    消费方据此给出明确原因（票据 11）。
    """

    stop_reason: str | None
    hit_iteration_cap: bool
    calls_made: int
    guardrail_stop: str | None = None


@dataclass(frozen=True)
class GuardrailTriggered:
    """死循环防御的一次拦截/熔断/终止（事件记录已先落盘，票据 11）。

    layer：tool（重复/无进展）/ reasoning（连续失败熔断）/ planning（重注入或温和终止）。
    """

    layer: str
    guard: str
    message: str


@dataclass(frozen=True)
class CompactionEvent:
    """一次上下文压缩（compaction 记录已先落盘，票据 12）。

    utilization 是触发时的 usage / 用户级生效窗口；after_tokens 是压缩后上下文的本地估算
    （字符/4）。warning 非空表示最小保留集仍高于目标（窗口配置偏小），不假装达标。
    """

    mode: CompactionMode
    utilization: float
    window: int
    before_tokens: int
    after_tokens: int
    summary: str
    first_kept_entry_id: str
    warning: str | None = None


@dataclass(frozen=True)
class CostRecorded:
    """一次模型调用的账单（时段判定与估价已随 usage 记录先落盘，票据 07）。"""

    record: CallRecord


LoopEvent = (
    TextDelta
    | ReasoningDelta
    | CostRecorded
    | ToolRequested
    | ToolFinished
    | GuardrailTriggered
    | CompactionEvent
    | TurnEnded
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


@dataclass(frozen=True)
class _Authorization:
    """一次工具调用的权限结论（reason 进审计记录，拒绝时也回传模型）。"""

    allowed: bool
    reason: str


@dataclass
class _Turn:
    """一个 turn（一次模型回复）的收集结果（失败时 failure 非空，其余字段为已收集到的部分）。"""

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
        permissions: PermissionLayer,
        env: str = "local",  # 未知工具的兜底；已知工具按自己的 exec_env 标记（见 _tool_env）
        messages: list[dict[str, Any]] | None = None,
        approver: Approver | None = None,
        guardrail_limits: GuardrailLimits | None = None,
        compaction_limits: CompactionLimits | None = None,
        context_window: int | None = None,
    ) -> None:
        self._client = client
        self._tools = tools
        self._store = store
        self._model = model
        self._env = env
        self._catalog = catalog
        self._permissions = permissions
        # 死循环三层防御（票据 11）：阈值可配，计数按回合重置
        self._guardrail_limits = (
            guardrail_limits if guardrail_limits is not None else GuardrailLimits()
        )
        self._guardrails = GuardrailTracker(self._guardrail_limits)
        self._turn_goal = ""
        # 压缩双阈值（票据 12）：settings.json 可配，默认 0.60 / 0.85
        self._compaction_limits = (
            compaction_limits if compaction_limits is not None else CompactionLimits()
        )
        # 压缩（票据 12）：分母是用户级生效窗口（与 TUI 状态栏同源，cli 传入）；
        # 分子优先用恢复会话里的最后一次 usage/压缩估算，否则从 0 开始。
        self._context_window = context_window
        self._last_input_tokens = (
            context_tokens_from_entries(load_branch(store.path, store.leaf_id))
            if context_window is not None
            else 0
        )
        # 审批者只在有交互面时注入（TUI）；无头上为 None——ask 一律 fail-closed（SPEC §G）
        self.approver = approver
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

    @property
    def model(self) -> str:
        """本次运行使用的模型 id（展示层用）。"""
        return self._model

    @property
    def permissions(self) -> PermissionLayer:
        """本次运行的权限层（notices 供展示层提示，票据 09）。"""
        return self._permissions

    @property
    def guardrail_limits(self) -> GuardrailLimits:
        """本次运行的死循环防御阈值（配置透传结果，票据 11）。"""
        return self._guardrail_limits

    @property
    def context_window(self) -> int | None:
        """本次运行的上下文窗口（用户级生效值；压缩与状态栏同源，票据 12）。"""
        return self._context_window

    @property
    def compaction_limits(self) -> CompactionLimits:
        """本次运行的压缩双阈值（settings.json 透传结果，票据 12）。"""
        return self._compaction_limits

    async def run_turn(self, prompt: str) -> AsyncIterator[LoopEvent]:
        """跑一个 run（用户回合）并广播事件：用户一句话 → 多次模型 turn → 最终回答。

        一个 run 可以包含很多 turn（每次模型回复 + 工具链）；工具失败不中断
        （错误文本回传模型自纠）。ProviderError 在把已收集的部分落盘后向上抛，
        由消费方决定怎么呈现与退出码。
        """
        self._store.append("message", role="user", content=prompt)
        self.messages.append({"role": "user", "content": prompt})
        # 死循环防御按回合计数：上一回合的重复/失败不牵连新任务（票据 11）
        self._turn_goal = prompt
        self._guardrails.reset()

        calls_made = 0
        stop_reason: str | None = None
        for _ in range(MAX_ITERATIONS):
            # 装配下一次请求之前判压缩（票据 12）：软触发等边界、硬触发不等
            async for event in self._maybe_compact():
                if isinstance(event, CompactionEvent):
                    calls_made += 1  # 摘要本身也是一次真实模型调用
                yield event
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
            self._guardrails.begin_batch()
            for call in turn.tool_calls:
                async for call_event in self._run_call(call):
                    yield call_event

            # 批结束统一结算：连续失败 → 熔断（禁工具请模型总结）；否则规划层处理拦截。
            # 放在整批之后是为了不打断协议：每个 tool_call 都已有对应的 tool 应答。
            if self._guardrails.should_break():
                async for event in self._circuit_break(calls_made):
                    yield event
                return
            action = self._guardrails.planning_after_batch()
            if action is not None:
                if action.kind == GUARD_REINJECT:
                    reminder = planning_reminder(self._turn_goal, action.detail)
                    message = f"工具层拦截重复操作：{action.detail}"
                    event = self._record_guardrail(
                        layer=LAYER_PLANNING,
                        guard=action.kind,
                        message=message,
                        blocks=action.blocks,
                        threshold=action.threshold,
                        injected=reminder,
                    )
                    self.messages.append({"role": "user", "content": reminder})
                    yield event
                else:
                    message = planning_terminate_message(
                        action.blocks, action.threshold, action.detail
                    )
                    yield self._record_guardrail(
                        layer=LAYER_PLANNING,
                        guard=action.kind,
                        message=message,
                        blocks=action.blocks,
                        threshold=action.threshold,
                    )
                    yield TurnEnded(
                        stop_reason=stop_reason,
                        hit_iteration_cap=False,
                        calls_made=calls_made,
                        guardrail_stop=STOP_PLANNING,
                    )
                    return
        else:
            self._store.append(
                "event", kind="iterationLimit", iterations=MAX_ITERATIONS
            )
            yield TurnEnded(
                stop_reason=stop_reason, hit_iteration_cap=True, calls_made=calls_made
            )

    async def _maybe_compact(self) -> AsyncIterator[LoopEvent]:
        """装配下一次请求前判压缩（票据 12）：可能先做一次无工具的摘要调用。

        摘要调用的 usage 照常计价落盘，但不落 assistant 消息（它是元操作，不是对话）；
        compaction entry 记录摘要、保留边界与独立重注入的硬约束。压缩后 live messages
        从记录重装配，与 --continue 的装配逐条一致。
        """
        if self._context_window is None:
            return
        entries = load_branch(self._store.path, self._store.leaf_id)
        decision = plan_compaction(
            entries,
            input_tokens=self._last_input_tokens,
            context_window=self._context_window,
        )
        if decision is None:
            return
        prefix_messages = messages_from_entries(entries[: decision.cut_index])
        if not prefix_messages:
            return

        before_tokens = self._last_input_tokens
        summary_turn = _Turn()
        cost_events: list[CostRecorded] = []
        async for event in self._consume_stream(
            summary_turn,
            use_tools=False,
            messages=build_summary_messages(prefix_messages),
            record_message=False,
        ):
            if isinstance(event, CostRecorded):
                cost_events.append(event)
        if summary_turn.failure is not None:
            raise summary_turn.failure
        summary = summary_turn.content.strip()
        if not summary:
            raise ProviderError("压缩摘要为空：模型没有返回摘要内容")

        kept_messages = messages_from_entries(entries[decision.cut_index :])
        compacted = build_compaction_messages(
            summary, COMPACTION_CONSTRAINTS, kept_messages
        )
        after_tokens = estimate_tokens(compacted)
        warning = self._compaction_warning(decision.mode, after_tokens)
        self._store.append(
            "compaction",
            summary=summary,
            firstKeptEntryId=decision.first_kept_entry_id,
            constraints=COMPACTION_CONSTRAINTS,  # 独立于摘要，恢复时原样重注入
            mode=decision.mode,
            # 不落百分比（票据 12 预置决策：百分比每回合现算）；展示由 beforeTokens/window 现算
            window=self._context_window,
            beforeTokens=before_tokens,
            estimatedAfterTokens=after_tokens,
            summaryModel=self._model,
            warning=warning,
        )
        self.messages = messages_from_entries(
            load_branch(self._store.path, self._store.leaf_id)
        )
        # 下一次请求前不能再用旧的高 usage 反复压缩；下一次真实请求的 usage 会覆盖它
        self._last_input_tokens = after_tokens
        for cost in cost_events:
            yield cost
        yield CompactionEvent(
            mode=decision.mode,
            utilization=decision.utilization,
            window=self._context_window,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            summary=summary,
            first_kept_entry_id=decision.first_kept_entry_id,
            warning=warning,
        )

    def _compaction_warning(self, mode: str, after_tokens: int) -> str | None:
        """最小保留集仍高于目标时明确提示（不无限压、不假装达标）。"""
        if self._context_window is None or self._context_window <= 0:
            return None
        share = after_tokens / self._context_window
        if share >= 1.0:
            return (
                f"窗口配置小于最小保留集：已压到 {after_tokens} tokens（预计占 "
                f"{share:.0%}）；原始记录仍可查，建议调大 contextWindow 或缩短任务"
            )
        if mode == "hard" and share >= self._compaction_limits.soft:
            return (
                f"已压到最小保留集，预计仍占 {share:.0%}"
                f"（未达到 {self._compaction_limits.soft:.0%} 目标）；原始记录仍可查"
            )
        return None

    async def _circuit_break(self, calls_made: int) -> AsyncIterator[LoopEvent]:
        """推理层熔断：记录事件 → 重注入总结要求 → 禁用工具再请求一次 → 结束回合。

        熔断不是异常：模型有一次机会在无工具条件下总结现状，总结照常落盘；
        回合结束原因写进 TurnEnded.guardrail_stop，会话可继续（票据 11 验收）。
        """
        failures = self._guardrails.failure_streak
        reminder = circuit_reminder(self._turn_goal, failures)
        message = (
            f"连续 {failures} 次工具调用失败，熔断当前回合"
            "（工具已禁用，请模型总结现状）"
        )
        event = self._record_guardrail(
            layer=LAYER_REASONING,
            guard=GUARD_CIRCUIT,
            message=message,
            count=failures,
            threshold=self.guardrail_limits.failure,
            injected=reminder,
        )
        self.messages.append({"role": "user", "content": reminder})
        yield event

        summary = _Turn()
        async for stream_event in self._consume_stream(summary, use_tools=False):
            yield stream_event
        if summary.failure is not None:
            raise summary.failure
        self.messages.append(_assistant_message(summary))
        yield TurnEnded(
            stop_reason=summary.stop_reason,
            hit_iteration_cap=False,
            calls_made=calls_made + 1,
            guardrail_stop=STOP_CIRCUIT,
        )

    def _record_guardrail(
        self, *, layer: str, guard: str, message: str, **fields: Any
    ) -> GuardrailTriggered:
        """落一条 guardrail 事件并返回广播用事件：记录先于呈现，字段形状只定义一次。"""
        self._store.append(
            "event",
            kind=EVENT_GUARDRAIL,
            layer=layer,
            guard=guard,
            message=message,
            **fields,
        )
        return GuardrailTriggered(layer=layer, guard=guard, message=message)

    async def _consume_stream(
        self,
        turn: _Turn,
        *,
        use_tools: bool = True,
        messages: list[dict[str, Any]] | None = None,
        record_message: bool = True,
    ) -> AsyncIterator[LoopEvent]:
        """请求模型一次：边收边广播增量事件，收完落盘（turn 由调用方持有，回填收集结果）。

        增量（文本/思考/用量）是呈现用事件，随到随发；assistant 记录在流结束时一次性落盘
        （流式中途失败或被取消时，已看到的部分也落盘后再向上抛——记录是事实源）。
        use_tools=False 用于熔断/压缩的总结调用：请求不带工具定义，指纹也按无工具算。
        record_message=False 用于压缩摘要：usage 照记，但不把元操作写成 assistant 对话。
        messages 给出时用它代替 self.messages（摘要请求的输入是历史前缀，不是当前上下文）。
        """
        request_messages = self.messages if messages is None else messages
        tool_schemas = self._tool_schemas if use_tools else None
        fingerprint = _request_fingerprint(request_messages, tool_schemas or [])
        parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            async for event in self._client.stream_chat(
                request_messages, tools=tool_schemas
            ):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                    yield event
                elif isinstance(event, ReasoningDelta):
                    reasoning_parts.append(event.text)
                    yield event
                elif isinstance(event, ToolCallsEvent):
                    if use_tools:
                        turn.tool_calls = event.calls
                    # use_tools=False（熔断总结）：即使端点硬塞回 tool_calls 也丢弃——
                    # 没有工具应答的 assistant toolCalls 会让恢复后的请求非法（票据 11）
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
            if record_message and (turn.content or turn.reasoning or turn.tool_calls):
                self._store.append(
                    "message", **_assistant_fields(turn, self._model, interrupted=True)
                )
            if turn.usage is not None:
                # 用量已经收到 = 这次调用已经在计费了：取消也不能丢账（审查修正）
                self._record_usage(turn.usage, fingerprint)
            raise
        turn.content = "".join(parts)
        turn.reasoning = "".join(reasoning_parts)
        if record_message:
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
        self._last_input_tokens = usage.input_tokens  # 下一次压缩判定的分子（实际 usage）
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
        block = None
        if call.parse_error is not None:
            self._guardrails.record_malformed()  # 参数畸形也算一次连续失败（票据 11）
            self._store.append(
                "tool_call",
                toolCallId=call.id,
                name=call.name,
                arguments=call.arguments,  # 无法解析时记原始文本，parseError 说明原因
                parseError=call.parse_error,
                env=self._tool_env(call.name),
            )
        else:
            parsed: dict[str, Any] = json.loads(call.arguments)  # 装配器已校验：合法 JSON 对象
            arguments = parsed
            self._store.append(
                "tool_call",
                toolCallId=call.id,
                name=call.name,
                arguments=arguments,
                env=self._tool_env(call.name),
            )
            block = self._guardrails.check_call(call.name, parsed)

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
        elif block is not None:
            # 工具层拦截：不执行、不经过权限层；拦截说明作为工具结果回传模型
            result = ToolResult(content=block.message, ok=False, duration_ms=0)
        else:
            authorization = await self._authorize(call, arguments)
            if authorization.allowed:
                result = await execute_tool(call.name, arguments, tools=self._tools)
            else:
                # 拒绝不是异常：原因回传模型让它换做法（SPEC §D），同时已落 permission 记录（§G）
                result = ToolResult(
                    content=(
                        f"错误：权限层未放行这次调用（{authorization.reason}）。"
                        "请换一种被允许的做法；如需放宽，请用户调整权限规则"
                        "（--allow / ~/.codelotte/permissions.json）。"
                    ),
                    ok=False,
                    duration_ms=0,
                )
        if arguments is not None and block is None:
            # 真正执行后的结果计入连续失败/无进展；工具层拦截不由推理层重复计数
            self._guardrails.record_result(
                call.name, arguments, result.content, ok=result.ok
            )
        block_event: GuardrailTriggered | None = None
        if block is not None:
            # 拦截事件先于工具结果落盘（记录是事实源，票据 11）
            block_event = self._record_guardrail(
                layer=LAYER_TOOL,
                guard=block.guard,
                message=block.message,
                count=block.count,
                threshold=block.threshold,
                detail=block.detail,
                tool=call.name,
                toolCallId=call.id,
            )
        reply["content"] = result.content  # 原地回填（同一条消息，取消也不会缺项）
        self._store.append(
            "tool_result",
            toolCallId=call.id,
            name=call.name,  # 自我描述：导出/归因按行读会话时不必回查 tool_call
            ok=result.ok,
            content=result.content,
            durationMs=result.duration_ms,
            env=self._tool_env(call.name),
        )
        yield ToolFinished(
            call_id=call.id,
            name=call.name,
            ok=result.ok,
            content=result.content,
            duration_ms=result.duration_ms,
        )
        if block_event is not None:
            yield block_event

    def _tool_env(self, name: str) -> str:
        """一次工具调用的执行环境（审计字段）：按工具实现如实标记（bash 随执行器，
        文件工具在宿主上跑）；未知工具尚未执行，退回会话默认值。"""
        tool = find_tool(name, self._tools)
        return tool.exec_env if tool is not None else self._env

    async def _authorize(self, call: ToolCall, arguments: dict[str, Any]) -> _Authorization:
        """权限判定 →（ask 时）审批 → 落 permission 记录（审计，SPEC §G）。

        记录先于执行：判定与决策先写进会话，再决定放行/拒绝——记录是事实源。
        """
        check = self._permissions.evaluate(call.name, arguments)
        decision: str | None = None
        if check.verdict == ALLOW:
            reason = f"规则放行（{check.rule.text}）" if check.rule else "放行"
        elif check.verdict == DENY:
            reason = f"被规则拒绝（{check.rule.text}）" if check.rule else "被规则拒绝"
        elif self.approver is None:
            decision = DECISION_DENY  # 无头模式：ask 一律 fail-closed（SPEC §G）
            reason = "无头模式未授权（fail-closed）；用 --allow 或规则文件授权"
        else:
            request = PermissionRequest(
                tool=call.name,
                subject=check.subject,
                arguments=arguments,
                rule=check.rule,
            )
            try:
                decision = await self.approver(request)
            except asyncio.CancelledError:
                # 审批中被取消（Ctrl+C）：判定已发生就要留痕（审查修正：审计断链）
                self._store.append(
                    "permission",
                    toolCallId=call.id,
                    tool=call.name,
                    subject=check.subject,
                    verdict=check.verdict,
                    rule=check.rule.text if check.rule is not None else None,
                    source=check.rule.source if check.rule is not None else None,
                    decision=None,
                    allowed=False,
                    reason="审批未完成（回合被取消）",
                )
                raise
            self._permissions.apply_decision(call.name, arguments, decision)
            reason = {
                DECISION_ONCE: "用户审批：本次允许",
                DECISION_SESSION: "用户审批：本会话允许",
                DECISION_ALWAYS: "用户审批：始终允许（已写入用户级规则）",
            }.get(decision, "用户在审批中拒绝")
        allowed = check.verdict == ALLOW or (
            check.verdict == ASK and decision in (DECISION_ONCE, DECISION_SESSION, DECISION_ALWAYS)
        )
        self._store.append(
            "permission",
            toolCallId=call.id,
            tool=call.name,
            subject=check.subject,
            verdict=check.verdict,
            rule=check.rule.text if check.rule is not None else None,
            source=check.rule.source if check.rule is not None else None,
            decision=decision,
            allowed=allowed,
            reason=reason,  # 一句话说明（审计/导出直接可读，与回传模型的错误文本同源）
        )
        return _Authorization(allowed=allowed, reason=reason)
