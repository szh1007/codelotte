"""内置工具注册表与执行入口（票据 04：read / write / edit / bash 四工具齐备）。

换行统一约定：模型的世界里只有 \n——read 呈现 LF 视图、write 原样写 LF、
edit 比对时把文件的 \r\n 看成 \n（只看不改；只替换命中段，新内容跟文件风格）。

执行策略（SPEC §D）：**工具失败不是异常**——可预期失败（ToolError）与
意外异常都转成错误文本作为结果回传模型自纠；只有系统级故障才中断回合。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from codelotte.sandbox import Executor
from codelotte.tools.base import Tool, ToolError, ToolOutcome, wire_schema
from codelotte.tools.bash import bash_tool
from codelotte.tools.edit import EDIT_TOOL
from codelotte.tools.read import READ_TOOL
from codelotte.tools.write import WRITE_TOOL

logger = logging.getLogger(__name__)


def default_tools(executor: Executor) -> tuple[Tool, ...]:
    """四个内置工具（SPEC §D）。执行器由调用方注入——票据 10 在此换 Docker 实现。"""
    return (READ_TOOL, WRITE_TOOL, EDIT_TOOL, bash_tool(executor))


@dataclass(frozen=True)
class ToolResult:
    """一次工具执行的结果。content 是回传给模型的文本（失败时为错误文本）。"""

    content: str
    ok: bool
    duration_ms: int


def find_tool(name: str, tools: tuple[Tool, ...]) -> Tool | None:
    for tool in tools:
        if tool.name == name:
            return tool
    return None


def wire_tools(tools: tuple[Tool, ...]) -> list[dict[str, Any]]:
    """转成 OpenAI 兼容协议的 tools 数组（顺序固定，保证请求前缀逐字节稳定）。"""
    return [wire_schema(tool) for tool in tools]


async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    tools: tuple[Tool, ...],
) -> ToolResult:
    """执行一次工具调用，永不向上抛异常（这是设计决策，见 SPEC §D）。"""
    started = time.perf_counter()

    def elapsed_ms() -> int:
        return round((time.perf_counter() - started) * 1000)

    tool = find_tool(name, tools)
    if tool is None:
        return ToolResult(content=f"错误：未知工具：{name}", ok=False, duration_ms=0)
    try:
        outcome = await tool.handler(arguments)
    except ToolError as exc:
        return ToolResult(content=f"错误：{exc}", ok=False, duration_ms=elapsed_ms())
    except Exception as exc:  # 工具 bug 不能杀死回合，转成错误文本让模型自纠
        logger.exception("工具 %s 执行时发生意外异常", name)
        return ToolResult(
            content=f"错误：工具内部异常（{type(exc).__name__}: {exc}）",
            ok=False,
            duration_ms=elapsed_ms(),
        )
    if isinstance(outcome, ToolOutcome):
        return ToolResult(
            content=outcome.content, ok=outcome.ok, duration_ms=elapsed_ms()
        )
    return ToolResult(content=outcome, ok=True, duration_ms=elapsed_ms())
