"""配置读取的单元测试：settings.json 直读、必填项报错指路（无默认、无环境变量来源）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codelotte.config import (
    ConfigError,
    Settings,
    get_api_key,
    get_base_url,
    get_model,
    load_settings,
)


def _write_settings(home: Path, payload: object) -> None:
    (home / ".codelotte").mkdir(parents=True, exist_ok=True)
    (home / ".codelotte" / "settings.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_load_settings_defaults_when_missing(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "empty")
    assert settings.model is None and settings.session_dir is None and settings.notices == []


def test_load_settings_reads_all_known_keys(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_settings(
        home,
        {
            "model": "deepseek-v4-pro",
            "baseUrl": "https://proxy.example",
            "sessionDir": "D:/sessions",
            "showReasoning": True,
            "commandTimeoutSeconds": 30,
            "env": {"HTTPS_PROXY": "http://local-proxy"},  # 旧包层字段：未知键 → 提示忽略
            "unknownKey": 1,
        },
    )
    settings = load_settings(home)
    assert settings.model == "deepseek-v4-pro"
    assert settings.base_url == "https://proxy.example"
    assert settings.session_dir == Path("D:/sessions")
    assert settings.show_reasoning is True
    assert settings.command_timeout == 30
    assert any("unknownKey" in note for note in settings.notices)  # 未知键不静默
    assert any("env" in note for note in settings.notices)


def test_load_settings_fails_loud_on_bad_json_and_bad_types(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "settings.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是合法 JSON"):
        load_settings(home)

    _write_settings(home, {"model": 5})
    with pytest.raises(ConfigError, match="model"):
        load_settings(home)
    _write_settings(home, {"showReasoning": "yes"})
    with pytest.raises(ConfigError, match="showReasoning"):
        load_settings(home)


def test_getters_require_explicit_configuration() -> None:
    """没有内置默认：模型/端点/密钥缺了就报错，并指引配到哪个文件的哪个字段。"""
    with pytest.raises(ConfigError, match="未配置模型.*settings.json"):
        get_model(Settings())
    assert get_model(Settings(model="m")) == "m"

    with pytest.raises(ConfigError, match="端点.*baseUrl"):
        get_base_url(Settings())
    assert get_base_url(Settings(base_url="http://x")) == "http://x"
    assert get_base_url(Settings(), fallback="http://file") == "http://file"  # provider 条目兜底

    with pytest.raises(ConfigError, match="API 密钥.*models.json.*apiKey"):
        get_api_key()
    assert get_api_key(fallback="sk-x") == "sk-x"
