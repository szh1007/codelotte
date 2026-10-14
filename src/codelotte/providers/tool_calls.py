"""工具调用分片装配：流式响应里 arguments 是一段段到达的，先攒齐再解析。

同一回复可能并发多个工具调用（DeepSeek 默认开启并行且不可关闭），分片用
index 归类（不同 index 的分片可能交错到达）；装配结果按 index 排序，保证
执行顺序与会话记录顺序确定。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from codelotte.providers.base import ToolCall

_PREVIEW_LIMIT = 120


class ToolCallAssemblyError(Exception):
    """分片无法装配成完整调用（缺工具名——协议级缺陷，没有可回填的执行错误）。"""


@dataclass
class _Partial:
    id: str = ""
    name: str = ""
    fragments: list[str] = field(default_factory=list)


class ToolCallAssembler:
    """按 index 累积 tool_call 分片；finish() 校验并产出完整的 ToolCall 列表。"""

    def __init__(self) -> None:
        self._partials: dict[int, _Partial] = {}

    def add_fragment(
        self,
        index: int,
        *,
        id: str | None = None,
        name: str | None = None,
        arguments: str = "",
    ) -> None:
        """喂入一段分片。id/name 只在首个分片出现（重复出现时取先到的非空值）。"""
        partial = self._partials.setdefault(index, _Partial())
        if id and not partial.id:
            partial.id = id
        if name and not partial.name:
            partial.name = name
        if arguments:
            partial.fragments.append(arguments)

    def finish(self) -> tuple[ToolCall, ...]:
        """产出完整调用（按 index 排序，空装配器返回空元组）。

        arguments 原样保留模型给出的 JSON 文本——回传模型时逐字节一致，
        是前缀缓存稳定的前提；空串按"无参数"规范化为 {}。
        参数不是合法 JSON 对象不算装配失败：记入 ToolCall.parse_error，
        由执行层作为工具结果回传模型自纠（一个坏调用不拖垮并行的兄弟调用）。

        Raises:
            ToolCallAssemblyError: 缺工具名。
        """
        calls: list[ToolCall] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            position = index + 1  # 报错信息用人类可读的序号
            if not partial.name:
                raise ToolCallAssemblyError(f"第 {position} 个工具调用缺少工具名")
            raw = "".join(partial.fragments)
            if not raw.strip():
                raw = "{}"
            calls.append(
                ToolCall(
                    id=partial.id or _synthetic_id(index),
                    name=partial.name,
                    arguments=raw,
                    parse_error=_parse_error(raw),
                )
            )
        return tuple(calls)


def _parse_error(raw: str) -> str | None:
    """校验参数 JSON；合法返回 None，畸形返回给模型看的原因。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"参数不是合法 JSON（{exc}；收到的片段：{_preview(raw)}）"
    if not isinstance(parsed, dict):
        return f"参数不是 JSON 对象：{_preview(raw)}"
    return None


def _synthetic_id(index: int) -> str:
    """模型漏 id 时补一个唯一 id：tool 结果消息靠它配对。

    带随机后缀——不同轮次都用 call_{index} 会让回放历史里的 tool_call_id 撞车。
    """
    return f"call_{index}_{uuid.uuid4().hex[:8]}"


def _preview(raw: str) -> str:
    return raw if len(raw) <= _PREVIEW_LIMIT else raw[:_PREVIEW_LIMIT] + "…"
