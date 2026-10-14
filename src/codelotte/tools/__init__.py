"""内置工具注册表与执行入口（票据 03：read；票据 04 增加 write/edit/bash）。

执行策略（SPEC §D）：**工具失败不是异常**——可预期失败（ToolError）与
意外异常都转成错误文本作为结果回传模型自纠；只有系统级故障才中断回合。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from codelotte.tools.base import Tool, ToolError, wire_schema
from codelotte.tools.read import READ_TOOL

logger = logging.getLogger(__name__)

BUILTIN_TOOLS: tuple[Tool, ...] = (READ_TOOL,)


@dataclass(frozen=True)
class ToolResult:
    """一次工具执行的结果。content 是回传给模型的文本（失败时为错误文本）。"""

    content: str
    ok: bool
    duration_ms: int


def find_tool(name: str) -> Tool | None:
    for tool in BUILTIN_TOOLS:
        if tool.name == name:
            return tool
    return None


def wire_tools() -> list[dict[str, Any]]:
    """转成 OpenAI 兼容协议的 tools 数组（顺序固定，保证请求前缀逐字节稳定）。"""
    return [wire_schema(tool) for tool in BUILTIN_TOOLS]


async def execute_tool(name: str, arguments: dict[str, Any]) -> ToolResult:
    """执行一次工具调用，永不向上抛异常（这是设计决策，见 SPEC §D）。"""
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    tool = find_tool(name)
    if tool is None:
        return ToolResult(content=f"错误：未知工具：{name}", ok=False, duration_ms=0)
    try:
        content = await tool.handler(arguments)
    except ToolError as exc:
        return ToolResult(content=f"错误：{exc}", ok=False, duration_ms=elapsed_ms())
    except Exception as exc:  # 工具 bug 不能杀死回合，转成错误文本让模型自纠
        logger.exception("工具 %s 执行时发生意外异常", name)
        return ToolResult(
            content=f"错误：工具内部异常（{type(exc).__name__}: {exc}）",
            ok=False,
            duration_ms=elapsed_ms(),
        )
    return ToolResult(content=content, ok=True, duration_ms=elapsed_ms())
