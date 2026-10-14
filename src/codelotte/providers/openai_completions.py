"""OpenAI 兼容协议（chat/completions）的流式客户端。

DeepSeek 官方端点即 OpenAI 兼容；本模块是 ADR-0004 中 v1 的第一条
wire protocol（anthropic-messages 为后续第二条）。

设计要点（评审加固版）：
- 只接受 text/event-stream 响应：重定向/HTML/JSON 错误体一律报错，绝不"空成功"
- 流内 {"error": ...} 帧视为失败；非对象帧忽略而不是崩溃
- 重试：仅对「尚未收到任何文本」的可重试失败（429/5xx/网络错误）做指数退避；
  请求体逐字节不变（不破坏前缀缓存）；已输出内容后不再重试；
  已收到 finish_reason 后连接被切断 → 按成功处理（回答已完整）
- 配置类错误（InvalidURL/UnsupportedProtocol）不重试，立即报可读错误
- 每次重试记 warning 日志（不静默）
- tool_calls 分片由 ToolCallAssembler 按 index 攒齐（每次尝试用新装配器，
  重试不会混入上一次的残片），流正常结束后统一产出 ToolCallsEvent；
  参数畸形的调用记入 ToolCall.parse_error（回传模型自纠），只有缺工具名
  这种协议级缺陷才中止回合
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx2

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
from codelotte.providers.sse import decode_sse_async
from codelotte.providers.tool_calls import ToolCallAssembler, ToolCallAssemblyError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_TOKENS = 8192
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

    @staticmethod
    def _assemble(assembler: ToolCallAssembler) -> tuple[ToolCall, ...]:
        """装配分片。缺工具名是协议级缺陷（没有可回填的执行错误），中止本回合。"""
        try:
            return assembler.finish()
        except ToolCallAssemblyError as exc:
            raise ProviderError(f"模型返回的工具调用无法装配：{exc}") from exc

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[
        TextDelta | ReasoningDelta | ToolCallsEvent | UsageEvent | StreamEnd
    ]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        if tools:
            # tool_choice 不显式设置（默认 auto）：思考模式不支持 required/指定工具
            body["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        usage: StreamUsage | None = None
        stop_reason: str | None = None
        emitted = False
        attempt = 0
        while True:
            attempt += 1
            assembler = ToolCallAssembler()  # 每次尝试用新装配器，重试不混入残片
            try:
                async with httpx2.AsyncClient(
                    base_url=self._base_url,
                    transport=self._transport,
                    timeout=httpx2.Timeout(60.0, connect=15.0),
                ) as client:
                    async with client.stream(
                        "POST", "/chat/completions", json=body, headers=headers
                    ) as response:
                        if (
                            response.status_code in RETRYABLE_STATUS
                            or response.status_code >= 500
                        ):
                            raise _RetryableStatus(response.status_code)
                        if response.status_code >= 400:
                            detail = (await response.aread()).decode(
                                "utf-8", errors="replace"
                            )
                            raise ProviderError(
                                f"DeepSeek API 返回 {response.status_code}：{detail[:300]}"
                            )
                        content_type = response.headers.get("content-type", "")
                        if "text/event-stream" not in content_type:
                            detail = (await response.aread()).decode(
                                "utf-8", errors="replace"
                            )
                            raise ProviderError(
                                f"响应不是 SSE 流（HTTP {response.status_code}，"
                                f"content-type={content_type!r}）：{detail[:300]}"
                            )
                        async for sse in decode_sse_async(response.aiter_bytes()):
                            if sse.data == "[DONE]":
                                break
                            try:
                                payload = json.loads(sse.data)
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(payload, dict):
                                continue
                            if "error" in payload:
                                detail = json.dumps(
                                    payload["error"], ensure_ascii=False
                                )
                                raise ProviderError(f"服务端流内错误：{detail[:300]}")
                            chunk_usage = payload.get("usage")
                            if chunk_usage:
                                usage = _parse_usage(chunk_usage)
                            for choice in payload.get("choices") or []:
                                delta = choice.get("delta") or {}
                                reasoning = delta.get("reasoning_content")
                                if isinstance(reasoning, str) and reasoning:
                                    yield ReasoningDelta(reasoning)
                                text = delta.get("content")
                                if isinstance(text, str) and text:
                                    emitted = True
                                    yield TextDelta(text)
                                for fragment in delta.get("tool_calls") or []:
                                    if not isinstance(fragment, dict):
                                        continue
                                    function = fragment.get("function")
                                    if not isinstance(function, dict):
                                        function = {}
                                    raw_index = fragment.get("index")
                                    call_id = fragment.get("id")
                                    name = function.get("name")
                                    arguments = function.get("arguments")
                                    assembler.add_fragment(
                                        raw_index if isinstance(raw_index, int) else 0,
                                        id=(
                                            call_id
                                            if isinstance(call_id, str)
                                            else None
                                        ),
                                        name=name if isinstance(name, str) else None,
                                        arguments=(
                                            arguments
                                            if isinstance(arguments, str)
                                            else ""
                                        ),
                                    )
                                if choice.get("finish_reason"):
                                    stop_reason = choice["finish_reason"]
                        calls = self._assemble(assembler)
                        if calls:
                            yield ToolCallsEvent(calls=calls)
                        if usage is not None:
                            yield UsageEvent(usage)
                        yield StreamEnd(reason=stop_reason)
                        return
            except (httpx2.InvalidURL, httpx2.UnsupportedProtocol) as exc:
                raise ProviderError(f"请求配置错误（不会重试）：{exc}") from exc
            except (httpx2.HTTPError, _RetryableStatus) as exc:
                if stop_reason is not None:
                    logger.warning("流在 finish_reason 之后被切断，按成功处理：%s", exc)
                    calls = self._assemble(
                        assembler
                    )  # reason 已到但连接断：工具调用照常产出
                    if calls:
                        yield ToolCallsEvent(calls=calls)
                    if usage is not None:
                        yield UsageEvent(usage)
                    yield StreamEnd(reason=stop_reason)
                    return
                if emitted:
                    raise ProviderError(
                        f"流式响应中途失败（已输出部分内容，不再重试）：{exc}"
                    ) from exc
                if attempt >= self._max_attempts:
                    raise ProviderError(
                        f"模型服务连续 {attempt} 次失败：{exc}"
                    ) from exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "模型请求失败（第 %d/%d 次：%s），%.1f 秒后重试",
                    attempt,
                    self._max_attempts,
                    exc,
                    delay,
                )
                await self._sleep(delay)
