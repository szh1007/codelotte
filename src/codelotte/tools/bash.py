"""bash 工具：执行任意 shell 命令（SPEC §D：搜索/测试/git 等统一走 bash，不设专用工具）。

命令经执行器（sandbox 组件）执行——工具代码不直接碰系统 shell；
超时杀整个进程组；超长输出截断保留头尾，全文写入临时文件。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codelotte.sandbox import ExecResult, Executor
from codelotte.tools.base import (
    Tool,
    ToolError,
    ToolOutcome,
    cap_output,
    int_arg,
    str_arg,
)

DEFAULT_TIMEOUT = 120  # 秒
MAX_TIMEOUT = 600  # 秒


def bash_tool(executor: Executor) -> Tool:
    """构造 bash 工具。执行器由调用方注入——票据 10 换 Docker 实现，工具代码不变。"""

    async def handler(args: dict[str, Any]) -> ToolOutcome:
        command = str_arg(args, "command")
        timeout = int_arg(
            args, "timeout", DEFAULT_TIMEOUT, minimum=1, maximum=MAX_TIMEOUT
        )
        try:
            result = await executor.run(command, cwd=Path.cwd(), timeout=float(timeout))
        except OSError as exc:
            raise ToolError(f"无法执行命令：{exc}") from exc
        content = _format_result(result, timeout)
        return ToolOutcome(
            content=cap_output(content, label="bash"), ok=_succeeded(result)
        )

    return Tool(
        name="bash",
        description=(
            "Run a shell command in the current working directory and return its output "
            "(stdout, stderr, exit code). Use it for searching, running tests or builds, git, "
            "and any other command; use read/write/edit for file contents. "
            "Commands are killed after timeout seconds; very long output is truncated "
            "(the full output is saved to a temporary file whose path is included in the result)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command line to run.",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Seconds before the command is killed (1-{MAX_TIMEOUT}). "
                        f"Defaults to {DEFAULT_TIMEOUT}."
                    ),
                },
            },
            "required": ["command"],
        },
        handler=handler,
    )


def _succeeded(result: ExecResult) -> bool:
    """退出码非 0 或超时都算这次执行失败（会话记录/死循环防御按失败计数）。"""
    return not result.timed_out and result.exit_code == 0


def _format_result(result: ExecResult, timeout: int) -> str:
    if result.timed_out:
        head = f"命令超过 {timeout} 秒未结束，已终止整个进程组。"
    else:
        head = f"退出码 {result.exit_code}"
    sections = [head]
    if result.stdout:
        sections.append(result.stdout.rstrip("\n"))
    if result.stderr:
        sections.append("[stderr]\n" + result.stderr.rstrip("\n"))
    return "\n".join(sections)
