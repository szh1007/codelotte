"""Provider 缝的脚本化假客户端（SPEC §K 主缝）：按剧本吐统一流事件，测试不碰网络。

剧本 = 事件列表（TextDelta / ToolCallsEvent / UsageEvent / StreamEnd），特殊项：
- PAUSE：假客户端在此永久等待（只能被取消唤醒）——测 Ctrl+C 中断；
- 异常实例（如 ProviderError(...)）：就地抛出——测流式中途失败。
请求数超出剧本时复用最后一个剧本（与 e2e 假服务器同规则）。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from codelotte.providers.base import (
    ProviderEvent,
    StreamEnd,
    StreamUsage,
    TextDelta,
    ToolCall,
    ToolCallsEvent,
    UsageEvent,
)


class _Pause:
    """剧本里的"卡住"标记（不是事件，只作控制流；假客户端不会把它吐给消费者）。"""


PAUSE = _Pause()


class ScriptedClient:
    def __init__(self, turns: Sequence[Sequence[object]]) -> None:
        self._turns = [list(turn) for turn in turns]
        self.requests: list[list[dict[str, Any]]] = []  # 每次请求的消息数组快照（断言用）
        self.paused = asyncio.Event()  # 进入 PAUSE 时置位——测试据此确定"已卡住"

    async def stream_chat(
        self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append([dict(message) for message in messages])
        index = min(len(self.requests) - 1, len(self._turns) - 1)
        script = self._turns[index] if self._turns else []
        for item in script:
            if item is PAUSE:
                self.paused.set()
                await asyncio.Event().wait()  # 直到整个回合被取消
            if isinstance(item, BaseException):
                raise item
            yield item  # type: ignore[misc]  # 剧本只放 ProviderEvent 实例


def text_turn(
    text: str,
    *,
    usage: tuple[int, int, int, int] | None = (10, 5, 0, 0),
    finish: str | None = "stop",
) -> list[object]:
    """一轮纯文本回复的剧本。"""
    events: list[object] = [TextDelta(text)]
    if usage is not None:
        events.append(UsageEvent(StreamUsage(*usage)))
    events.append(StreamEnd(finish))
    return events


def tool_turn(
    name: str,
    arguments: dict[str, Any],
    *,
    call_id: str = "call_1",
    usage: tuple[int, int, int, int] | None = (10, 5, 0, 0),
) -> list[object]:
    """一轮"请求调用工具"的剧本。"""
    call = ToolCall(id=call_id, name=name, arguments=json.dumps(arguments, ensure_ascii=False))
    events: list[object] = [ToolCallsEvent((call,))]
    if usage is not None:
        events.append(UsageEvent(StreamUsage(*usage)))
    events.append(StreamEnd("tool_calls"))
    return events
