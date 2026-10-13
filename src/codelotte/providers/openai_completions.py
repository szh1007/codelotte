"""OpenAI 兼容协议（chat/completions）的流式客户端。

DeepSeek 官方端点即 OpenAI 兼容；本模块是 ADR-0004 中 v1 的第一条
wire protocol（anthropic-messages 为后续第二条）。

设计要点：
- 请求体显式设置 max_tokens（DeepSeek 默认上限远小于最大值，会静默截断）
- stream_options.include_usage=true，让末尾 chunk 带 usage（含缓存命中字段）
- 重试：仅对「尚未收到任何文本」的可重试失败（429/5xx/网络错误）做指数退避；
  每次重试的请求体与首次逐字节相同（不破坏前缀缓存）；已输出内容后不再重试
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx2

from codelotte.providers.base import ProviderError, StreamEnd, StreamUsage, TextDelta, UsageEvent
from codelotte.providers.sse import decode_sse_async

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 8.0


class _RetryableStatus(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def _parse_usage(raw: dict[str, Any]) -> StreamUsage:
    details = raw.get("prompt_tokens_details") or {}
    hit = raw.get("prompt_cache_hit_tokens")
    if hit is None:
        hit = details.get("cached_tokens", 0)
    input_tokens = int(raw.get("prompt_tokens", 0) or 0)
    hit = int(hit or 0)
    miss = raw.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = max(input_tokens - hit, 0)
    return StreamUsage(
        input_tokens=input_tokens,
        output_tokens=int(raw.get("completion_tokens", 0) or 0),
        cache_hit_tokens=hit,
        cache_miss_tokens=int(miss or 0),
    )


class OpenAICompletionsClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        transport: httpx2.AsyncBaseTransport | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        jitter: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._transport = transport
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._jitter = jitter
        self._sleep = sleep

    def _backoff_delay(self, attempt: int) -> float:
        delay = min(self._backoff_base * (2 ** (attempt - 1)), self._backoff_cap)
        if self._jitter:
            delay += random.uniform(0, delay * self._jitter)
        return delay

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[TextDelta | UsageEvent | StreamEnd]:
        body = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        attempt = 0
        while True:
            attempt += 1
            emitted = False
            try:
                async with httpx2.AsyncClient(
                    base_url=self._base_url,
                    transport=self._transport,
                    timeout=httpx2.Timeout(60.0, connect=15.0),
                ) as client:
                    async with client.stream(
                        "POST", "/chat/completions", json=body, headers=headers
                    ) as response:
                        if response.status_code in RETRYABLE_STATUS or response.status_code >= 500:
                            raise _RetryableStatus(response.status_code)
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode("utf-8", errors="replace")
                            raise ProviderError(
                                f"DeepSeek API 返回 {response.status_code}：{detail[:300]}"
                            )
                        usage: StreamUsage | None = None
                        stop_reason: str | None = None
                        async for sse in decode_sse_async(response.aiter_bytes()):
                            if sse.data == "[DONE]":
                                break
                            try:
                                payload = json.loads(sse.data)
                            except json.JSONDecodeError:
                                continue
                            chunk_usage = payload.get("usage")
                            if chunk_usage:
                                usage = _parse_usage(chunk_usage)
                            for choice in payload.get("choices") or []:
                                delta = choice.get("delta") or {}
                                text = delta.get("content")
                                if text:
                                    emitted = True
                                    yield TextDelta(text)
                                if choice.get("finish_reason"):
                                    stop_reason = choice["finish_reason"]
                        if usage is not None:
                            yield UsageEvent(usage)
                        yield StreamEnd(reason=stop_reason)
                        return
            except (httpx2.TransportError, _RetryableStatus) as exc:
                if emitted:
                    raise ProviderError(
                        f"流式响应中途失败（已输出部分内容，不再重试）：{exc}"
                    ) from exc
                if attempt >= self._max_attempts:
                    raise ProviderError(f"模型服务连续 {attempt} 次失败：{exc}") from exc
                await self._sleep(self._backoff_delay(attempt))
