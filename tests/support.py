"""测试共享小工具（票据 08 审查修正）：子进程 CLI 调用收在一处。

三个测试模块（test_cli / test_roundtrip / test_export）此前各带一份
child_env/run_cli 拷贝——到这里合一。测试缝保持在"进程边界"：只验证外部可观察行为。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30


def child_env(**extra: str) -> dict[str, str]:
    """子进程环境：强制 UTF-8（Windows 管道默认 GBK 会毁中文输出），叠加 extra。"""
    return {**os.environ, "PYTHONUTF8": "1", **extra}


def run_cli(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """跑一次真实 CLI（子进程）；父进程按 UTF-8 解码，避免代码页错位造成的假失败。"""
    return subprocess.run(
        [sys.executable, "-m", "codelotte", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env if env is not None else child_env(),
        cwd=cwd if cwd is not None else PROJECT_ROOT,
    )
