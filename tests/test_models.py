"""用户级 models.json（models.py）：运行参数唯一来源 + 随包默认值/上限 + 校验报错。

规则（2026-10-17 定稿）：id 必须在随包目录已适配；contextWindow/maxTokens 可省、
写了必须 ≤ 随包默认值；name 用户优先；reasoning_effort 可省（随包默认 high），
none 关闭思考、其余档位开启并控制强度；多写的字段一律忽略。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codelotte.config import ConfigError, Settings
from codelotte.cost import load_catalog
from codelotte.models import resolve
from tests.support import write_user_config


def _spec(
    home: Path, *, provider: str | None = "deepseek", model: str | None = "deepseek-flash"
):
    """按 settings 的选择（defaultProvider/defaultModel）解析出最终参数。"""
    return resolve(
        Settings(default_provider=provider, default_model=model), load_catalog(), home=home
    )


def test_resolve_joins_user_file_with_packaged_defaults(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home")
    spec = _spec(home)
    assert spec.id == "deepseek-flash"
    assert spec.name == "DeepSeek Flash"  # 没写 name：用随包默认展示名
    assert spec.context_window == 1_048_576  # 随包默认值（官方上限）
    assert spec.max_output_tokens == 393_216
    assert spec.reasoning_effort == "high"  # 没写：用随包默认档（思考开启）
    assert spec.base_url == "https://api.deepseek.com"
    assert spec.api_key == "test-key"


def test_user_overrides_name_and_sizes(tmp_path: Path) -> None:
    home = write_user_config(
        tmp_path / "home",
        name="我的 Flash",
        context_window=500_000,  # 下调 OK
        max_tokens=8_192,
        reasoning_effort="none",  # 关闭思考（直接进请求体）
    )
    spec = _spec(home)
    assert spec.name == "我的 Flash"  # 用户优先
    assert spec.context_window == 500_000
    assert spec.max_output_tokens == 8_192
    assert spec.reasoning_effort == "none"


def test_sizes_above_packaged_defaults_are_rejected(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home", context_window=1_048_577)
    with pytest.raises(ConfigError, match="contextWindow=1048577 超过上限 1048576"):
        _spec(home)
    home = write_user_config(tmp_path / "home2", max_tokens=393_217)
    with pytest.raises(ConfigError, match="maxTokens=393217 超过上限 393216"):
        _spec(home)


def test_unadapted_model_id_is_rejected(tmp_path: Path) -> None:
    """只允许随包目录里已适配的模型——没适配过的模型配了也不给用。"""
    home = write_user_config(tmp_path / "home", model="gpt-9", default_model="gpt-9")
    with pytest.raises(ConfigError, match="未适配的模型 'gpt-9'.*已适配"):
        _spec(home)


def test_missing_file_points_to_the_shape(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="未找到模型参数文件.*providers"):
        _spec(tmp_path / "empty")


def test_missing_defaults_point_to_settings(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home")
    with pytest.raises(ConfigError, match="未配置默认 provider.*defaultProvider"):
        _spec(home, provider=None)
    with pytest.raises(ConfigError, match="未配置默认模型.*defaultModel"):
        _spec(home, model=None)


def test_unknown_provider_and_model_list_options(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home")
    with pytest.raises(ConfigError, match="未知 provider 'other'.*deepseek"):
        _spec(home, provider="other")
    with pytest.raises(ConfigError, match="未知模型 'deepseek-v4-pro'.*deepseek-flash"):
        _spec(home, model="deepseek-v4-pro")  # 随包有、但用户文件没配


def test_provider_requires_base_url_and_key(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home", api_key=None)
    with pytest.raises(ConfigError, match="providers.deepseek 缺少 apiKey"):
        _spec(home)
    home = write_user_config(tmp_path / "home2", base_url=None)
    with pytest.raises(ConfigError, match="缺少 baseUrl（官方端点：https://api.deepseek.com）"):
        _spec(home)


def test_extra_fields_are_ignored(tmp_path: Path) -> None:
    """多写的字段（计费规则、vision 等）一律忽略——钱的事以随包文件为准。"""
    home = tmp_path / "home"
    directory = home / ".codelotte"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(
        json.dumps({"defaultProvider": "deepseek", "defaultModel": "deepseek-flash"}),
        encoding="utf-8",
    )
    (directory / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "baseUrl": "https://proxy.example",
                        "apiKey": "sk-x",
                        "currency": "USD",  # 计费字段：忽略
                        "offPeakMultiplier": 0.01,  # 忽略
                        "models": [
                            {
                                "id": "deepseek-flash",
                                "peakPricePerMillion": {"inputCacheHit": 999},  # 忽略
                                "vision": False,  # 忽略
                            }
                        ],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    spec = _spec(home)
    assert spec.base_url == "https://proxy.example"  # 用户文件里的端点生效
    assert spec.name == "DeepSeek Flash"
    assert load_catalog().off_peak_multiplier == 0.5  # 随包价目 / 规则不受用户文件影响


@pytest.mark.parametrize("value", [0, -5, True, 1.5, "100"])
def test_bad_size_values_are_rejected(tmp_path: Path, value: object) -> None:
    """上限字段只收正整数：bool/float/字符串/0/负数都不行（True 是 int 的子类，单独拦）。"""
    home = write_user_config(tmp_path / "home", context_window=value)  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="contextWindow 要正整数"):
        _spec(home)


def test_empty_name_is_rejected(tmp_path: Path) -> None:
    home = write_user_config(tmp_path / "home", name="")
    with pytest.raises(ConfigError, match="name 要是非空字符串"):
        _spec(home)


def test_bad_shapes_report_readably(tmp_path: Path) -> None:
    home = tmp_path / "home"
    directory = home / ".codelotte"
    directory.mkdir(parents=True)
    (directory / "models.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是合法 JSON"):
        _spec(home)
    (directory / "models.json").write_text('{"providers": {}}', encoding="utf-8")
    with pytest.raises(ConfigError, match="缺少 providers"):
        _spec(home)
    (directory / "models.json").write_text(
        '{"providers": {"deepseek": {"baseUrl": "u", "apiKey": "k", "models": [{"id": "deepseek-flash",'
        ' "contextWindow": "big"}]}}}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="contextWindow 要正整数"):
        _spec(home)
    (directory / "models.json").write_text(
        '{"providers": {"deepseek": {"baseUrl": "u", "apiKey": "k", "models": [{"id": "deepseek-flash",'
        ' "reasoning_effort": "very-high"}]}}}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="reasoning_effort 要是 none/minimal/low/medium/high/xhigh/max/ultra"):
        _spec(home)
    (directory / "models.json").write_text(
        '{"providers": {"deepseek": {"baseUrl": "u", "apiKey": "k", "models": []}}}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="models 不能为空"):
        _spec(home)


def test_legacy_reasoning_key_points_to_the_rename(tmp_path: Path) -> None:
    """旧键 reasoning（boolean 展示开关）直接报改名错误——静默忽略会让写了 false
    自以为关了思考的人继续白花 token（2026-10-17 的用户反馈）。"""
    home = tmp_path / "home"
    directory = home / ".codelotte"
    directory.mkdir(parents=True)
    (directory / "models.json").write_text(
        '{"providers": {"deepseek": {"baseUrl": "u", "apiKey": "k", "models": [{"id": "deepseek-flash",'
        ' "reasoning": false}]}}}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="reasoning 已改名 reasoning_effort"):
        _spec(home)


def test_all_providers_are_validated_even_unselected(tmp_path: Path) -> None:
    """配置文件整体校验：配置错误要响，哪怕坏的那个 provider 没被选中。"""
    home = tmp_path / "home"
    directory = home / ".codelotte"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(
        json.dumps({"defaultProvider": "deepseek", "defaultModel": "deepseek-flash"}),
        encoding="utf-8",
    )
    (directory / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "deepseek": {
                        "baseUrl": "u",
                        "apiKey": "k",
                        "models": [{"id": "deepseek-flash"}],
                    },
                    "other": {"baseUrl": "u2", "models": [{"id": "deepseek-flash"}]},  # 缺 apiKey
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="providers.other 缺少 apiKey"):
        _spec(home)
