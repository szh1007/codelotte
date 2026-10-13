"""无头单次执行（票据 02）：组请求 → 流式打印 → 会话落盘。

不变量：**记录是事实源**——即使流式过程中途失败，已打印的内容也会
先落入会话（stopReason=interrupted）再向上抛错，绝不出现"终端看到了、
会话里没有"的悬空状态。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from codelotte.config import get_api_key, get_base_url, get_model, get_session_dir
from codelotte.providers.base import (
    ProviderError,
    ReasoningDelta,
    StreamEnd,
    TextDelta,
    UsageEvent,
)
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.session.store import SessionStore


async def run_once(prompt: str) -> int:
    api_key = get_api_key()
    base_url = get_base_url()
    model = get_model()
    session_base = get_session_dir()

    store = SessionStore.start(Path.cwd(), base_dir=session_base)
    store.append("message", role="user", content=prompt)

    client = OpenAICompletionsClient(base_url=base_url, api_key=api_key, model=model)
    parts: list[str] = []
    reasoning_parts: list[str] = []
    usage = None
    stop_reason: str | None = None
    failure: ProviderError | None = None
    try:
        async for event in client.stream_chat([{"role": "user", "content": prompt}]):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
                parts.append(event.text)
            elif isinstance(event, ReasoningDelta):
                reasoning_parts.append(event.text)
            elif isinstance(event, UsageEvent):
                usage = event.usage
            elif isinstance(event, StreamEnd):
                stop_reason = event.reason
    except ProviderError as exc:
        failure = exc

    if parts and not parts[-1].endswith("\n"):
        sys.stdout.write("\n")
        sys.stdout.flush()

    assistant_fields: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(parts),
        "model": model,
        "stopReason": "interrupted" if failure is not None else stop_reason,
    }
    if reasoning_parts:
        assistant_fields["reasoningContent"] = "".join(reasoning_parts)
    store.append("message", **assistant_fields)
    if usage is not None:
        store.append(
            "usage",
            model=model,
            inputTokens=usage.input_tokens,
            outputTokens=usage.output_tokens,
            cacheHitTokens=usage.cache_hit_tokens,
            cacheMissTokens=usage.cache_miss_tokens,
        )

    if failure is not None:
        raise failure
    if stop_reason is None:
        sys.stderr.write("[codelotte] 警告：响应未正常结束（无 stop 标记），回答可能不完整\n")
    elif stop_reason == "length":
        sys.stderr.write("[codelotte] 警告：输出被 max_tokens 截断（finish_reason=length）\n")
    in_tokens = usage.input_tokens if usage else "?"
    out_tokens = usage.output_tokens if usage else "?"
    hit_tokens = usage.cache_hit_tokens if usage else "?"
    sys.stderr.write(
        f"[codelotte] tokens in={in_tokens} out={out_tokens} cache_hit={hit_tokens}"
        f" | session: {store.path}\n"
    )
    sys.stderr.flush()
    return 0
