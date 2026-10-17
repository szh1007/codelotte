"""工具注册表与执行策略测试（票据 04）：四工具齐备、wire 形状、失败转结果文本。"""

from __future__ import annotations

import asyncio
from typing import Any

from codelotte.sandbox import LocalExecutor
from codelotte.tools import default_tools, execute_tool, find_tool, wire_tools
from codelotte.tools.base import Tool, ToolError, ToolOutcome


def _tools() -> tuple[Tool, ...]:
    return default_tools(LocalExecutor())


def test_default_tools_has_all_four_in_order() -> None:
    assert [t.name for t in _tools()] == ["read", "write", "edit", "bash"]


def test_bash_carries_the_executor_environment_into_audit_records() -> None:
    """bash 跟执行器走（docker / local）；文件工具永远在宿主上执行——审计标记要如实。"""
    from codelotte.sandbox import DockerExecutor

    envs = {tool.name: tool.exec_env for tool in default_tools(DockerExecutor())}
    assert envs == {"read": "local", "write": "local", "edit": "local", "bash": "docker"}


def test_wire_schemas_are_openai_shaped() -> None:
    schemas = wire_tools(_tools())
    assert [s["function"]["name"] for s in schemas] == ["read", "write", "edit", "bash"]
    for schema in schemas:
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["description"].strip()  # 描述是 prompt 工程：不能为空
        assert function["parameters"]["type"] == "object"
        assert function["parameters"]["required"]  # 每个工具都有必填参数


def test_find_tool_returns_none_for_unknown() -> None:
    assert find_tool("nope", _tools()) is None


def test_unknown_tool_is_a_result_not_an_exception() -> None:
    result = asyncio.run(execute_tool("nope", {}, tools=_tools()))
    assert result.ok is False
    assert "未知工具" in result.content


def _tool_with(handler: Any, name: str = "t") -> tuple[Tool, ...]:
    return (Tool(name=name, description="d", parameters={"type": "object"}, handler=handler),)


def test_tool_error_becomes_error_text() -> None:
    async def boom(args: dict[str, Any]) -> str:
        raise ToolError("文件不存在：x")

    result = asyncio.run(execute_tool("t", {}, tools=_tool_with(boom)))
    assert result.ok is False
    assert result.content == "错误：文件不存在：x"


def test_unexpected_exception_is_contained() -> None:
    async def bug(args: dict[str, Any]) -> str:
        raise RuntimeError("内部 bug")

    result = asyncio.run(execute_tool("t", {}, tools=_tool_with(bug)))
    assert result.ok is False
    assert "工具内部异常" in result.content
    assert "RuntimeError" in result.content  # 类型名带上，便于归因


def test_tool_outcome_ok_flag_is_respected() -> None:
    async def failing(args: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(content="退出码 1", ok=False)

    result = asyncio.run(execute_tool("t", {}, tools=_tool_with(failing)))
    assert result.ok is False
    assert result.content == "退出码 1"
