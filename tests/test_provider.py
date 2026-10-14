"""Provider 适配层测试（票据 02）：重试、用量解析、错误映射。

全部通过 httpx2.MockTransport 注入，不触网；异步用例用 asyncio.run 驱动。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2

from codelotte.providers.base import (
    ProviderError,
    StreamEnd,
    StreamUsage,
    TextDelta,
    ToolCall,
    ToolCallsEvent,
    UsageEvent,
)
from codelotte.providers.openai_completions import OpenAICompletionsClient

SSE_OK = (
    'data: {"choices":[{"delta":{"content":"你好"},"index":0}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}\n\n'
    'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":3,'
    '"prompt_cache_hit_tokens":4,"prompt_cache_miss_tokens":5}}\n\n'
    "data: [DONE]\n\n"
).encode("utf-8")


async def _no_sleep(_seconds: float) -> None:
    return None


def _collect(
    client: OpenAICompletionsClient, tools: list[dict[str, Any]] | None = None
) -> list[object]:
    async def run() -> list[object]:
        events: list[object] = []
        async for ev in client.stream_chat([{"role": "user", "content": "hi"}], tools=tools):
            events.append(ev)
        return events

    return asyncio.run(run())


def _sse_frames(*deltas: dict, finish_reason: str | None = None) -> bytes:
    """把若干 delta 拼成 SSE 响应体（用 json.dumps 序列化，避免手写转义错误）。"""
    frames = [
        "data: " + json.dumps({"choices": [{"delta": delta, "index": 0}]}) + "\n\n"
        for delta in deltas
    ]
    if finish_reason is not None:
        frames.append(
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": finish_reason, "index": 0}]})
            + "\n\n"
        )
    frames.append("data: [DONE]\n\n")
    return "".join(frames).encode("utf-8")


def _make_client(handler, **kwargs: Any) -> OpenAICompletionsClient:
    return OpenAICompletionsClient(
        base_url="http://test.local",
        api_key="k",
        model="deepseek-flash",
        transport=httpx2.MockTransport(handler),
        sleep=_no_sleep,
        jitter=0.0,
        **kwargs,
    )


def test_happy_path_parses_text_usage_and_end() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["stream_options"]["include_usage"] is True
        assert body["max_tokens"] > 0
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)

    events = _collect(_make_client(handler))
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta("你好")]
    assert [e for e in events if isinstance(e, UsageEvent)] == [
        UsageEvent(StreamUsage(input_tokens=9, output_tokens=3, cache_hit_tokens=4, cache_miss_tokens=5))
    ]
    assert events[-1] == StreamEnd(reason="stop")


def test_retryable_429_then_success_keeps_body_identical() -> None:
    seen_bodies: list[bytes] = []
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_bodies.append(request.content or b"")
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(429, json={"error": "rate limited"})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)

    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = OpenAICompletionsClient(
        base_url="http://test.local",
        api_key="k",
        model="m",
        transport=httpx2.MockTransport(handler),
        sleep=recording_sleep,
        jitter=0.0,
    )
    events = _collect(client)
    assert calls["n"] == 2
    assert delays == [0.5]
    assert seen_bodies[0] == seen_bodies[1]
    assert any(isinstance(e, TextDelta) for e in events)


def test_transport_error_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx2.ConnectError("boom")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)

    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = OpenAICompletionsClient(
        base_url="http://t",
        api_key="k",
        model="m",
        transport=httpx2.MockTransport(handler),
        sleep=recording_sleep,
        jitter=0.0,
    )
    _collect(client)
    assert calls["n"] == 3
    assert delays == [0.5, 1.0]


def test_401_is_not_retried_and_maps_to_provider_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(401, json={"error": {"message": "bad key"}})

    client = _make_client(handler)
    try:
        _collect(client)
        raise AssertionError("应抛出 ProviderError")
    except ProviderError as e:
        assert "401" in str(e)
    assert calls["n"] == 1


def test_exhausted_retries_raise_provider_error() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(503, text="unavailable")

    client = _make_client(handler, max_attempts=3)
    try:
        _collect(client)
        raise AssertionError("应抛出 ProviderError")
    except ProviderError:
        pass
    assert calls["n"] == 3


def test_error_frame_inside_stream_raises_provider_error() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"partial"},"index":0}]}\n\n'
        b'data: {"error":{"message":"content filter triggered"}}\n\n'
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    try:
        _collect(_make_client(handler))
        raise AssertionError("应抛出 ProviderError")
    except ProviderError as e:
        assert "content filter triggered" in str(e)


def test_non_dict_frames_are_ignored() -> None:
    body = (
        b"data: null\n\n"
        b"data: [1,2,3]\n\n"
        b'data: {"choices":[{"delta":{"content":"ok"},"index":0}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    events = _collect(_make_client(handler))
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta("ok")]


def test_non_sse_response_is_rejected() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "application/json"}, json={"nope": True})

    try:
        _collect(_make_client(handler))
        raise AssertionError("应抛出 ProviderError")
    except ProviderError as e:
        assert "SSE" in str(e)


def test_invalid_base_url_is_not_retried() -> None:
    delays: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        delays.append(seconds)

    client = OpenAICompletionsClient(
        base_url="api.deepseek.com",  # 缺 scheme
        api_key="k",
        model="m",
        sleep=recording_sleep,
        jitter=0.0,
    )
    try:
        _collect(client)
        raise AssertionError("应抛出 ProviderError")
    except ProviderError as e:
        assert "不会重试" in str(e)
    assert delays == []


def test_drop_after_finish_reason_is_treated_as_success() -> None:
    prefix = (
        b'data: {"choices":[{"delta":{"content":"done"},"index":0}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}\n\n'
        b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2}}\n\n'
    )

    class _ResetStream(httpx2.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield prefix
            raise httpx2.RemoteProtocolError("connection reset")

        async def aclose(self) -> None:
            return None

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=_ResetStream()
        )

    events = _collect(_make_client(handler))
    assert events[-1] == StreamEnd(reason="stop")
    assert any(isinstance(e, UsageEvent) for e in events)
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta("done")]


def test_tools_are_sent_in_request_body_and_omitted_when_absent() -> None:
    seen_bodies: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen_bodies.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)

    tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]
    _collect(_make_client(handler), tools=tools)
    _collect(_make_client(handler))
    assert seen_bodies[0]["tools"] == tools
    assert "tools" not in seen_bodies[1]


def test_tool_call_fragments_are_assembled_into_event_before_stream_end() -> None:
    """参数分片逐段到达，攒齐后以 ToolCallsEvent 产出（在 Usage/StreamEnd 之前）。"""
    body = _sse_frames(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"pa'},
                }
            ]
        },
        {"tool_calls": [{"index": 0, "function": {"arguments": 'th": "a.txt"}'}}]},
        finish_reason="tool_calls",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    events = _collect(_make_client(handler))
    assert events == [
        ToolCallsEvent(calls=(ToolCall(id="call_a", name="read", arguments='{"path": "a.txt"}'),)),
        StreamEnd(reason="tool_calls"),
    ]


def test_parallel_tool_calls_in_one_reply() -> None:
    body = _sse_frames(
        {
            "tool_calls": [
                {"index": 0, "id": "c0", "function": {"name": "read", "arguments": '{"path": "a"'}},
                {"index": 1, "id": "c1", "function": {"name": "read", "arguments": '{"path": "b"'}},
            ]
        },
        {"tool_calls": [{"index": 1, "function": {"arguments": "}"}}]},
        {"tool_calls": [{"index": 0, "function": {"arguments": "}"}}]},
        finish_reason="tool_calls",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    events = _collect(_make_client(handler))
    (tool_calls_event,) = [e for e in events if isinstance(e, ToolCallsEvent)]
    assert [c.id for c in tool_calls_event.calls] == ["c0", "c1"]
    assert [c.arguments for c in tool_calls_event.calls] == ['{"path": "a"}', '{"path": "b"}']


def test_malformed_tool_arguments_are_reported_not_fatal() -> None:
    """参数畸形是模型输出缺陷：产出带 parse_error 的 ToolCall（回传自纠），流不中止。"""
    body = _sse_frames(
        {
            "tool_calls": [
                {"index": 0, "id": "c0", "function": {"name": "read", "arguments": '{"path": '}}
            ]
        },
        finish_reason="tool_calls",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    events = _collect(_make_client(handler))
    (tool_calls_event,) = [e for e in events if isinstance(e, ToolCallsEvent)]
    (call,) = tool_calls_event.calls
    assert call.parse_error is not None
    assert call.arguments == '{"path": '  # 原始文本逐字节保留
    assert events[-1] == StreamEnd(reason="tool_calls")


def test_missing_tool_name_aborts_stream() -> None:
    """缺工具名是协议级缺陷：没有可回填的执行错误，中止本回合。"""
    body = _sse_frames(
        {"tool_calls": [{"index": 0, "id": "c0", "function": {"arguments": "{}"}}]},
        finish_reason="tool_calls",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    try:
        _collect(_make_client(handler))
        raise AssertionError("应抛出 ProviderError")
    except ProviderError as e:
        assert "工具名" in str(e)


def test_assistant_reasoning_content_and_tool_calls_pass_through_request() -> None:
    """SPEC §C 雷区：带 tools 时 assistant 的 reasoning_content 必须原样进请求体，否则 API 400。"""
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=SSE_OK)

    messages = [
        {"role": "user", "content": "读文件"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "先想再调工具",
            "tool_calls": [
                {
                    "id": "c0",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path": "a.txt"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c0", "content": "1\ta"},
    ]
    tools = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]

    async def run() -> None:
        async for _event in _make_client(handler).stream_chat(messages, tools=tools):
            pass

    asyncio.run(run())
    assert seen[0]["messages"] == messages
    assert seen[0]["messages"][1]["reasoning_content"] == "先想再调工具"


def test_tool_calls_survive_drop_after_finish_reason() -> None:
    """finish_reason 已到、连接随后被切断：按成功处理，工具调用照常产出。"""
    chunk = _sse_frames(
        {
            "tool_calls": [
                {"index": 0, "id": "c0", "function": {"name": "read", "arguments": '{"path": "a"}'}}
            ]
        },
        finish_reason="tool_calls",
    )[:-len(b"data: [DONE]\n\n")]

    class _ResetStream(httpx2.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[override]
            yield chunk
            raise httpx2.RemoteProtocolError("connection reset")

        async def aclose(self) -> None:
            return None

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=_ResetStream()
        )

    events = _collect(_make_client(handler))
    assert events[-1] == StreamEnd(reason="tool_calls")
    assert ToolCallsEvent(calls=(ToolCall(id="c0", name="read", arguments='{"path": "a"}'),)) in events
