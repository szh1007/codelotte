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


def test_no_args_prints_help_and_exits_zero() -> None:
    result = run_cli()
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


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


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == codelotte.__version__


def test_missing_api_key_fails_with_readable_error() -> None:
    env = {k: v for k, v in child_env().items() if k != "DEEPSEEK_API_KEY"}
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 2
    assert "DEEPSEEK_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr
