"""Docker 沙箱集成套件（票据 10）：真容器、真隔离、真限额。

独立套件、可选执行（SPEC §K）：默认 `pytest` 通过 marker 排除（见 pyproject 的 addopts），
要跑时用 `uv run pytest -m docker`；没有 Docker daemon 或镜像时整组跳过，不阻塞冒烟。
运行前：启动 Docker Desktop，并 `docker pull python:3.13-slim`（或用环境变量
CODELOTTE_TEST_DOCKER_IMAGE 指定已有镜像）。

这些测试故意不 mock Docker：要证明的正是"宿主文件看不见、网络出不去、超时杀得掉"。
"""

from __future__ import annotations

import asyncio
import functools
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from codelotte.sandbox.docker import DEFAULT_CPUS, DEFAULT_IMAGE, DEFAULT_MEMORY, DockerExecutor
from codelotte.sandbox.executor import ExecResult

IMAGE = os.environ.get("CODELOTTE_TEST_DOCKER_IMAGE", DEFAULT_IMAGE)

pytestmark = pytest.mark.docker


@functools.lru_cache(maxsize=1)
def _docker_available() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


@functools.lru_cache(maxsize=1)
def _image_available() -> bool:
    proc = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30, check=False
    )
    return proc.returncode == 0


@pytest.fixture(autouse=True, scope="module")
def _require_docker() -> None:
    """惰性闸门：只有真的选中 docker 组时才探测 daemon（默认冒烟不付这 20 秒）。"""
    if not _docker_available():
        pytest.skip("本机没有可用的 Docker daemon（独立套件，可选执行；不阻塞冒烟）")


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


def _executor(
    *, memory: str = DEFAULT_MEMORY, cpus: float = DEFAULT_CPUS
) -> DockerExecutor:
    """新建一个隔离的执行器；镜像缺失时给出可操作的跳过原因。"""
    if not _image_available():
        pytest.skip(
            f"本机没有镜像 {IMAGE}（先 docker pull {IMAGE}，"
            "或用 CODELOTTE_TEST_DOCKER_IMAGE 指定）"
        )
    return DockerExecutor(
        name=f"codelotte-test-{uuid.uuid4().hex[:8]}",
        image=IMAGE,
        memory=memory,
        cpus=cpus,
    )


@pytest.fixture()
def executor() -> Iterator[DockerExecutor]:
    ex = _executor()
    yield ex
    asyncio.run(ex.close())


def _run(executor: DockerExecutor, command: str, cwd: Path, timeout: float = 30.0) -> ExecResult:
    return asyncio.run(executor.run(command, cwd=cwd, timeout=timeout))


def _inspect(name: str, template: str) -> str:
    proc = subprocess.run(
        ["docker", "inspect", "--format", template, name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_workspace_is_mounted_read_write(executor: DockerExecutor, workspace: Path) -> None:
    (workspace / "from-host.txt").write_text("宿主写的\n", encoding="utf-8")
    seen = _run(executor, "cat from-host.txt", workspace)
    assert seen.exit_code == 0, seen.stderr
    assert "宿主写的" in seen.stdout

    written = _run(executor, "echo 容器写的 > made-by-container.txt", workspace)
    assert written.exit_code == 0, written.stderr
    assert (workspace / "made-by-container.txt").read_text(encoding="utf-8").strip() == "容器写的"


def test_container_is_reused_between_commands(executor: DockerExecutor, workspace: Path) -> None:
    """容器生命周期 = 会话生命周期：第二条命令看到第一条的 /tmp 残留即证明复用。"""
    _run(executor, "echo keep > /tmp/reuse-marker", workspace)
    second = _run(executor, "cat /tmp/reuse-marker", workspace)
    assert second.exit_code == 0, second.stderr
    assert second.stdout.strip() == "keep"


def test_host_home_and_dotenv_are_not_visible(
    executor: DockerExecutor, workspace: Path, tmp_path: Path
) -> None:
    """验收：宿主家目录、.ssh、.env 在容器里不可见（工作区是唯一挂载）。

    证明方式：在宿主家目录放一个唯一标记，再在容器内全盘搜索这个标记——找不到才说明
    家目录没有以任何形式进入容器（只查 /root 是空壳断言：Docker 根本没把宿主家目录
    映射到 /root）。
    """
    marker = "CODELOTTE-HOST-SECRET-7f3a"
    host_home = tmp_path / "host-home"
    (host_home / ".ssh").mkdir(parents=True)
    (host_home / ".ssh" / "id_rsa").write_text(marker, encoding="utf-8")
    (host_home / ".env").write_text(f"HOST_SECRET={marker}\n", encoding="utf-8")

    result = _run(
        executor,
        "echo HOME=$HOME; "
        "grep -rl CODELOTTE-HOST-SECRET-7f3a / "
        "--exclude-dir=proc --exclude-dir=sys --exclude-dir=dev 2>/dev/null || true",
        workspace,
    )
    assert result.exit_code == 0, result.stderr
    assert "HOME=/tmp" in result.stdout  # 家目录指向容器内临时目录，不是宿主家目录
    assert marker not in result.stdout  # 宿主家目录的 .ssh/.env 没有进入容器


def test_network_is_denied_with_a_clear_note(
    executor: DockerExecutor, workspace: Path
) -> None:
    # 用 bash 的 /dev/tcp 发起连接：不依赖镜像里有没有 curl/python（默认镜像与本机备用镜像都适用）
    result = _run(executor, "exec 3<>/dev/tcp/example.com/80", workspace)
    assert result.timed_out is False
    assert result.exit_code != 0  # 连接被拒绝
    assert "网络访问被沙箱拒绝" in result.stderr  # 明确错误回传模型


def test_memory_limit_is_enforced(workspace: Path) -> None:
    executor = _executor(memory="128m")
    try:
        # bash 的 command substitution 会把输出整个留在内存里：300MB > 128m 上限
        result = _run(
            executor,
            "a=$(head -c 300000000 /dev/zero | tr '\\0' x); echo allocated",
            workspace,
        )
        assert result.exit_code != 0
        assert "allocated" not in result.stdout  # 300MB 分配被 128m 上限拦下
    finally:
        asyncio.run(executor.close())


def test_cpu_and_memory_limits_are_configured(workspace: Path) -> None:
    """CPU 份额很难用挂钟稳定观测：直接读容器配置，证明限额真实下发。"""
    limited = _executor(memory="256m", cpus=0.5)
    try:
        result = _run(limited, "true", workspace)
        assert result.exit_code == 0, result.stderr
        configured = _inspect(
            limited._name, "{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}"
        )
        assert configured == "500000000 268435456"
    finally:
        asyncio.run(limited.close())


def test_timeout_kills_the_whole_process_group(
    executor: DockerExecutor, workspace: Path
) -> None:
    """超时在容器内由 timeout 杀整个进程组：后台子进程也必须停，不能留孤儿。"""
    command = "(while true; do echo x >> /tmp/beat; sleep 0.1; done) & sleep 60"
    started = time.perf_counter()
    result = _run(executor, command, workspace, timeout=2.0)
    elapsed = time.perf_counter() - started
    assert result.timed_out is True
    assert elapsed < 30.0  # 没傻等 60 秒

    first = _run(executor, "wc -l < /tmp/beat", workspace)
    assert first.exit_code == 0 and int(first.stdout.strip()) > 0, "后台进程没跑起来——测试前提不成立"
    time.sleep(1.5)
    second = _run(executor, "wc -l < /tmp/beat", workspace)
    assert second.stdout == first.stdout, "后台进程还在心跳——超时没有杀掉整个进程组"


def test_close_removes_the_container(executor: DockerExecutor, workspace: Path) -> None:
    assert _run(executor, "true", workspace).exit_code == 0
    name = executor._name
    asyncio.run(executor.close())
    gone = subprocess.run(
        ["docker", "inspect", name], capture_output=True, timeout=30, check=False
    )
    assert gone.returncode != 0  # 容器已清理
