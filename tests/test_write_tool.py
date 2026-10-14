"""write 工具单元测试（票据 04）：整文件写入、建父目录、覆盖语义、路径形式、可预期失败。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from codelotte.tools.base import ToolError
from codelotte.tools.read import read_file
from codelotte.tools.write import WRITE_TOOL, write_file


def test_creates_new_file_and_reports_state(tmp_path: Path) -> None:
    result = write_file("a.txt", "你好\n", cwd=tmp_path)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "你好\n"
    assert result == "已写入 a.txt（3 字符，新建文件）"


def test_overwrites_existing_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("旧内容", encoding="utf-8")
    result = write_file("a.txt", "新", cwd=tmp_path)
    assert "覆盖已有文件" in result
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "新"


def test_creates_parent_directories(tmp_path: Path) -> None:
    write_file("deep/nested/a.txt", "x", cwd=tmp_path)
    assert (tmp_path / "deep" / "nested" / "a.txt").read_text(encoding="utf-8") == "x"


def test_line_endings_are_written_verbatim(tmp_path: Path) -> None:
    """行尾按模型给的原文写，不做平台翻译（跨平台可复现）。"""
    write_file("a.txt", "a\nb\n", cwd=tmp_path)
    assert (tmp_path / "a.txt").read_bytes() == b"a\nb\n"


def test_directory_target_raises(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    with pytest.raises(ToolError) as excinfo:
        write_file("dir", "x", cwd=tmp_path)
    assert "目录" in str(excinfo.value)


def test_windows_drive_form_only_recognizes_drive_shaped_paths() -> None:
    """翻译只认"单字母盘符"形状；/dev/null、相对路径、已是盘符形式的一律不动。"""
    from codelotte.tools.base import _windows_drive_form

    assert _windows_drive_form("/d/foo/bar") == "D:/foo/bar"
    assert _windows_drive_form("\\d\\foo") == "D:/foo"
    assert _windows_drive_form("/d") == "D:/"
    assert _windows_drive_form("/dev/null") == "/dev/null"
    assert _windows_drive_form("rel/foo") == "rel/foo"
    assert _windows_drive_form("D:/foo") == "D:/foo"


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash 风格路径只在 Windows 上翻译")
def test_git_bash_style_path_writes_to_the_real_drive(tmp_path: Path) -> None:
    """回归（2026-10-15 真机）：/d/... 曾被当成"当前盘符根下的 d 目录"，
    文件写到别处、bash 侧永远看不到。Git Bash 里 /d/foo 就是 D:\\foo——
    write 必须落到同一处，read 也必须能从同一写法读回来。"""
    tail = str(tmp_path)[len(tmp_path.drive) :]
    bash_style = "/" + tmp_path.drive[0].lower() + tail.replace("\\", "/")
    write_file(bash_style + "/t.txt", "hi\n", cwd=Path.cwd())
    assert (tmp_path / "t.txt").read_text(encoding="utf-8") == "hi\n"
    assert "1\thi" in read_file(bash_style + "/t.txt")


def test_handler_requires_content_string(tmp_path: Path) -> None:
    target = str(tmp_path / "a.txt")
    with pytest.raises(ToolError):
        asyncio.run(WRITE_TOOL.handler({"path": target}))
    with pytest.raises(ToolError):
        asyncio.run(WRITE_TOOL.handler({"path": target, "content": 123}))
