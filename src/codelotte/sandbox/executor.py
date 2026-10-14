"""执行器接口与结果类型（SPEC §A 的 Sandbox 组件）。

命令执行有"本地/沙箱"两种实现：本票落地 LocalExecutor，Docker 版是票据 10。
工具层只依赖本协议、不得直接调用系统 shell——换实现时工具代码零改动。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ExecResult:
    """一次命令执行的原始事实（未做任何截断/加工）。

    执行环境（"local"/"docker"）是执行器的属性（Executor.env），不在结果里重复。
    """

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Executor(Protocol):
    """命令执行器。实现可抛 OSError 表示命令无法启动（shell 缺失、cwd 不存在等）。"""

    env: str

    async def run(self, command: str, *, cwd: Path, timeout: float) -> "ExecResult": ...
