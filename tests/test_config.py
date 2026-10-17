"""settings.json 的读取与写回：键与 Settings 字段一一对应、坏配置报错、版本号写回。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codelotte.config import (
    ConfigError,
    Settings,
    load_settings,
    record_changelog_version,
)


def _write_settings(home: Path, payload: object) -> None:
    (home / ".codelotte").mkdir(parents=True, exist_ok=True)
    (home / ".codelotte" / "settings.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_load_settings_defaults_when_missing(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "empty")
    assert settings.last_changelog_version is None
    assert settings.default_provider is None and settings.default_model is None
    assert settings.command_timeout is None and settings.notices == []


def test_load_settings_reads_all_known_keys(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_settings(
        home,
        {
            "lastChangelogVersion": "0.1.0",
            "defaultProvider": "deepseek",
            "defaultModel": "deepseek-v4-pro",
            "commandTimeoutSeconds": 30,
            "unknownKey": 1,  # 未知键：忽略并提示（不静默）
        },
    )
    settings = load_settings(home)
    assert settings.last_changelog_version == "0.1.0"
    assert settings.default_provider == "deepseek"
    assert settings.default_model == "deepseek-v4-pro"
    assert settings.command_timeout == 30
    assert any("unknownKey" in note for note in settings.notices)


def test_load_settings_fails_loud_on_bad_json_and_bad_types(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "settings.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是合法 JSON"):
        load_settings(home)

    _write_settings(home, {"defaultModel": 5})
    with pytest.raises(ConfigError, match="defaultModel"):
        load_settings(home)
    _write_settings(home, {"commandTimeoutSeconds": "120"})
    with pytest.raises(ConfigError, match="commandTimeoutSeconds"):
        load_settings(home)


def test_record_changelog_version_updates_existing_file_only(tmp_path: Path) -> None:
    """写回是读-改-写：保留其他键；没有 settings.json 就不凭空创建。"""
    home = tmp_path / "home"
    assert record_changelog_version("0.1.0", home) is None  # 无文件：不创建
    assert not (home / ".codelotte" / "settings.json").exists()

    _write_settings(home, {"defaultModel": "deepseek-flash", "futureKey": True})
    path = record_changelog_version("0.1.0", home)
    assert path is not None
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["lastChangelogVersion"] == "0.1.0"
    assert written["defaultModel"] == "deepseek-flash"  # 其他键原样保留
    assert written["futureKey"] is True
    assert not (path.parent / "settings.json.tmp").exists()  # 原子写：临时文件不残留
    assert record_changelog_version("0.1.0", home) is None  # 一致就不重写


def test_record_changelog_version_survives_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归（审查发现）：写回失败（只读盘/磁盘满）不能拖垮启动，也不能留半截文件。"""
    home = tmp_path / "home"
    _write_settings(home, {"defaultModel": "deepseek-flash"})
    path = home / ".codelotte" / "settings.json"

    def _boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("codelotte.config.os.replace", _boom)
    assert record_changelog_version("0.1.0", home) is None
    assert not (path.parent / "settings.json.tmp").exists()  # 临时文件被清掉
    assert "lastChangelogVersion" not in path.read_text(encoding="utf-8")  # 原文件不动


def test_record_changelog_version_does_not_lower_the_watermark(tmp_path: Path) -> None:
    """回归（评审发现）：跑过更新版本再回到旧版，水位不能被拉低——否则再升级会重放整段更新。"""
    home = tmp_path / "home"
    _write_settings(home, {"lastChangelogVersion": "9.9.9"})
    assert record_changelog_version("0.1.0", home) is None
    data = json.loads((home / ".codelotte" / "settings.json").read_text(encoding="utf-8"))
    assert data["lastChangelogVersion"] == "9.9.9"  # 原样不动

    _write_settings(home, {"lastChangelogVersion": "abc"})  # 认不出的值：修正为当前版本（自愈）
    assert record_changelog_version("0.1.0", home) is not None
    data = json.loads((home / ".codelotte" / "settings.json").read_text(encoding="utf-8"))
    assert data["lastChangelogVersion"] == "0.1.0"


def test_command_timeout_range_is_enforced(tmp_path: Path) -> None:
    """回归（评审发现）：commandTimeoutSeconds 有 1–600 的范围校验（文档早就这么写了）。"""
    home = tmp_path / "home"
    for bad in (0, -5, 601):
        _write_settings(home, {"commandTimeoutSeconds": bad})
        with pytest.raises(ConfigError, match="commandTimeoutSeconds.*1–600"):
            load_settings(home)
    for ok in (1, 600):
        _write_settings(home, {"commandTimeoutSeconds": ok})
        assert load_settings(home).command_timeout == ok


def test_guardrail_limits_are_read_from_settings(tmp_path: Path) -> None:
    """票据 11：三层防御的四个阈值从 settings.json 读进字段。"""
    home = tmp_path / "home"
    _write_settings(
        home,
        {
            "guardrailRepeatLimit": 4,
            "guardrailStagnationLimit": 3,
            "guardrailFailureLimit": 5,
            "guardrailPlanningLimit": 2,
        },
    )
    settings = load_settings(home)
    assert settings.guardrail_repeat_limit == 4
    assert settings.guardrail_stagnation_limit == 3
    assert settings.guardrail_failure_limit == 5
    assert settings.guardrail_planning_limit == 2


def test_guardrail_limits_reject_out_of_range_and_bad_types(tmp_path: Path) -> None:
    """阈值范围 2–100；字符串/布尔值都按类型错误报，且错误信息指明键名。"""
    from codelotte.config import _GUARDRAIL_FIELDS

    home = tmp_path / "home"
    for key, field in _GUARDRAIL_FIELDS.items():
        for bad in (1, 0, -5, 101):
            _write_settings(home, {key: bad})
            with pytest.raises(ConfigError, match=key):
                load_settings(home)
        for bad_type in ("3", True):
            _write_settings(home, {key: bad_type})
            with pytest.raises(ConfigError, match=key):
                load_settings(home)
        for ok in (2, 100):
            _write_settings(home, {key: ok})
            assert getattr(load_settings(home), field) == ok


def test_command_timeout_max_matches_bash_tool() -> None:
    """守卫：settings 的上限与 bash 工具的上限是同一个数（防两处漂移）。"""
    from codelotte.config import COMMAND_TIMEOUT_MAX
    from codelotte.tools.bash import MAX_TIMEOUT

    assert COMMAND_TIMEOUT_MAX == MAX_TIMEOUT


def test_record_changelog_version_leaves_broken_file_alone(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "settings.json").write_text("{ not json", encoding="utf-8")
    assert record_changelog_version("0.1.0", home) is None
    assert (home / ".codelotte" / "settings.json").read_text(encoding="utf-8") == "{ not json"


def test_settings_fields_cover_every_known_key() -> None:
    """守卫：文件键与 Settings 字段一一对应（加键就要加字段，反之亦然）。"""
    from codelotte.config import _KNOWN_SETTINGS

    assert len(Settings.__dataclass_fields__) - 1 == len(_KNOWN_SETTINGS)  # 减去 notices（非文件字段）


def test_compaction_thresholds_are_read_from_settings(tmp_path: Path) -> None:
    """票据 12：软/硬压缩阈值可配（比例 0.2–0.9）。"""
    home = tmp_path / "home"
    _write_settings(
        home,
        {
            "compactionSoftThreshold": 0.5,
            "compactionHardThreshold": 0.8,
        },
    )
    settings = load_settings(home)
    assert settings.compaction_soft_threshold == 0.5
    assert settings.compaction_hard_threshold == 0.8


def test_compaction_thresholds_enforce_range_and_gap(tmp_path: Path) -> None:
    """0.2 ≤ soft < hard ≤ 0.9 且 hard - soft ≥ 0.2；单边覆盖也要按生效值校验。"""
    home = tmp_path / "home"
    for soft, hard in ((0.2, 0.4), (0.6, 0.85), (0.7, 0.9), (0.2, 0.9)):
        _write_settings(
            home,
            {"compactionSoftThreshold": soft, "compactionHardThreshold": hard},
        )
        settings = load_settings(home)
        assert settings.compaction_soft_threshold == soft
        assert settings.compaction_hard_threshold == hard

    for soft, hard in ((0.19, 0.5), (0.5, 0.91), (0.6, 0.7), (0.7, 0.85)):
        _write_settings(
            home,
            {"compactionSoftThreshold": soft, "compactionHardThreshold": hard},
        )
        with pytest.raises(
            ConfigError, match="compactionSoftThreshold|compactionHardThreshold|压缩阈值"
        ):
            load_settings(home)

    for key in ("compactionSoftThreshold", "compactionHardThreshold"):
        for bad in ("0.6", True):
            _write_settings(home, {key: bad})
            with pytest.raises(ConfigError, match=key):
                load_settings(home)

    # 只改一边：另一边用默认值，差距也要满足 ≥0.2
    _write_settings(home, {"compactionSoftThreshold": 0.75})  # 默认 hard 0.85，差 0.10
    with pytest.raises(ConfigError, match="压缩阈值"):
        load_settings(home)
    _write_settings(home, {"compactionHardThreshold": 0.75})  # 默认 soft 0.60，差 0.15
    with pytest.raises(ConfigError, match="压缩阈值"):
        load_settings(home)


def test_compaction_defaults_match_the_trigger_module() -> None:
    """守卫：settings 校验用的默认值与 compaction.trigger 的常量不漂移。"""
    from codelotte.compaction import HARD_THRESHOLD, SOFT_THRESHOLD
    from codelotte.config import COMPACTION_HARD_DEFAULT, COMPACTION_SOFT_DEFAULT

    assert (COMPACTION_SOFT_DEFAULT, COMPACTION_HARD_DEFAULT) == (
        SOFT_THRESHOLD,
        HARD_THRESHOLD,
    )
