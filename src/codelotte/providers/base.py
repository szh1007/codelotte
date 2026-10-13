"""Provider 层公共类型：统一流事件与错误。"""

from __future__ import annotations

from dataclasses import dataclass


class ProviderError(Exception):
    """模型服务调用失败（网络、限流、协议或服务端错误）。"""


@dataclass(frozen=True)
class TextDelta:
    """一段增量文本（流式输出的一段）。"""

    text: str


@dataclass(frozen=True)
class ReasoningDelta:
    """一段增量推理内容（thinking 模式的 reasoning_content）。"""

    text: str


@dataclass(frozen=True)
class StreamUsage:
    """一次模型调用的 token 用量。"""

    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int


@dataclass(frozen=True)
class UsageEvent:
    usage: StreamUsage


@dataclass(frozen=True)
class StreamEnd:
    reason: str | None
