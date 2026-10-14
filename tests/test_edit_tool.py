"""edit 工具单元测试（票据 04）：唯一替换与全部失败模式（找不到/多匹配/文件缺失）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codelotte.tools.base import ToolError
from codelotte.tools.edit import EDIT_TOOL, edit_file


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_replaces_unique_snippet_and_reports_line(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.py", "line1\nold\nline3\n")
    result = edit_file("a.py", "old", "new", cwd=tmp_path)
    assert result == "已更新 a.py（替换 1 处，位于第 2 行）"
    assert path.read_text(encoding="utf-8") == "line1\nnew\nline3\n"


def test_multiline_replacement(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.py", "def f():\n    return 1\n")
    edit_file("a.py", "def f():\n    return 1", "def f():\n    return 2", cwd=tmp_path)
    assert path.read_text(encoding="utf-8") == "def f():\n    return 2\n"


def test_empty_new_string_deletes_snippet(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.txt", "keep\ndrop me\nkeep2\n")
    edit_file("a.txt", "drop me\n", "", cwd=tmp_path)
    assert path.read_text(encoding="utf-8") == "keep\nkeep2\n"


def test_missing_target_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "hello\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.py", "不存在的文本", "x", cwd=tmp_path)
    assert "未找到要替换的文本" in str(excinfo.value)


def test_ambiguous_target_raises_with_count(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "x = 1\nx = 1\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.py", "x = 1", "x = 2", cwd=tmp_path)
    assert "2 处匹配" in str(excinfo.value)
    assert "目标不唯一" in str(excinfo.value)


def test_missing_file_raises_and_hints_write(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as excinfo:
        edit_file("nope.py", "a", "b", cwd=tmp_path)
    assert "文件不存在" in str(excinfo.value)
    assert "write" in str(excinfo.value)


def test_empty_old_string_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "x\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.py", "", "y", cwd=tmp_path)
    assert "不能为空" in str(excinfo.value)


def test_identical_old_and_new_raises(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "x\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.py", "x", "x", cwd=tmp_path)
    assert "无需替换" in str(excinfo.value)


def test_crlf_file_matched_with_lf_pattern(tmp_path: Path) -> None:
    """模型给的是 LF 视图；比对时把文件的 \r\n 看成 \n，其余行尾保持原样。"""
    (tmp_path / "win.txt").write_bytes("a\r\nold\r\nb\r\n".encode())
    edit_file("win.txt", "old\nb", "new\nb", cwd=tmp_path)
    assert (tmp_path / "win.txt").read_bytes() == "a\r\nnew\r\nb\r\n".encode()


def test_only_cr_is_tolerated_before_a_newline(tmp_path: Path) -> None:
    """宽容的只有换行前的 \r：old 后面多一个字母 r 时不许匹配 old + 换行 + b。"""
    (tmp_path / "a.txt").write_bytes(b"oldr\nb\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.txt", "old\nb", "x", cwd=tmp_path)
    assert "未找到" in str(excinfo.value)


def test_non_utf8_file_raises(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(bytes([255, 254, 0]))
    with pytest.raises(ToolError) as excinfo:
        edit_file("bin.dat", "a", "b", cwd=tmp_path)
    assert "UTF-8" in str(excinfo.value)


def test_handler_requires_all_string_args(tmp_path: Path) -> None:
    target = str(tmp_path / "a.txt")
    with pytest.raises(ToolError):
        asyncio.run(EDIT_TOOL.handler({"path": target, "new_string": "b"}))
    with pytest.raises(ToolError):
        asyncio.run(EDIT_TOOL.handler({"path": target, "old_string": "a"}))


def test_crlf_file_with_leading_newline_pattern(tmp_path: Path) -> None:
    """回归：LF 版 pattern 以 \n 开头时会沿 \r\n 边界错位命中——必须以 CRLF 变体为准，不留孤 \r。"""
    (tmp_path / "win.txt").write_bytes(b"a\r\nb\r\n")
    edit_file("win.txt", "\nb", "\nX", cwd=tmp_path)
    assert (tmp_path / "win.txt").read_bytes() == b"a\r\nX\r\n"


def test_crlf_file_ambiguous_variant_reports_crlf_count(tmp_path: Path) -> None:
    (tmp_path / "win.txt").write_bytes("one\r\ntwo\r\none\r\ntwo\r\n".encode())
    with pytest.raises(ToolError) as excinfo:
        edit_file("win.txt", "one\ntwo", "x", cwd=tmp_path)
    assert "2 处匹配" in str(excinfo.value)


def test_old_string_with_crlf_matches_crlf_file(tmp_path: Path) -> None:
    """回归：模型自己带上 \r\n 的原文也要能对得上（拍平后匹配）。"""
    (tmp_path / "win.txt").write_bytes(b"a\r\nb\r\n")
    edit_file("win.txt", "\r\nb", "\r\nB", cwd=tmp_path)
    assert (tmp_path / "win.txt").read_bytes() == b"a\r\nB\r\n"


def test_new_string_with_crlf_follows_file_style(tmp_path: Path) -> None:
    """回归：模型新内容里带 \r\n，写进普通换行文件时要跟着文件的风格走，不能掺混行尾。"""
    (tmp_path / "l.txt").write_bytes(b"a\nb\n")
    edit_file("l.txt", "b", "c\r\nd", cwd=tmp_path)
    assert (tmp_path / "l.txt").read_bytes() == b"a\nc\nd\n"


def test_crlf_old_and_new_that_only_differ_in_line_endings_is_rejected(tmp_path: Path) -> None:
    """回归：拍平后两者相同（只差换行写法）也算"无需替换"，不能空转一次写盘。"""
    (tmp_path / "a.txt").write_bytes(b"x\ny\n")
    with pytest.raises(ToolError) as excinfo:
        edit_file("a.txt", "x\ny", "x\r\ny", cwd=tmp_path)
    assert "无需替换" in str(excinfo.value)


def test_mixed_line_endings_only_touch_the_match(tmp_path: Path) -> None:
    """回归：文件里两种换行混着时，只动匹配到的那一段，其他行的行尾一个字节不改。"""
    (tmp_path / "mix.txt").write_bytes(b"a\r\nb\nc\r\n")
    edit_file("mix.txt", "b", "B", cwd=tmp_path)
    assert (tmp_path / "mix.txt").read_bytes() == b"a\r\nB\nc\r\n"


def test_new_lines_follow_the_file_crlf_style(tmp_path: Path) -> None:
    """文件里有 \r\n 就当 Windows 风格：新内容两行之间也用 \r\n；没碰的行一个字节不改。"""
    (tmp_path / "mix2.txt").write_bytes(b"x\r\na\nb\nz\n")
    edit_file("mix2.txt", "a\nb", "A\nB", cwd=tmp_path)
    assert (tmp_path / "mix2.txt").read_bytes() == b"x\r\nA\r\nB\nz\n"
