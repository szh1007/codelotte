"""read 工具：读取文本文件的行范围（SPEC §D 四工具之一）。

返回带行号的内容（模型据此引用行、配合后续 edit 的精确替换）；
可预期失败一律抛 ToolError，由执行层转为结果文本回传模型。
换行约定：读入时 \r\n 与 \r 统一成 \n（Python 文本模式）——模型看到的永远是 LF 视图。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codelotte.tools.base import (
    Tool,
    ToolError,
    cap_output,
    int_arg,
    resolve_path,
    str_arg,
)

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
    target = resolve_path(path, cwd)
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


async def _read_handler(args: dict[str, Any]) -> str:
    path = str_arg(args, "path")
    text = read_file(
        path.strip(),
        offset=int_arg(args, "offset", 1),
        limit=int_arg(args, "limit", DEFAULT_LIMIT),
    )
    # 行数上限挡不住"少数超长行"（一行的字符数无上限）：统一再过一遍字符级截断（SPEC §D）
    return cap_output(text, label="read")


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
