"""Provider 适配层测试（票据 02）：重试、用量解析、错误映射。

全部通过 httpx2.MockTransport 注入，不触网；异步用例用 asyncio.run 驱动。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2

from codelotte.providers.base import ProviderError, StreamEnd, StreamUsage, TextDelta, UsageEvent
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


def _collect(client: OpenAICompletionsClient) -> list[object]:
    async def run() -> list[object]:
        events: list[object] = []
        async for ev in client.stream_chat([{"role": "user", "content": "hi"}]):
            events.append(ev)
        return events

    return asyncio.run(run())


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
