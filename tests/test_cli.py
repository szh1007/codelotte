"""CLI 入口的冒烟测试（票据 01/02 验收项）。

测试缝在"进程边界"——以子进程方式运行真实 CLI，只验证外部可观察行为。
子进程强制 PYTHONUTF8=1（UTF-8 模式），父进程按 UTF-8 解码，
避免 Windows ANSI 代码页（cp936）与 UTF-8 解码错位导致的假失败。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import codelotte

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30


def child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONUTF8": "1"}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codelotte", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=child_env(),
        cwd=PROJECT_ROOT,
    )


def test_version_flag_prints_version_and_exits_zero() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_no_args_without_a_real_terminal_fails_readably(tmp_path: Path) -> None:
    """无参数 = 进 TUI（票据 05）：管道/CI 里没有真实终端时给可读错误，不往 stdout 喷转义码。"""
    env = {
        **child_env(),
        "DEEPSEEK_API_KEY": "test-key",
        "CODELOTTE_HOME": str(tmp_path / "home"),
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "codelotte"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2
    assert "真实终端" in result.stderr
    assert "Traceback" not in result.stderr
    assert "\x1b[" not in result.stdout  # 没把全屏转义码喷进管道


def test_continue_without_any_session_fails_readably(tmp_path: Path) -> None:
    env = {
        **child_env(),
        "DEEPSEEK_API_KEY": "test-key",
        "CODELOTTE_HOME": str(tmp_path / "home"),
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi", "--continue"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "没有可继续的会话" in result.stderr
    assert "Traceback" not in result.stderr


def test_continue_flags_parse() -> None:
    from codelotte.cli import build_parser

    assert build_parser().parse_args(["--continue"]).continue_ is True
    assert build_parser().parse_args(["-c"]).continue_ is True
    assert build_parser().parse_args([]).continue_ is False


def test_console_script_entry_point_works() -> None:
    script = shutil.which("codelotte")
    assert script is not None, "console script 不在 PATH 上——请通过 `uv run pytest` 运行测试"
    result = subprocess.run(
        [script, "--version"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=child_env(),
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_config_error_leaves_no_session_file(tmp_path: Path) -> None:
    """回归（审查发现）：没密钥的启动不得留下"只有会话头"的空会话文件——
    否则 --continue 按 mtime 会挑中它，真实历史被跳过。"""
    env = {k: v for k, v in child_env().items() if k != "DEEPSEEK_API_KEY"}
    env["CODELOTTE_HOME"] = str(tmp_path / "home")
    env["CODELOTTE_SESSION_DIR"] = str(tmp_path / "sessions")
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    sessions = tmp_path / "sessions"
    assert not (sessions.exists() and list(sessions.rglob("*.jsonl")))


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == codelotte.__version__


def test_missing_api_key_fails_with_readable_error(tmp_path: Path) -> None:
    env = {k: v for k, v in child_env().items() if k != "DEEPSEEK_API_KEY"}
    env["CODELOTTE_HOME"] = str(tmp_path / "home")  # 隔离用户级 .env
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,  # 空目录：不加载项目级 .env
    )
    assert result.returncode == 2
    assert "DEEPSEEK_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr
