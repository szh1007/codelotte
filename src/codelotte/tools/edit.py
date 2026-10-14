"""edit 工具：精确文本替换（要求目标唯一——找不到或出现多次时明确报错，模型自纠后重试）。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from codelotte.tools.base import Tool, ToolError, resolve_path, str_arg


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    *,
    cwd: Path | None = None,
) -> str:
    """把 path 中唯一出现的 old_string 替换为 new_string，返回替换位置。

    换行约定（read / write / edit 统一）：模型的世界里只有 \n。这里比对时把文件的
    \r\n 看成 \n（只看，不改）；命中后只替换那一段，前后字节原样保留；
    新内容的换行跟文件走——文件里有 \r\n 就用 \r\n，没有就是 \n。

    Args:
        path: 文件路径（必须是已存在的文件；新建请用 write）。
        old_string: 要替换的原文本，须与文件内容逐字符一致（含缩进与空行）。
        new_string: 替换后的文本；空字符串表示删除该段。
        cwd: 相对路径的基准目录，默认当前工作目录。

    Raises:
        ToolError: 文件不存在、old_string 为空/找不到/出现多次、old 与 new 相同、非 UTF-8 等。
    """
    target = resolve_path(path, cwd)
    if not target.is_file():
        raise ToolError(f"文件不存在：{path}（新建文件请用 write）")

    # 模型可能自带 \r\n 的旧文/新文（它见过 Windows 文件）：先拍平到 \n 再处理
    old_string = old_string.replace("\r\n", "\n")
    new_string = new_string.replace("\r\n", "\n")
    if not old_string:
        raise ToolError("old_string 不能为空（要删除一段文本时 new_string 留空即可）")
    if old_string == new_string:
        raise ToolError("old_string 与 new_string 相同，无需替换")

    try:
        text = target.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"不是 UTF-8 文本文件，无法编辑：{path}") from None
    except OSError as exc:
        raise ToolError(f"读取失败：{path}（{exc}）") from exc

    # 比对：旧文按行拆开，行与行之间允许 \n 或 \r\n（文件可能是 Windows 存的）；
    # 除这一个 \r 之外，字符必须逐一相同——不猜"这文件是哪种风格"
    pattern = re.compile(
        r"\r?\n".join(re.escape(line) for line in old_string.split("\n"))
    )
    matches = list(pattern.finditer(text))
    if not matches:
        raise ToolError(
            f"未找到要替换的文本：{path}（old_string 须与文件内容逐字符一致，含缩进）"
        )
    if len(matches) > 1:
        raise ToolError(
            f"找到 {len(matches)} 处匹配，目标不唯一：{path}（请扩展 old_string 加入前后文，使其只匹配一处）"
        )

    match = matches[0]
    line = text.count("\n", 0, match.start()) + 1
    # 落笔：只换命中那一段；文件里有 \r\n 就按 Windows 风格给新内容的换行补上 \r
    replacement = new_string.replace("\n", "\r\n") if "\r\n" in text else new_string
    updated = text[: match.start()] + replacement + text[match.end() :]
    try:
        target.write_bytes(updated.encode("utf-8"))
    except OSError as exc:
        raise ToolError(f"写入失败：{path}（{exc}）") from exc
    return f"已更新 {path}（替换 1 处，位于第 {line} 行）"


async def _edit_handler(args: dict[str, Any]) -> str:
    path = str_arg(args, "path")
    old_string = str_arg(
        args, "old_string", allow_empty=True
    )  # 空 old 由 edit_file 拒（领域规则）
    new_string = str_arg(args, "new_string", allow_empty=True)
    return edit_file(path.strip(), old_string, new_string)


EDIT_TOOL = Tool(
    name="edit",
    description=(
        "Replace an exact snippet in an existing file. old_string must match the file content exactly "
        "and occur exactly once — otherwise the edit fails and you must extend it with more context. "
        "An empty new_string deletes the snippet. Prefer edit over write for partial changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path: absolute, or relative to the current working directory.",
            },
            "old_string": {
                "type": "string",
                "description": "Exact text to replace; must occur exactly once in the file.",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement text; an empty string deletes old_string.",
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
    handler=_edit_handler,
)
