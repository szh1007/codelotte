"""Docker 执行器的纯逻辑测试（票据 10）：加固参数、路径映射、超时与网络拒绝提示。

真容器的行为由独立套件 tests/test_docker_sandbox.py 覆盖（需 Docker daemon，可选执行）。
这里只钉住"发出去的 docker 命令长什么样"——参数一旦被删改，加固承诺就静默失效。

**刻意的测试缝例外**（SPEC §K 的"不测内部实现"）：`--network none`、`--read-only`、
唯一挂载、限额这些加固参数就是安全契约本身；没有 Docker 的冒烟也必须守住它们，
所以直接断言 argv，而不是等只有 CI 才能跑的集成套件。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from codelotte.sandbox.docker import (
    CONTAINER_WORKDIR,
    DEFAULT_IMAGE,
    DockerExecutor,
    _is_timeout,
    _network_denial_note,
)


def test_start_args_deny_network(tmp_path: Path) -> None:
    args = DockerExecutor(name="codelotte-test")._start_args(tmp_path)
    assert args[:3] == ["docker", "run", "-d"]
    assert args[args.index("--network") + 1] == "none"


def test_start_args_make_the_root_filesystem_read_only(tmp_path: Path) -> None:
    args = DockerExecutor(name="codelotte-test")._start_args(tmp_path)
    assert "--read-only" in args
    assert args[args.index("--tmpfs") + 1].startswith("/tmp:")


def test_start_args_tag_and_name_the_container(tmp_path: Path) -> None:
    executor = DockerExecutor(name="codelotte-test")
    args = executor._start_args(tmp_path)
    assert "codelotte.sandbox=true" in args  # 遗留容器可按标签找到
    assert args[args.index("--name") + 1] == "codelotte-test"


def test_start_args_mount_only_the_workspace(tmp_path: Path) -> None:
    """宿主机家目录不单独挂载——容器里只有工作区这一个宿主入口。"""
    args = DockerExecutor(name="codelotte-test")._start_args(tmp_path)
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg in ("-v", "--volume")]
    assert mounts == [f"{tmp_path.resolve()}:{CONTAINER_WORKDIR}"]


def test_start_args_enforce_memory_cpu_and_pid_limits(tmp_path: Path) -> None:
    executor = DockerExecutor(
        name="codelotte-test", memory="256m", cpus=0.5, pids_limit=64
    )
    args = executor._start_args(tmp_path)
    assert args[args.index("--memory") + 1] == "256m"
    assert args[args.index("--memory-swap") + 1] == "256m"  # swap 不许超卖
    assert args[args.index("--cpus") + 1] == "0.5"
    assert args[args.index("--pids-limit") + 1] == "64"


def test_exec_args_run_the_command_under_an_incontainer_timeout() -> None:
    """超时必须由容器内的 timeout 杀进程组：只杀宿主侧的 docker exec 客户端，
    容器里的孙进程会活下来（Docker 的已知行为）。"""
    executor = DockerExecutor(name="codelotte-test")
    args = executor._exec_args("echo hi", 30.0)
    assert args[:3] == ["docker", "exec", "-w"]
    assert args[args.index("-w") + 1] == CONTAINER_WORKDIR
    tail = args[-6:]
    assert tail == ["timeout", "--signal=KILL", "30", "bash", "-c", "echo hi"]


def test_defaults_are_sandbox_first() -> None:
    executor = DockerExecutor()
    assert executor.env == "docker"
    assert DEFAULT_IMAGE == "python:3.13-slim"
    assert DockerExecutor()._name != executor._name  # 每会话独立容器


def test_network_denial_is_translated_into_a_clear_note() -> None:
    note = _network_denial_note(
        "", "urllib.error.URLError: <urlopen error [Errno 101] Network is unreachable>", 1
    )
    assert note is not None
    assert "网络访问被沙箱拒绝" in note
    assert "--no-sandbox" in note


def test_network_note_ignores_success_and_unrelated_failures() -> None:
    assert _network_denial_note("ok", "", 0) is None
    assert _network_denial_note("", "SyntaxError: invalid syntax", 1) is None
    assert _network_denial_note("network is unreachable", "", 0) is None


def test_timeout_exit_codes_are_classified_by_wall_clock() -> None:
    """GNU timeout 在 KILL 模式下自己也随组被杀（实测 docker exec 返回 137）；
    124/137 都必须"已到点"才算超时——不到点的 124 是命令自己的退出码，不到点的
    137 是 OOM/外部杀，都不能误报。"""
    assert _is_timeout(124, 30.5, 30.0) is True
    assert _is_timeout(137, 30.5, 30.0) is True
    assert _is_timeout(124, 0.1, 30.0) is False
    assert _is_timeout(137, 2.0, 30.0) is False
    assert _is_timeout(0, 40.0, 30.0) is False


def test_close_before_start_returns_without_error() -> None:
    """没启动过容器（没用 bash）时 close 不该碰 Docker，也不该抛异常。"""
    executor = DockerExecutor(name="codelotte-test")
    asyncio.run(executor.close())
    assert executor._start_attempted is False
