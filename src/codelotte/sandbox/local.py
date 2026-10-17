"""本地执行器：直接在宿主机跑命令（SPEC §H 里 --no-sandbox 的默认形态）。

超时处理的两条纪律：
- 杀的是整个进程组/进程树——shell 往往只是父进程，只杀单个 pid 会留下孤儿进程；
- 先竞速等待、超时后杀，再回收已缓冲的输出（不是直接取消读取，否则输出全丢）。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from codelotte.sandbox.executor import ExecResult, decode_output

_DRAIN_TIMEOUT = 10.0  # 杀死后回收残余输出的兜底时限


def _find_git_bash() -> str | None:
    """找 Git Bash：Windows 上的首选 shell（工具名叫 bash，模型也按 bash 语法写命令）。

    System32\\bash.exe 是 WSL 的启动器——路径体系完全不同（没有 /d 这种盘符映射），排除。
    """
    path = shutil.which("bash")
    if path is None or "system32" in path.lower():
        return None
    return path


class LocalExecutor:
    """在宿主机上跑命令。POSIX 用 /bin/sh -c；Windows 优先 Git Bash（工具名叫 bash，
    模型按 bash 语法写命令——`;`、`cd /d/...` 这些 cmd 会误解），找不到才退回 cmd.exe /c。"""

    env = "local"

    async def close(self) -> None:
        """本地执行器没有长驻资源；接口要求有 close（Docker 版在这里清理容器）。"""

    async def run(self, command: str, *, cwd: Path, timeout: float) -> ExecResult:
        proc = await self._create_process(command, cwd)
        # 用 asyncio.wait 竞速而不是 wait_for：超时只放弃等待、不取消读取任务，
        # 这样杀完进程还能把已缓冲的输出读回来（wait_for 取消 communicate 会丢输出）
        drain = asyncio.ensure_future(proc.communicate())
        try:
            done, _pending = await asyncio.wait({drain}, timeout=timeout)
            timed_out = drain not in done
            if timed_out:
                await self._kill_process_tree(proc)
                try:
                    out, err = await asyncio.wait_for(drain, _DRAIN_TIMEOUT)
                except (TimeoutError, ValueError, RuntimeError):
                    # 进程树里有漏网进程攥着管道：放弃残余输出，超时事实不变
                    out, err = b"", b""
            else:
                out, err = drain.result()
        finally:
            # 正常路径子进程已退出（kill 提前返回）；取消路径（run 中断）也在这里收回
            # 子进程——不这么做，Ctrl+C 之后命令会作为孤儿继续跑
            drain.cancel()
            await self._kill_process_tree(proc)
        return ExecResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=decode_output(out),
            stderr=decode_output(err),
            timed_out=timed_out,
        )

    async def _create_process(self, command: str, cwd: Path) -> asyncio.subprocess.Process:
        """起进程：Windows 上找得到 Git Bash 就用它跑（bash -c），否则退回系统 shell。"""
        common: dict[str, Any] = {
            "cwd": cwd,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            **self._spawn_kwargs(),
        }
        bash = _find_git_bash() if sys.platform == "win32" else None
        if bash is not None:
            return await asyncio.create_subprocess_exec(bash, "-c", command, **common)
        return await asyncio.create_subprocess_shell(command, **common)

    @staticmethod
    def _spawn_kwargs() -> dict[str, Any]:
        if sys.platform == "win32":
            return {}  # Windows 无进程组语义：进程树用 taskkill /T 杀（见下）
        return {"start_new_session": True}  # 自成会话 → killpg 能杀掉整组子进程

    @staticmethod
    async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
        """杀掉整个进程组/进程树：shell 只是父进程，只杀它会留下孤儿。"""
        if proc.returncode is not None:
            return
        if sys.platform == "win32":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/F",
                "/T",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()  # 组杀失败：至少杀掉 shell 本身
        try:
            await asyncio.wait_for(proc.wait(), _DRAIN_TIMEOUT)
        except TimeoutError:
            proc.kill()
