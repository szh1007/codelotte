"""write 工具：整文件写入（创建或整体重写）。局部修改请用 edit（SPEC §D）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codelotte.tools.base import Tool, ToolError, resolve_path, str_arg


def write_file(path: str, content: str, *, cwd: Path | None = None) -> str:
    """把 content 整文件写入 path，父目录不存在时自动创建。

    行尾按 content 原样写入（不做平台翻译）——跨平台可复现，与仓库 LF 纪律一致。

    Args:
        path: 文件路径（绝对路径或相对 cwd）。
        content: 完整的文件内容（整文件覆盖，不是追加）。
        cwd: 相对路径的基准目录，默认当前工作目录。

    Raises:
        ToolError: 目标是目录、无权限、磁盘错误等。
    """
    target = resolve_path(path, cwd)
    existed = target.is_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolError(f"写入失败：{path}（{exc}）") from exc
    state = "覆盖已有文件" if existed else "新建文件"
    return f"已写入 {path}（{len(content)} 字符，{state}）"


async def _write_handler(args: dict[str, Any]) -> str:
    path = str_arg(args, "path")
    content = str_arg(args, "content", allow_empty=True)  # 空内容 = 建空文件，合法
    return write_file(path.strip(), content)


WRITE_TOOL = Tool(
    name="write",
    description=(
        "Create a file or overwrite an existing file with the given content. "
        "Use it for new files or complete rewrites; to change part of an existing file use edit instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path: absolute, or relative to the current working directory.",
            },
            "content": {
                "type": "string",
                "description": "The complete file content to write (UTF-8 text).",
            },
        },
        "required": ["path", "content"],
    },
    handler=_write_handler,
)
