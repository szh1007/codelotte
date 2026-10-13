"""无头单次执行（票据 02）：组请求 → 流式打印 → 会话落盘。"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

import httpx2

from codelotte.config import get_api_key, get_base_url, get_model, get_session_dir
from codelotte.providers.base import StreamEnd, TextDelta, UsageEvent
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.session.store import SessionStore


async def run_once(
    prompt: str,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
    env: Mapping[str, str] | None = None,
    transport: httpx2.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> int:
    stdout = out if out is not None else sys.stdout
    stderr = err if err is not None else sys.stderr

    api_key = get_api_key(env)
    base_url = get_base_url(env)
    model = get_model(env)
    session_base = get_session_dir(env)

    store = SessionStore.start(Path.cwd(), base_dir=session_base)
    store.append("message", role="user", content=prompt)

    overrides: dict[str, Any] = {}
    if transport is not None:
        overrides["transport"] = transport
    if sleep is not None:
        overrides["sleep"] = sleep
    client = OpenAICompletionsClient(
        base_url=base_url, api_key=api_key, model=model, **overrides
    )

    parts: list[str] = []
    usage = None
    stop_reason: str | None = None
    async for event in client.stream_chat([{"role": "user", "content": prompt}]):
        if isinstance(event, TextDelta):
            stdout.write(event.text)
            stdout.flush()
            parts.append(event.text)
        elif isinstance(event, UsageEvent):
            usage = event.usage
        elif isinstance(event, StreamEnd):
            stop_reason = event.reason
    if parts and not parts[-1].endswith("\n"):
        stdout.write("\n")
        stdout.flush()

    store.append(
        "message", role="assistant", content="".join(parts), model=model, stopReason=stop_reason
    )
    if usage is not None:
        store.append(
            "usage",
            model=model,
            inputTokens=usage.input_tokens,
            outputTokens=usage.output_tokens,
            cacheHitTokens=usage.cache_hit_tokens,
            cacheMissTokens=usage.cache_miss_tokens,
        )
    in_tokens = usage.input_tokens if usage else "?"
    out_tokens = usage.output_tokens if usage else "?"
    hit_tokens = usage.cache_hit_tokens if usage else "?"
    stderr.write(f"[codelotte] tokens in={in_tokens} out={out_tokens} cache_hit={hit_tokens} | session: {store.path}\n")
    stderr.flush()
    return 0
