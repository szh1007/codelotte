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
class ToolCall:
    """模型请求的一次工具调用（分片已装配完成）。

    arguments 为原始 JSON 文本：回传模型时逐字节一致，是前缀缓存稳定的前提。
    parse_error 非空表示参数不是合法 JSON 对象——这是模型输出缺陷而非系统错误，
    执行层不执行它、把错误作为工具结果回传让它自纠（SPEC §D）。
    """

    id: str
    name: str
    arguments: str
    parse_error: str | None = None


@dataclass(frozen=True)
class ToolCallsEvent:
    """一次回复中请求的全部工具调用（流结束、分片装配完成后统一发出）。"""

    calls: tuple[ToolCall, ...]


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
