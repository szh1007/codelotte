"""CLI 入口的冒烟测试（票据 01 验收项）。

TDD 说明：这些测试先行于实现编写。测试缝在"进程边界"——
以子进程方式运行真实的 `python -m codelotte`，验证外部可观察行为。
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import codelotte

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codelotte", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
    )


def test_version_flag_prints_version_and_exits_zero() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == codelotte.__version__
