"""内联 SSE（text/event-stream）解码器——约百行，不引第三方库。

输入是网络的字节分片，输出是完整事件。关键点：
- 分片边界可以落在任意位置（半行、半个多字节字符）：增量 UTF-8 解码 + 行缓冲
- `:` 开头是注释行（keep-alive），忽略
- 事件以空行结束；多个 `data:` 行以换行连接（text/event-stream 规范）
"""

from __future__ import annotations

import codecs
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: str


class SSEDecoder:
    """增量解码器：喂入字节分片，吐出已完成的 SSE 事件。"""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._buffer = ""
        self._event_name: str | None = None
        self._data_lines: list[str] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        events: list[SSEEvent] = []
        self._buffer += self._decoder.decode(chunk)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                event = self._flush()
                if event is not None:
                    events.append(event)
                continue
            if line.startswith(":"):
                continue  # 注释行 / keep-alive
            if ":" in line:
                field_name, value = line.split(":", 1)
                if value.startswith(" "):
                    value = value[1:]
            else:
                field_name, value = line, ""
            if field_name == "event":
                self._event_name = value
            elif field_name == "data":
                self._data_lines.append(value)
            # id / retry 等字段暂不需要，忽略
        return events

    def _flush(self) -> SSEEvent | None:
        if not self._data_lines and self._event_name is None:
            return None
        event = SSEEvent(event=self._event_name, data="\n".join(self._data_lines))
        self._event_name = None
        self._data_lines.clear()
        return event


def decode_sse(chunks: Iterable[bytes]) -> Iterator[SSEEvent]:
    """同步版：给单元测试与本地回放用。"""
    decoder = SSEDecoder()
    for chunk in chunks:
        yield from decoder.feed(chunk)


async def decode_sse_async(chunks: AsyncIterable[bytes]) -> AsyncIterator[SSEEvent]:
    """异步版：消费网络字节流（httpx2 的 aiter_bytes）。"""
    decoder = SSEDecoder()
    async for chunk in chunks:
        for event in decoder.feed(chunk):
            yield event
