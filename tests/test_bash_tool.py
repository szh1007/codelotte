"""bash 工具测试（票据 04）：只经执行器执行、退出码语义、超时、输出截断与全文去向。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from codelotte.sandbox import ExecResult, LocalExecutor
from codelotte.tools.base import Tool, ToolError, ToolOutcome
from codelotte.tools.bash import DEFAULT_TIMEOUT, MAX_TIMEOUT, bash_tool


class _RecordingExecutor:
    """记录调用参数的假执行器：证明工具层只依赖 Executor 协议、不直接碰系统 shell。"""

    env = "test"

    def __init__(self, result: ExecResult) -> None:
        self.result = result
        self.calls: list[tuple[str, Path, float]] = []

    async def run(self, command: str, *, cwd: Path, timeout: float) -> ExecResult:
        self.calls.append((command, cwd, timeout))
        return self.result


def _result(
    stdout: str = "", stderr: str = "", exit_code: int = 0, timed_out: bool = False
) -> ExecResult:
    return ExecResult(exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out)


def _run(tool: Tool, args: dict[str, Any]) -> ToolOutcome:
    """驱动 handler 并收窄返回值类型（handler 的静态类型是 str | ToolOutcome）。"""
    outcome = asyncio.run(tool.handler(args))
    assert isinstance(outcome, ToolOutcome)
    return outcome


def test_command_goes_through_executor() -> None:
    fake = _RecordingExecutor(_result(stdout="hi\n"))
    outcome = _run(bash_tool(fake), {"command": "echo hi"})
    assert outcome.ok is True
    assert outcome.content == "退出码 0\nhi"
    assert fake.calls == [("echo hi", Path.cwd(), float(DEFAULT_TIMEOUT))]


def test_nonzero_exit_is_failure_outcome() -> None:
    fake = _RecordingExecutor(_result(stdout="boom", exit_code=1))
    outcome = _run(bash_tool(fake), {"command": "false"})
    assert outcome.ok is False
    assert "退出码 1" in outcome.content


def test_stderr_has_its_own_section() -> None:
    fake = _RecordingExecutor(_result(stdout="out", stderr="err", exit_code=2))
    outcome = _run(bash_tool(fake), {"command": "x"})
    assert "out" in outcome.content
    assert "[stderr]\nerr" in outcome.content


def test_timeout_message_and_failure() -> None:
    fake = _RecordingExecutor(_result(stdout="前半", timed_out=True))
    outcome = _run(bash_tool(fake), {"command": "sleep", "timeout": 5})
    assert outcome.ok is False
    assert "命令超过 5 秒未结束，已终止整个进程组。" in outcome.content
    assert fake.calls[0][2] == 5.0


def test_timeout_is_clamped_to_maximum() -> None:
    fake = _RecordingExecutor(_result())
    _run(bash_tool(fake), {"command": "x", "timeout": 10**9})
    assert fake.calls[0][2] == float(MAX_TIMEOUT)


def test_missing_command_raises() -> None:
    fake = _RecordingExecutor(_result())
    with pytest.raises(ToolError):
        _run(bash_tool(fake), {})


def test_malformed_timeout_raises() -> None:
    fake = _RecordingExecutor(_result())
    with pytest.raises(ToolError) as excinfo:
        _run(bash_tool(fake), {"command": "x", "timeout": "abc"})
    assert "整数" in str(excinfo.value)


def test_long_output_truncated_with_full_text_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """超长输出：保留头尾 + 省略量说明 + 全文写入临时文件（SPEC §D）。"""
    art_dir = tmp_path / "artifacts"
    monkeypatch.setattr("codelotte.tools.base.ARTIFACT_DIR", art_dir)
    head, tail = "H" * 40_000, "T" * 40_000
    fake = _RecordingExecutor(_result(stdout=head + tail))
    outcome = _run(bash_tool(fake), {"command": "big"})
    assert len(outcome.content) < 30_000
    assert outcome.content.startswith("退出码 0\n" + "H" * 100)
    assert "中间省略" in outcome.content
    assert outcome.content.endswith("T" * 100)
    (artifact,) = art_dir.iterdir()
    assert artifact.read_text(encoding="utf-8") == "退出码 0\n" + head + tail
    assert str(artifact) in outcome.content  # 去向写进了结果文本，模型可 read


def test_real_executor_roundtrip() -> None:
    """接真实本地执行器跑一条命令（SPEC §K：测试走本地实现）。"""
    tool = bash_tool(LocalExecutor())
    py = f'"{sys.executable}"'
    outcome = _run(tool, {"command": f'{py} -c "import sys; sys.exit(3)"'})
    assert outcome.ok is False
    assert "退出码 3" in outcome.content
