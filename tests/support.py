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


_SAME = object()  # "跟 provider/model 一致"哨兵；显式传 None = 不写这个键


def write_user_config(
    home: Path,
    *,
    provider: str = "deepseek",
    default_provider: object = _SAME,
    model: str = "deepseek-flash",
    default_model: object = _SAME,
    name: str | None = None,
    context_window: int | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    base_url: str | None = "https://api.deepseek.com",
    api_key: str | None = "test-key",
    settings_extra: dict[str, object] | None = None,
) -> Path:
    """把"用户级配置"落成一个临时 home 里的真实文件（没有了环境变量来源，测试也走文件）。

    - default_provider / default_model 缺省 = 与 provider / model 一致；显式 None = 不写这个键
    - api_key=None 写"没有 apiKey 的 provider"（测报错指路）；base_url 同理
    """
    import json

    directory = home / ".codelotte"
    directory.mkdir(parents=True, exist_ok=True)
    settings: dict[str, object] = {}
    chosen_provider = provider if default_provider is _SAME else default_provider
    chosen_model = model if default_model is _SAME else default_model
    if chosen_provider is not None:
        settings["defaultProvider"] = chosen_provider
    if chosen_model is not None:
        settings["defaultModel"] = chosen_model
    if settings_extra:
        settings.update(settings_extra)
    (directory / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False), encoding="utf-8"
    )
    entry: dict[str, object] = {"id": model}
    if name is not None:
        entry["name"] = name
    if context_window is not None:
        entry["contextWindow"] = context_window
    if max_tokens is not None:
        entry["maxTokens"] = max_tokens
    if reasoning_effort is not None:
        entry["reasoning_effort"] = reasoning_effort
    spec: dict[str, object] = {"models": [entry]}
    if base_url is not None:
        spec["baseUrl"] = base_url
    if api_key is not None:
        spec["apiKey"] = api_key
    (directory / "models.json").write_text(
        json.dumps({"providers": {provider: spec}}, ensure_ascii=False), encoding="utf-8"
    )
    return home


def sessions_dir(home: Path) -> Path:
    """会话目录在用户级目录下固定（settings.json 不再有 sessionDir）。"""
    return home / ".codelotte" / "sessions"


def home_env(home: Path, **extra: str) -> dict[str, str]:
    """子进程环境：把"系统用户根目录"指到临时目录（Path.home() 读 USERPROFILE/HOME）。"""
    return child_env(USERPROFILE=str(home), HOME=str(home), **extra)
