"""更新提示（changelog.py）：版本比对、条目截取、读不到就不打扰。"""

from __future__ import annotations

from pathlib import Path

from codelotte.changelog import changelog_notice, should_record

_SAMPLE = """# CHANGELOG

## [0.2.0] - 2026-11-01

- 新增压缩

## [0.1.0] - 2026-10-17

- 首个版本
"""


def _file(tmp_path: Path, text: str = _SAMPLE) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_notice_lists_entries_newer_than_stored(tmp_path: Path) -> None:
    notice = changelog_notice("0.0.1", "0.2.0", path=_file(tmp_path))
    assert notice is not None
    assert "更新内容（0.0.1 → 0.2.0）" in notice
    assert "【0.2.0】" in notice and "【0.1.0】" in notice
    assert "新增压缩" in notice and "首个版本" in notice


def test_notice_only_covers_up_to_current(tmp_path: Path) -> None:
    """CHANGELOG 里有更新的条目也不提前剧透：只报到当前版本为止。"""
    notice = changelog_notice("0.1.0", "0.1.5", path=_file(tmp_path))
    assert notice is None  # 0.1.5 没有自己的条目 → 没内容可报，安静
    notice = changelog_notice("0.1.0", "0.2.0", path=_file(tmp_path))
    assert notice is not None and "【0.2.0】" in notice and "【0.1.0】" not in notice


def test_silent_cases(tmp_path: Path) -> None:
    path = _file(tmp_path)
    assert changelog_notice(None, "0.2.0", path=path) is None  # 首次运行：静默记版本
    assert changelog_notice("0.2.0", "0.2.0", path=path) is None  # 一致
    assert changelog_notice("0.3.0", "0.2.0", path=path) is None  # 版本回退：只记不报
    assert changelog_notice("乱写", "0.2.0", path=path) is None  # 认不出：不猜
    assert changelog_notice("0.0.1", "0.2.0", path=tmp_path / "nope.md") is None  # 读不到文件


def test_versions_compare_with_zero_padding(tmp_path: Path) -> None:
    """回归（审查发现）：段数不同的等价写法不误报；带后缀的版本号认不出就不猜。"""
    path = _file(tmp_path)
    assert changelog_notice("0.1", "0.1.0", path=path) is None  # 0.1 == 0.1.0
    assert changelog_notice("v0.0.1", "0.2.0", path=path) is not None  # 前缀 v 照常识别
    assert changelog_notice("1.0.0rc1", "0.2.0", path=path) is None  # 数字抽取不冒充版本


def test_should_record_only_for_first_run_or_older_watermark() -> None:
    """水位更新规则：首次/落后才写；一致不写、回退不写；认不出的值修正（自愈）。"""
    assert should_record(None, "0.1.0") is True  # 首次
    assert should_record("0.0.1", "0.1.0") is True  # 落后
    assert should_record("0.1", "0.1.0") is False  # 等价写法（补零后相等）
    assert should_record("0.1.0", "0.1.0") is False  # 一致：幂等
    assert should_record("9.9.9", "0.1.0") is False  # 回退：不拉低水位
    assert should_record("abc", "0.1.0") is True  # 认不出：当成坏了修过来


def test_project_changelog_parses() -> None:
    """真实 CHANGELOG.md 能被解析出当前版本条目（版本号写错格式这里就会红）。"""
    from codelotte import __version__
    from tests.support import PROJECT_ROOT

    notice = changelog_notice("0.0.1", __version__, path=PROJECT_ROOT / "CHANGELOG.md")
    assert notice is not None and f"【{__version__}】" in notice
