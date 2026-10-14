"""read 工具：读取文本文件的行范围（SPEC §D 四工具之一）。

返回带行号的内容（模型据此引用行、配合后续 edit 的精确替换）；
可预期失败一律抛 ToolError，由执行层转为结果文本回传模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codelotte.tools.base import Tool, ToolError

DEFAULT_LIMIT = 2000  # 默认读取行数，同时也是单次读取的行数上限（防单次输出吃光上下文）


def read_file(
    path: str, *, offset: int = 1, limit: int = DEFAULT_LIMIT, cwd: Path | None = None
) -> str:
    """读取 path 从头第 offset 行起、至多 limit 行，返回带行号的文本。

    Args:
        path: 文件路径（绝对路径或相对 cwd）。
        offset: 起始行号（1-based）。
        limit: 最多读取行数，上限 DEFAULT_LIMIT。
        cwd: 相对路径的基准目录，默认当前工作目录。

    Returns:
        头部注明显示范围与总行数；每行格式 `行号<TAB>内容`。

    Raises:
        ToolError: 文件不存在、是目录、非 UTF-8 文本、无权限、offset 越界。
    """
    base = cwd if cwd is not None else Path.cwd()
    target = Path(path)
    if not target.is_absolute():
        target = base / target
    if target.is_dir():
        raise ToolError(f"不是文件（是目录）：{path}")
    if not target.is_file():
        raise ToolError(f"文件不存在：{path}")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"不是 UTF-8 文本文件，无法按文本读取：{path}") from None
    except OSError as exc:
        raise ToolError(f"读取失败：{path}（{exc}）") from exc

    lines = text.splitlines()
    if not lines:
        return f"{path}（空文件）"
    offset = max(1, offset)  # 宽容处理：模型常把 offset 写成 0 表示第一行
    limit = max(1, min(limit, DEFAULT_LIMIT))  # 上限兜底，防单次读取吃光上下文
    if offset > len(lines):
        raise ToolError(f"offset {offset} 超出文件行数（{path} 共 {len(lines)} 行）")
    start = offset - 1
    selected = lines[start : start + limit]
    end = start + len(selected)
    numbered = "\n".join(
        f"{number}\t{line}" for number, line in enumerate(selected, start=offset)
    )
    header = f"{path}（第 {offset}-{end} 行 / 共 {len(lines)} 行）"
    if end < len(lines):
        remaining = len(lines) - end
        return f"{header}\n{numbered}\n（已截断：后续还有 {remaining} 行，可用 offset={end + 1} 继续读）"
    return f"{header}\n{numbered}"


def _int_arg(args: dict[str, Any], key: str, default: int) -> int:
    """取整数参数：缺失/None 用默认值；接受 int 或数字字符串（模型偶尔把数字写成字符串）。

    其它类型一律抛 ToolError——静默回退会让模型永远学不到错，错误回传才能自纠（SPEC §D）。
    """
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise ToolError(f"参数 {key} 应为整数，收到 {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(f"参数 {key} 应为整数，收到 {value!r}") from None


async def _read_handler(args: dict[str, Any]) -> str:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ToolError("缺少必需参数 path（要读取的文件路径）")
    return read_file(
        path.strip(),
        offset=_int_arg(args, "offset", 1),
        limit=_int_arg(args, "limit", DEFAULT_LIMIT),
    )


READ_TOOL = Tool(
    name="read",
    description=(
        "Read a UTF-8 text file and return its lines with line numbers. "
        f"Use offset/limit to read a slice of a large file (at most {DEFAULT_LIMIT} lines per call)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path: absolute, or relative to the current working directory.",
            },
            "offset": {
                "type": "integer",
                "description": "1-based line number to start reading from. Defaults to 1.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of lines to read (1-{DEFAULT_LIMIT}). Defaults to {DEFAULT_LIMIT}.",
            },
        },
        "required": ["path"],
    },
    handler=_read_handler,
)
