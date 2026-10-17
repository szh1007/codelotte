"""Docker 执行器（票据 10 / SPEC §H）：每会话一个长驻容器，命令用 `docker exec` 复用。

隔离承诺（参数即契约，改动等于改安全边界）：
- **只挂工作区**：宿主家目录、`.ssh`、`.env` 不在任何挂载里；根文件系统 `--read-only`，
  唯一可写挂载是工作区（`/workspace`），临时文件只进 256MB 的 tmpfs `/tmp`。
- **网络默认拒绝**：`--network none`。被拦的网络错误带一句明确说明回传模型
  （否则模型只会看到 "Network is unreachable" 却不知道是沙箱）。
- **限额**：内存（memory-swap 同值，禁 swap 超卖）、CPU、PID 数；单命令超时在容器内由
  `timeout --signal=KILL` 杀整个进程组——只杀宿主侧的 `docker exec` 客户端，
  容器里的孙进程会活下来（Docker 的已知行为），所以超时哨兵必须放在容器里。

生命周期：第一次 `run` 惰性启动容器（`sleep infinity` 作主进程），后续命令复用；
会话结束时调用方 `close()` → `docker rm -f`。`--rm` + 标签 `codelotte.sandbox=true`
保证即使进程崩了，遗留容器也能被找到并清掉。工作目录在会话内固定（bash 工具总是传
进程 cwd），换目录直接报错而不是悄悄挂错盘。
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from pathlib import Path

from codelotte.sandbox.executor import ExecResult, decode_output

DEFAULT_IMAGE = "python:3.13-slim"  # 自带 bash + python + timeout；需预先 docker pull
CONTAINER_WORKDIR = "/workspace"
DEFAULT_MEMORY = "1g"
DEFAULT_CPUS = 1.0
DEFAULT_PIDS_LIMIT = 256

_LIFECYCLE_TIMEOUT = 60.0  # docker run / rm 的兜底时限
_HOST_TIMEOUT_GRACE = 10.0  # 容器内 timeout 已到点，宿主侧再等这么久才强制收尸
_DRAIN_TIMEOUT = 10.0
_HOST_FALLBACK_NOTE = (
    "[codelotte] 容器内的超时哨兵没有按时返回，已停止并回收沙箱容器；"
    "下一条命令会启动新容器（/tmp 中的临时文件已丢失）。"
)

# 容器在 --network none 下常见的网络失败文本（Python urllib、curl、apt 的措辞）。
_NETWORK_DENIED = re.compile(
    r"network is unreachable|temporary failure in name resolution|could not resolve host|"
    r"name or service not known|failed to establish a new connection|getaddrinfo failed",
    re.IGNORECASE,
)
_NETWORK_NOTE = (
    "[codelotte] 网络访问被沙箱拒绝（容器以 --network none 启动）。"
    "如确需联网，请用 --no-sandbox 重新启动。"
)


def _network_denial_note(stdout: str, stderr: str, exit_code: int) -> str | None:
    """把"网络被沙箱挡住"翻译成模型能理解的一句话；成功退出或无网络迹象时不动。"""
    if exit_code == 0 or not _NETWORK_DENIED.search(f"{stdout}\n{stderr}"):
        return None
    return _NETWORK_NOTE


def _is_timeout(exit_code: int, elapsed: float, timeout: float) -> bool:
    """容器内 timeout 的退出码判定：正常是 124；KILL 模式下 timeout 自己也在被杀
    的进程组里，docker exec 实际返回 137（2026-10-17 集成测试实测）。

    两种退出码都必须"已到点"才算超时：不到点的 124 是命令自己选的退出码，不到点的
    137 是 OOM/外部杀——都不能误报成沙箱超时。"""
    return exit_code in (124, 137) and elapsed >= timeout


class DockerExecutor:
    """在长驻 Docker 容器里执行命令。构造不碰 Docker（daemon 没起也能 --version/列会话）。"""

    env = "docker"

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        memory: str = DEFAULT_MEMORY,
        cpus: float = DEFAULT_CPUS,
        pids_limit: int = DEFAULT_PIDS_LIMIT,
        name: str | None = None,
    ) -> None:
        self._image = image
        self._memory = memory
        self._cpus = cpus
        self._pids_limit = pids_limit
        self._name = name or f"codelotte-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._workspace: Path | None = None
        self._started = False
        self._start_attempted = False

    def _start_args(self, cwd: Path) -> list[str]:
        mount = f"{cwd.resolve()}:{CONTAINER_WORKDIR}"
        return [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self._name,
            "--label",
            "codelotte.sandbox=true",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,size=256m",
            "-e",
            "HOME=/tmp",  # 家目录指向容器内临时目录：工具写 HOME 不碰只读根
            "-w",
            CONTAINER_WORKDIR,
            "-v",
            mount,
            "--memory",
            self._memory,
            "--memory-swap",
            self._memory,  # 不给 swap 留超卖空间
            "--cpus",
            str(self._cpus),
            "--pids-limit",
            str(self._pids_limit),
            self._image,
            "sleep",
            "infinity",
        ]

    def _exec_args(self, command: str, timeout: float) -> list[str]:
        return [
            "docker",
            "exec",
            "-w",
            CONTAINER_WORKDIR,
            self._name,
            "timeout",
            "--signal=KILL",
            f"{timeout:g}",
            "bash",
            "-c",
            command,
        ]

    async def run(self, command: str, *, cwd: Path, timeout: float) -> ExecResult:
        await self._ensure_started(cwd)
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *self._exec_args(command, timeout),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        drain = asyncio.ensure_future(proc.communicate())
        timed_out = False
        host_fallback = False
        try:
            done, _pending = await asyncio.wait(
                {drain}, timeout=timeout + _HOST_TIMEOUT_GRACE
            )
            if drain not in done:
                # 兜底路径：容器内的 timeout 没按时返回（daemon 卡住等）。
                # 只杀 docker exec 客户端保证不了容器里的进程树，直接停容器。
                timed_out = True
                host_fallback = True
                proc.kill()
                await self._stop_container()
                try:
                    out, err = await asyncio.wait_for(drain, _DRAIN_TIMEOUT)
                except (TimeoutError, ValueError, RuntimeError):
                    out, err = b"", b""
            else:
                out, err = drain.result()
        finally:
            drain.cancel()
            if proc.returncode is None:
                proc.kill()
                try:
                    await proc.wait()
                except OSError:
                    pass
        exit_code = proc.returncode if proc.returncode is not None else -1
        elapsed = time.monotonic() - started
        stdout = decode_output(out)
        stderr = decode_output(err)
        if host_fallback:
            stderr = f"{stderr}\n{_HOST_FALLBACK_NOTE}" if stderr else _HOST_FALLBACK_NOTE
        elif not timed_out and _is_timeout(exit_code, elapsed, timeout):
            timed_out = True
        if not timed_out:
            note = _network_denial_note(stdout, stderr, exit_code)
            if note is not None:
                stderr = f"{stderr}\n{note}" if stderr else note
        return ExecResult(
            exit_code=exit_code, stdout=stdout, stderr=stderr, timed_out=timed_out
        )

    async def close(self) -> None:
        """会话结束清理容器；清理失败不抛（`--rm` 与标签是最后兜底）。"""
        await self._stop_container()

    async def _ensure_started(self, cwd: Path) -> None:
        workspace = cwd.resolve()
        if self._started:
            if self._workspace != workspace:
                raise OSError(
                    f"Docker 沙箱的工作目录在会话内固定为 {self._workspace}，不能切换：{workspace}"
                )
            return
        self._start_attempted = True
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._start_args(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise OSError(
                "找不到 docker 命令——请安装并启动 Docker Desktop，"
                "或用 --no-sandbox 在宿主机执行"
            ) from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), _LIFECYCLE_TIMEOUT)
        except TimeoutError:
            proc.kill()
            raise OSError("启动 Docker 沙箱超时（docker run 没有返回）") from None
        if proc.returncode != 0:
            detail = decode_output(err).strip() or decode_output(out).strip()
            raise OSError(
                f"启动 Docker 沙箱失败：{detail}。请确认 Docker daemon 已启动、"
                f"镜像 {self._image} 可用（docker pull {self._image}）；"
                "或用 --no-sandbox 在宿主机执行"
            )
        self._workspace = workspace
        self._started = True

    async def _stop_container(self) -> None:
        self._started = False
        self._workspace = None
        if not self._start_attempted:
            return
        self._start_attempted = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                self._name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            return
        try:
            await asyncio.wait_for(proc.wait(), _LIFECYCLE_TIMEOUT)
        except TimeoutError:
            proc.kill()
