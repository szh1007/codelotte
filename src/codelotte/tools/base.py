"""工具层公共类型：工具定义与可预期失败（SPEC §D）。

工具 = 名字 + 描述 + 参数 JSON Schema + 执行函数。模型只看到前三者
（wire 格式），执行永远在我们这侧。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any


class ToolError(Exception):
    """工具的可预期失败（文件不存在、参数缺失等）。

    由执行层转成结果文本回传模型让它自纠，不视为系统错误（SPEC §D）。
    """


ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, str]]


@dataclass(frozen=True)
class Tool:
    """一个工具的定义。handler 抛 ToolError 表示可预期失败，正常时返回结果文本。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


def wire_schema(tool: Tool) -> dict[str, Any]:
    """转成 OpenAI 兼容协议的工具定义（键序固定，保证请求前缀逐字节稳定）。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
