"""环境与配置读取：密钥只从环境变量或 .env 文件；启动时自动加载 .env 文件层。"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
API_KEY_ENV = "DEEPSEEK_API_KEY"
HOME_ENV = "CODELOTTE_HOME"
ENV_FILE_NAME = ".env"
USER_ENV_DIR = ".codelotte"


class ConfigError(Exception):
    """配置缺失或无效。"""


def _env(source: Mapping[str, str] | None) -> Mapping[str, str]:
    return source if source is not None else os.environ


def get_api_key(env: Mapping[str, str] | None = None) -> str:
    key = _env(env).get(API_KEY_ENV, "").strip()
    if not key:
        raise ConfigError(
            f"未找到环境变量 {API_KEY_ENV}（密钥只从环境变量或 .env 读取）。"
            "启动时会自动加载 ~/.codelotte/.env 与当前目录 .env（模板见 .env.example），"
            "也可在 shell 中 export。"
        )
    return key


def get_base_url(env: Mapping[str, str] | None = None) -> str:
    return _env(env).get("CODELOTTE_BASE_URL", "").strip() or DEFAULT_BASE_URL


def get_model(env: Mapping[str, str] | None = None) -> str:
    return _env(env).get("CODELOTTE_MODEL", "").strip() or DEFAULT_MODEL


def get_session_dir(env: Mapping[str, str] | None = None) -> Path | None:
    raw = _env(env).get("CODELOTTE_SESSION_DIR", "").strip()
    return Path(raw) if raw else None


def get_home_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """CODELOTTE_HOME 覆盖用户级目录的位置（测试隔离用；只从真实环境读取）。"""
    raw = _env(env).get(HOME_ENV, "").strip()
    return Path(raw) if raw else None


def parse_env_text(text: str) -> dict[str, str]:
    """最小 .env 解析：KEY=VALUE、# 注释、可选单双引号、可选 export 前缀；不做变量插值。"""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def load_env_files(
    *,
    cwd: Path | None = None,
    home: Path | None = None,
    env: MutableMapping[str, str] | None = None,
) -> list[Path]:
    """自动加载 .env 文件层：用户级 ~/.codelotte/.env → 项目级 ./.env（后者覆盖前者）。

    已存在的环境变量永不覆盖（命令行/CI 的显式设置为准）。返回实际读取的文件路径。
    """
    target = env if env is not None else os.environ
    base = cwd if cwd is not None else Path.cwd()
    home_dir = home if home is not None else Path.home()
    candidates = [home_dir / USER_ENV_DIR / ENV_FILE_NAME, base / ENV_FILE_NAME]
    loaded: list[Path] = []
    merged: dict[str, str] = {}
    for path in candidates:
        if not path.is_file():
            continue
        try:
            merged.update(parse_env_text(path.read_text(encoding="utf-8")))
        except OSError:
            continue
        loaded.append(path)
    for key, value in merged.items():
        if key not in target:
            target[key] = value
    return loaded
