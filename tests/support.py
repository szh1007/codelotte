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
    input_text: str | None = None,
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
        input=input_text,
    )


def write_user_config(
    home: Path,
    *,
    model: str | None = "deepseek-flash",
    base_url: str | None = None,
    session_dir: Path | None = None,
    api_key: str | None = "test-key",
    show_reasoning: bool | None = None,
    extra_settings: dict[str, object] | None = None,
) -> Path:
    """把"用户级配置"落成一个临时 home 里的真实文件（没有了环境变量来源，测试也走文件）。"""
    import json

    directory = home / ".codelotte"
    directory.mkdir(parents=True, exist_ok=True)
    settings: dict[str, object] = {}
    if model is not None:
        settings["model"] = model
    if base_url is not None:
        settings["baseUrl"] = base_url
    if session_dir is not None:
        settings["sessionDir"] = str(session_dir)
    if show_reasoning is not None:
        settings["showReasoning"] = show_reasoning
    if extra_settings:
        settings.update(extra_settings)
    (directory / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False), encoding="utf-8"
    )
    if api_key is not None:
        (directory / "models.json").write_text(
            json.dumps({"providers": {"deepseek": {"apiKey": api_key}}}), encoding="utf-8"
        )
    return home


def home_env(home: Path, **extra: str) -> dict[str, str]:
    """子进程环境：把"系统用户根目录"指到临时目录（Path.home() 读 USERPROFILE/HOME）。"""
    return child_env(USERPROFILE=str(home), HOME=str(home), **extra)
