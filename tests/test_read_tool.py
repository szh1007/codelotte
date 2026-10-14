"""read 工具单元测试（票据 03）：行范围、截断提示、各类可预期失败。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codelotte.tools.base import ToolError
from codelotte.tools.read import DEFAULT_LIMIT, READ_TOOL, read_file


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_whole_file_with_line_numbers(tmp_path: Path) -> None:
    _write(tmp_path, "a.txt", "第一行\nsecond\n")
    result = read_file("a.txt", cwd=tmp_path)
    assert result == "a.txt（第 1-2 行 / 共 2 行）\n1\t第一行\n2\tsecond"


def test_offset_and_limit_slice_with_truncation_footer(tmp_path: Path) -> None:
    _write(tmp_path, "a.txt", "1\n2\n3\n4\n5\n")
    result = read_file("a.txt", offset=2, limit=2, cwd=tmp_path)
    assert result == "a.txt（第 2-3 行 / 共 5 行）\n2\t2\n3\t3\n（已截断：后续还有 2 行，可用 offset=4 继续读）"


def test_default_limit_caps_long_files(tmp_path: Path) -> None:
    text = "".join(f"line{i}\n" for i in range(1, DEFAULT_LIMIT + 6))
    _write(tmp_path, "big.txt", text)
    result = read_file("big.txt", cwd=tmp_path)
    assert f"共 {DEFAULT_LIMIT + 5} 行" in result
    assert f"{DEFAULT_LIMIT}\tline{DEFAULT_LIMIT}" in result  # 最后一行是上限行
    assert "已截断：后续还有 5 行" in result


def test_explicit_limit_is_clamped_to_cap(tmp_path: Path) -> None:
    text = "".join(f"line{i}\n" for i in range(1, DEFAULT_LIMIT + 6))
    _write(tmp_path, "big.txt", text)
    result = read_file("big.txt", limit=10_000, cwd=tmp_path)
    assert "已截断" in result  # 请求超上限也只给 DEFAULT_LIMIT 行


def test_offset_zero_is_treated_as_first_line(tmp_path: Path) -> None:
    _write(tmp_path, "a.txt", "x\ny\n")
    assert "1\tx" in read_file("a.txt", offset=0, cwd=tmp_path)


def test_offset_beyond_eof_reports_total(tmp_path: Path) -> None:
    _write(tmp_path, "a.txt", "x\ny\n")
    with pytest.raises(ToolError) as excinfo:
        read_file("a.txt", offset=3, cwd=tmp_path)
    assert "共 2 行" in str(excinfo.value)


def test_empty_file(tmp_path: Path) -> None:
    _write(tmp_path, "empty.txt", "")
    assert read_file("empty.txt", cwd=tmp_path) == "empty.txt（空文件）"


def test_missing_file_raises_tool_error(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as excinfo:
        read_file("nope.txt", cwd=tmp_path)
    assert "文件不存在" in str(excinfo.value)


def test_directory_raises_tool_error(tmp_path: Path) -> None:
    (tmp_path / "dir").mkdir()
    with pytest.raises(ToolError) as excinfo:
        read_file("dir", cwd=tmp_path)
    assert "目录" in str(excinfo.value)


def test_non_utf8_file_raises_tool_error(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(ToolError) as excinfo:
        read_file("bin.dat", cwd=tmp_path)
    assert "UTF-8" in str(excinfo.value)


def test_absolute_path_ignores_cwd(tmp_path: Path) -> None:
    path = _write(tmp_path, "abs.txt", "hello\n")
    assert "1\thello" in read_file(str(path), cwd=tmp_path / "elsewhere")


def test_handler_rejects_missing_or_bad_path() -> None:
    with pytest.raises(ToolError):
        asyncio.run(READ_TOOL.handler({}))
    with pytest.raises(ToolError):
        asyncio.run(READ_TOOL.handler({"path": "   "}))
    with pytest.raises(ToolError):
        asyncio.run(READ_TOOL.handler({"path": 123}))


def test_handler_tolerates_string_numbers(tmp_path: Path) -> None:
    """模型偶尔把数字写成字符串——宽容解析而不是整个调用失败。"""
    target = _write(tmp_path, "a.txt", "x\ny\nz\n")
    result = asyncio.run(READ_TOOL.handler({"path": str(target), "offset": "2", "limit": "3"}))
    assert result == f"{target}（第 2-3 行 / 共 3 行）\n2\ty\n3\tz"


def test_handler_rejects_malformed_integer(tmp_path: Path) -> None:
    """畸形整数不静默回退——错误回传模型自纠（SPEC §D）。"""
    target = _write(tmp_path, "a.txt", "x\n")
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(READ_TOOL.handler({"path": str(target), "limit": "abc"}))
    assert "limit" in str(excinfo.value)
    assert "整数" in str(excinfo.value)


def test_permission_error_maps_to_tool_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无权限读取：OSError 转 ToolError（作为工具结果回传模型，循环不崩）。"""
    path = _write(tmp_path, "secret.txt", "x\n")

    def deny(*args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(ToolError) as excinfo:
        read_file(str(path))
    assert "读取失败" in str(excinfo.value)
    assert "Permission denied" in str(excinfo.value)
