"""TUI 与 HTML 导出共用的展示模板（票据 08）。

把"工具块标题 / 参数预览 / 耗时"这类两边必须一致的东西收在一处——"导出与界面逐项一致"
（票据 08 验收）从口号变成结构保证：同一句话由同一个函数产出。
显示上限（截断长度）按介质传参：终端窄、网页宽，数值各留各的。
"""

from __future__ import annotations

import json


def preview_text(text: str, limit: int) -> str:
    """压成一行再截断加省略号（标题里的任何文本都先过这里）。"""
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def args_preview(name: str, arguments: object, *, limit: int) -> str:
    """工具块标题上的参数预览：常用工具取关键字段，其他给压缩后的原始 JSON。

    arguments 可以是解析好的对象，也可以是原始文本（参数畸形时记录的就是原始文本）。
    """
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return preview_text(arguments, limit)
    if not isinstance(arguments, dict):
        return preview_text(json.dumps(arguments, ensure_ascii=False), limit)
    if name == "bash" and "command" in arguments:
        return preview_text(str(arguments["command"]), limit)
    if "path" in arguments:
        return preview_text(str(arguments["path"]), limit)
    return preview_text(json.dumps(arguments, ensure_ascii=False), limit)


def tool_title(name: str, preview: str, status: str) -> str:
    """工具块标题（收起态）：`⚙ 名称  参数预览  状态`。"""
    return f"⚙ {name}  {preview}  {status}"


def duration_text(duration_ms: int) -> str:
    """耗时显示（展开体开头）：`（123ms）`。"""
    return f"（{duration_ms}ms）"
