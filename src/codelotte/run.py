"""无头单次执行（票据 02/03）：Agent 循环——组请求 → 流式 → 执行工具 → 回填 → 直到模型不再请求工具。

不变量：**记录是事实源**——每轮模型回复与每次工具执行（调用/结果/耗时）都先落盘
再呈现；流式中途失败也先落盘（stopReason=interrupted）再向上抛错，绝不出现
"终端看到了、会话里没有"的悬空状态。

终端约定：真终端（stdout 是 tty）里模型文本实时流式输出（人要看进度）；管道/重定向时
不实时写，轮末才决定去向——**终轮的文本（答案）进 stdout，中间轮次的过渡叙述进 stderr**，
管道拿到的是纯净答案。思考过程（reasoning_content）、工具活动与用量总结始终走 stderr。
工具失败不是异常：错误文本作为工具结果回传模型自纠，循环继续（SPEC §D）。

deepseek 雷区：带 tools 的请求必须把历史 assistant 的 reasoning_content 原样回传，
否则 400（docs/tech/deepseek-api.md §4）。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codelotte.config import get_api_key, get_base_url, get_model, get_session_dir
from codelotte.providers.base import (
    ProviderError,
    ReasoningDelta,
    StreamEnd,
    StreamUsage,
    TextDelta,
    ToolCall,
    ToolCallsEvent,
    UsageEvent,
)
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import SessionStore
from codelotte.tools import ToolResult, default_tools, execute_tool, wire_tools
from codelotte.tools.base import Tool

_ANSI_DIM = "\x1b[2m"
_ANSI_RESET = "\x1b[0m"
MAX_ITERATIONS = 50  # 迭代硬上限兜底（死循环三层防御是票据 11）
_PREVIEW_LIMIT = 200  # stderr 上工具参数/错误文本的显示上限


@dataclass
class _Turn:
    """一轮模型回复的收集结果（失败时 failure 非空，其余字段为已收集到的部分）。"""

    content: str = ""
    reasoning: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: StreamUsage | None = None
    stop_reason: str | None = None
    failure: ProviderError | None = None


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


async def _stream_once(
    client: OpenAICompletionsClient,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    show_reasoning: bool,
    live: bool,
) -> _Turn:
    """请求模型一次，收集文本/思考/工具调用/用量。

    失败不抛出而是记入 failure：调用方要先落盘已收集的部分（记录是事实源）。
    live=True（真终端）时文本实时写 stdout；live=False（管道/重定向）只收集，
    由调用方在轮末决定文本去向（终轮进 stdout、中间叙述进 stderr）。
    思考过程默认只落盘不打印；开启后走 stderr（stdout 保持"只有答案"的纯净管道）。
    暗色只用在真实终端上——写进管道/文件时转义序列就是乱码。
    """
    turn = _Turn()
    parts: list[str] = []
    reasoning_parts: list[str] = []
    dim = _ANSI_DIM if (show_reasoning and sys.stderr.isatty()) else ""
    reset = _ANSI_RESET if dim else ""
    reasoning_open = False

    def close_reasoning() -> None:
        """结束 stderr 上的思考块（复位颜色 + 空一行），与后续输出分隔。"""
        nonlocal reasoning_open
        if reasoning_open:
            sys.stderr.write(reset + "\n\n")
            sys.stderr.flush()
            reasoning_open = False

    try:
        async for event in client.stream_chat(messages, tools=tools):
            if reasoning_open and not isinstance(event, ReasoningDelta):
                close_reasoning()  # 思考块与后续输出之间换行分隔
            if isinstance(event, TextDelta):
                parts.append(event.text)
                if live:
                    sys.stdout.write(event.text)
                    sys.stdout.flush()
            elif isinstance(event, ReasoningDelta):
                reasoning_parts.append(event.text)
                if show_reasoning:
                    if not reasoning_open:
                        sys.stderr.write(dim)
                        reasoning_open = True
                    sys.stderr.write(event.text)
                    sys.stderr.flush()
            elif isinstance(event, ToolCallsEvent):
                turn.tool_calls = event.calls
            elif isinstance(event, UsageEvent):
                turn.usage = event.usage
            elif isinstance(event, StreamEnd):
                turn.stop_reason = event.reason
    except ProviderError as exc:
        turn.failure = exc
    close_reasoning()  # 思考中途失败 / 正常结束时也要让 stderr 收尾

    turn.content = "".join(parts)
    turn.reasoning = "".join(reasoning_parts)
    if live and turn.content and not turn.content.endswith("\n"):
        sys.stdout.write("\n")
        sys.stdout.flush()
    return turn


def _assistant_fields(turn: _Turn, model: str) -> dict[str, Any]:
    """一轮回复的会话记录字段。toolCalls 存原始参数 JSON 文本（回放时逐字节重建请求）。"""
    fields: dict[str, Any] = {
        "role": "assistant",
        "content": turn.content,
        "model": model,
        "stopReason": "interrupted" if turn.failure is not None else turn.stop_reason,
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
    """一轮回复转成 OpenAI 兼容协议的 assistant 消息（键序固定，缓存前缀稳定）。

    reasoning_content 必须原样回传：带 tools 的请求缺它会 400（deepseek 雷区）。
    """
    message: dict[str, Any] = {"role": "assistant", "content": turn.content}
    if turn.reasoning:
        message["reasoning_content"] = turn.reasoning
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in turn.tool_calls
        ]
    return message


async def _run_tool_call(
    store: SessionStore,
    call: ToolCall,
    *,
    tools: tuple[Tool, ...],
    env: str,
) -> str:
    """执行一次工具调用：先落盘、再呈现、执行、落盘结果（SPEC §E 事件先落盘再呈现）。

    参数畸形（模型输出缺陷）不执行也不报错：错误作为工具结果回传让它自纠（SPEC §D）。
    env 是执行环境标记（SPEC §E：tool_call/tool_result 记录 sandbox/local，可审计）。
    """
    if call.parse_error is not None:
        store.append(
            "tool_call",
            toolCallId=call.id,
            name=call.name,
            arguments=call.arguments,  # 无法解析时记原始文本，parseError 说明原因
            parseError=call.parse_error,
            env=env,
        )
        sys.stderr.write(f"[codelotte] → {call.name}（参数畸形，未执行）\n")
        sys.stderr.flush()
        result = ToolResult(
            content=f"错误：工具 {call.name} 的{call.parse_error}",
            ok=False,
            duration_ms=0,
        )
    else:
        arguments = json.loads(call.arguments)  # 装配器已校验：合法 JSON 对象
        store.append(
            "tool_call",
            toolCallId=call.id,
            name=call.name,
            arguments=arguments,
            env=env,
        )
        display = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        sys.stderr.write(f"[codelotte] → {call.name}({_preview(display)})\n")
        sys.stderr.flush()
        result = await execute_tool(call.name, arguments, tools=tools)

    store.append(
        "tool_result",
        toolCallId=call.id,
        name=call.name,  # 自我描述：导出/归因按行读会话时不必回查 tool_call 也能知道是哪个工具
        ok=result.ok,
        content=result.content,
        durationMs=result.duration_ms,
        env=env,
    )
    if result.ok:
        size = len(result.content)
        sys.stderr.write(
            f"[codelotte] ← {call.name} {result.duration_ms}ms，结果 {size} 字符\n"
        )
    else:
        sys.stderr.write(
            f"[codelotte] ← {call.name} 失败：{_preview(result.content)}\n"
        )
    sys.stderr.flush()
    return result.content


async def run_once(prompt: str, *, show_reasoning: bool = False) -> int:
    api_key = get_api_key()
    base_url = get_base_url()
    model = get_model()
    session_base = get_session_dir()

    store = SessionStore.start(Path.cwd(), base_dir=session_base)
    store.append("message", role="user", content=prompt)

    client = OpenAICompletionsClient(base_url=base_url, api_key=api_key, model=model)
    executor = LocalExecutor()  # 票据 10：按配置换成 Docker 沙箱实现，工具代码零改动
    toolset = default_tools(executor)
    tool_schemas = wire_tools(toolset)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    calls_made = 0
    usage_seen = False
    in_tokens = out_tokens = hit_tokens = 0
    failure: ProviderError | None = None
    stop_reason: str | None = None
    hit_cap = False

    live = sys.stdout.isatty()  # 真终端实时流式；管道/重定向轮末决定文本去向
    for _ in range(MAX_ITERATIONS):
        turn = await _stream_once(
            client,
            messages,
            tools=tool_schemas,
            show_reasoning=show_reasoning,
            live=live,
        )
        calls_made += 1
        stop_reason = turn.stop_reason
        if turn.usage is not None:
            usage_seen = True
            in_tokens += turn.usage.input_tokens
            out_tokens += turn.usage.output_tokens
            hit_tokens += turn.usage.cache_hit_tokens
        store.append("message", **_assistant_fields(turn, model))
        if turn.usage is not None:
            store.append(
                "usage",
                model=model,
                inputTokens=turn.usage.input_tokens,
                outputTokens=turn.usage.output_tokens,
                cacheHitTokens=turn.usage.cache_hit_tokens,
                cacheMissTokens=turn.usage.cache_miss_tokens,
            )
        if not live and turn.content:
            # 先落盘再呈现；管道/重定向下：终轮文本（答案）进 stdout，中间轮次叙述进 stderr
            target = sys.stderr if turn.tool_calls else sys.stdout
            tail = "" if turn.content.endswith("\n") else "\n"
            target.write(turn.content + tail)
            target.flush()
        if turn.failure is not None:
            failure = turn.failure
            break
        if not turn.tool_calls:
            break  # 一次回复中没有工具调用 = 回合结束
        messages.append(_assistant_message(turn))
        for call in turn.tool_calls:
            content = await _run_tool_call(store, call, tools=toolset, env=executor.env)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": content}
            )
    else:
        hit_cap = True
        store.append("event", kind="iterationLimit", iterations=MAX_ITERATIONS)

    if failure is not None:
        raise failure
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
        f" calls={calls_made} | session: {store.path}\n\n"
    )
    sys.stderr.flush()
    return 1 if hit_cap else 0
