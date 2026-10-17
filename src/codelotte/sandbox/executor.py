"""执行器接口与结果类型（SPEC §A 的 Sandbox 组件）。

命令执行有"本地/沙箱"两种实现：本票落地 LocalExecutor，Docker 版是票据 10。
工具层只依赖本协议、不得直接调用系统 shell——换实现时工具代码零改动。
"""

from __future__ import annotations

import locale
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
    """命令执行器。实现可抛 OSError 表示命令无法启动（shell 缺失、cwd 不存在等）。

    close 回收长驻资源：本地执行器无事可做，Docker 执行器在这里清理容器。
    会话结束时调用方必须关一次（票据 10：容器生命周期跟随会话）。
    """

    env: str

    async def run(self, command: str, *, cwd: Path, timeout: float) -> "ExecResult": ...

    async def close(self) -> None: ...


def decode_output(data: bytes) -> str:
    """命令输出解码：优先 UTF-8；Windows 原生工具（cmd 报错等）按系统 ANSI 代码页输出，
    退一步用 locale.getencoding() 解——它不受 UTF-8 模式影响，正是控制台本地编码。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(locale.getencoding(), errors="replace")
