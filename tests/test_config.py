"""`.env` 自动加载的单元测试（用户级 → 项目级，不覆盖已有环境变量）。"""

from __future__ import annotations

from pathlib import Path

from codelotte.config import load_env_files, parse_env_text


def test_parse_basic_key_values() -> None:
    parsed = parse_env_text("A=1\nB=hello world\n")
    assert parsed == {"A": "1", "B": "hello world"}


def test_parse_ignores_comments_and_blank_lines() -> None:
    parsed = parse_env_text("# comment\n\n   \nA=1\n")
    assert parsed == {"A": "1"}


def test_parse_strips_quotes_and_export_prefix() -> None:
    parsed = parse_env_text('export A="quoted"\nB=\'single\'\n')
    assert parsed == {"A": "quoted", "B": "single"}


def test_parse_skips_lines_without_key() -> None:
    parsed = parse_env_text("=nokey\nJUSTTEXT\nA=1\n")
    assert parsed == {"A": "1"}


def test_load_project_env_overrides_user_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / ".env").write_text("KEY=user\nONLY_USER=u\n", encoding="utf-8")
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("KEY=project\n", encoding="utf-8")
    env: dict[str, str] = {}
    loaded = load_env_files(cwd=project, home=home, env=env)
    assert env["KEY"] == "project"
    assert env["ONLY_USER"] == "u"
    assert loaded == [home / ".codelotte" / ".env", project / ".env"]


def test_existing_environment_wins(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("KEY=fromfile\n", encoding="utf-8")
    env = {"KEY": "fromenv"}
    load_env_files(cwd=project, home=tmp_path / "nohome", env=env)
    assert env["KEY"] == "fromenv"


def test_missing_files_are_ignored(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    loaded = load_env_files(cwd=tmp_path, home=tmp_path, env=env)
    assert loaded == []
    assert env == {}
