"""环境与配置读取：密钥只从环境变量来（绝不进配置文件/仓库）。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
API_KEY_ENV = "DEEPSEEK_API_KEY"


class ConfigError(Exception):
    """配置缺失或无效。"""


def _env(source: Mapping[str, str] | None) -> Mapping[str, str]:
    return source if source is not None else os.environ


def get_api_key(env: Mapping[str, str] | None = None) -> str:
    key = _env(env).get(API_KEY_ENV, "").strip()
    if not key:
        raise ConfigError(
            f"未找到环境变量 {API_KEY_ENV}（密钥只从环境变量读取）。"
            '用法参考 .env.example：`uv run --env-file .env codelotte -p "..."`，'
            "或在 shell 中先 export。"
        )
    return key


def get_base_url(env: Mapping[str, str] | None = None) -> str:
    return _env(env).get("CODELOTTE_BASE_URL", "").strip() or DEFAULT_BASE_URL


def get_model(env: Mapping[str, str] | None = None) -> str:
    return _env(env).get("CODELOTTE_MODEL", "").strip() or DEFAULT_MODEL


def get_session_dir(env: Mapping[str, str] | None = None) -> Path | None:
    raw = _env(env).get("CODELOTTE_SESSION_DIR", "").strip()
    return Path(raw) if raw else None
