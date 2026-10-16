"""用户级配置文件读取（SPEC §M）：settings.json 与 models.json 就是配置的全部来源。

配置级联：命令行参数（如 `-r`）> `~/.codelotte/settings.json` > `~/.codelotte/models.json`
的 provider 条目。**没有任何内置默认**——模型、密钥、端点都必须显式配置，缺了就直接报错并
指出该去哪个文件的哪个字段补，不替用户猜。

没有任何配置会从项目目录或进程环境加载（.env 文件层、settings 的 env 包层、CODELOTTE_*
环境变量均已移除，2026-10-17）；用户级目录固定为系统用户根目录下的 `.codelotte/`。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

USER_ENV_DIR = ".codelotte"
SETTINGS_FILE_NAME = "settings.json"


class ConfigError(Exception):
    """配置缺失或无效。"""


@dataclass
class Settings:
    """~/.codelotte/settings.json 的内容（每个设置一个顶层字段，直接读取）。

    权限规则不在此（单独 permissions.json）；密钥也不在此（models.json 的 provider 条目）。
    """

    model: str | None = None
    base_url: str | None = None
    session_dir: Path | None = None
    show_reasoning: bool | None = None
    command_timeout: int | None = None
    notices: list[str] = field(default_factory=list)


_KNOWN_SETTINGS = {
    "model": str,
    "baseUrl": str,
    "sessionDir": str,
    "showReasoning": bool,
    "commandTimeoutSeconds": int,
}


def load_settings(home: Path | None = None) -> Settings:
    """读用户级 settings.json：缺失 = 全空（缺什么由取值方报错指路）。

    坏文件/坏类型直接报错（配置错误要响）；未知键忽略并记入 notices（不静默吞）。
    """
    home_dir = home if home is not None else Path.home()
    path = home_dir / USER_ENV_DIR / SETTINGS_FILE_NAME
    if not path.is_file():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise ConfigError(f"设置文件读不动或不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"设置文件顶层应是 JSON 对象：{path}")
    settings = Settings()
    for key, value in raw.items():
        if key not in _KNOWN_SETTINGS:
            settings.notices.append(f"settings.json 有未知键 {key!r}（已忽略）")
            continue
        if key == "model" and isinstance(value, str):
            settings.model = value or None
        elif key == "baseUrl" and isinstance(value, str):
            settings.base_url = value or None
        elif key == "sessionDir" and isinstance(value, str):
            settings.session_dir = Path(value) if value else None
        elif key == "showReasoning" and isinstance(value, bool):
            settings.show_reasoning = value
        elif key == "commandTimeoutSeconds" and isinstance(value, int) and not isinstance(value, bool):
            settings.command_timeout = value
        else:
            expected = _KNOWN_SETTINGS[key].__name__
            raise ConfigError(
                f"settings.json 的 {key!r} 类型不对（应为 {expected}）：{value!r}"
            )
    return settings


def get_model(settings: Settings) -> str:
    """模型必填：settings.json 的 "model"——没配置就报错指路（不替用户挑默认模型）。"""
    if not settings.model:
        raise ConfigError(
            '未配置模型：请在 ~/.codelotte/settings.json 中设置 "model" 字段'
            '（可选值见 ~/.codelotte/models.json 的 providers）'
        )
    return settings.model


def get_base_url(settings: Settings, *, fallback: str | None = None) -> str:
    """端点：settings.baseUrl 优先，其次 provider 条目的 baseUrl（fallback）；都没有则报错。"""
    if settings.base_url:
        return settings.base_url
    if fallback:
        return fallback
    raise ConfigError(
        '未找到 API 端点：请在 ~/.codelotte/settings.json 设置 "baseUrl"，'
        '或在 ~/.codelotte/models.json 的对应 provider 下配置 "baseUrl"'
    )


def get_api_key(*, fallback: str | None = None) -> str:
    """密钥：models.json 的 provider 条目（fallback）；没有则报错指路。"""
    if fallback:
        return fallback
    raise ConfigError(
        '未找到 API 密钥：请在 ~/.codelotte/models.json 的 provider 条目里配置 "apiKey"'
        '（例如 {"providers": {"deepseek": {"apiKey": "sk-…"}}}）'
    )
