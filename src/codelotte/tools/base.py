"""工具层公共件：工具定义、可预期失败、参数解析与结果长度管理（SPEC §D）。

工具 = 名字 + 描述 + 参数 JSON Schema + 执行函数。模型只看到前三者
（wire 格式），执行永远在我们这侧。
"""

from __future__ import annotations

import re
import sys
import tempfile
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ToolError(Exception):
    """工具的可预期失败（文件不存在、参数缺失等）。

    由执行层转成结果文本回传模型让它自纠，不视为系统错误（SPEC §D）。
    """


@dataclass(frozen=True)
class ToolOutcome:
    """handler 的显式结果：content 回传模型，ok=False 表示这次执行失败（如命令退出码非 0）。

    handler 直接返回 str 等价于 ToolOutcome(content, ok=True)。
    """

    content: str
    ok: bool = True


ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, "str | ToolOutcome"]]


@dataclass(frozen=True)
class Tool:
    """一个工具的定义。handler 抛 ToolError 表示可预期失败，正常时返回结果文本。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    # 该工具真实执行的环境（会话审计字段）：文件工具在宿主上跑，bash 随执行器（docker/local）
    exec_env: str = "local"


def wire_schema(tool: Tool) -> dict[str, Any]:
    """转成 OpenAI 兼容协议的工具定义（键序固定，保证请求前缀逐字节稳定）。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def str_arg(args: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    """取必需的字符串参数：类型不对 → ToolError；默认还要求非空白（allow_empty=True 放行空串）。

    空串放行是给"内容类"参数用的（write 的 content、edit 的 new_string 空串=删除）；
    "能不能是空"之外的规则留在领域函数里定（如 edit_file 拒绝空 old_string）。
    """
    value = args.get(key)
    if not isinstance(value, str):
        raise ToolError(f"缺少必需参数 {key}（应为字符串）")
    if not allow_empty and not value.strip():
        raise ToolError(f"缺少必需参数 {key}（应为非空字符串）")
    return value


_BASH_DRIVE_PATH = re.compile(r"^[\\/]([A-Za-z])(?:[\\/](.*))?$")


def _windows_drive_form(path: str) -> str:
    """把 Git Bash 风格路径（/d/foo）翻成 Windows 盘符形式（D:/foo）。

    同一个写法在两个世界里含义不同：Git Bash 里 /d/foo 就是 D:\\foo，而 Windows 的
    Path("/d/foo") 是"当前盘符根下的 d\\foo"——模型从 pwd/ls 看到的都是前者，
    不统一它就会把文件写到 D:\\d\\... 而 bash 侧永远看不到（2026-10-15 真机踩过）。
    """
    match = _BASH_DRIVE_PATH.match(path)
    if match is None:
        return path
    drive, rest = match.groups()
    return f"{drive.upper()}:/{rest or ''}"


def resolve_path(path: str, cwd: Path | None) -> Path:
    """把工具参数里的路径解析为绝对路径（相对 cwd 基准），并拒绝目录目标。

    三个文件工具（read/write/edit）共用这一条路径纪律：报错文案里的 path
    保持模型原样给出的写法，便于它自己纠正。Windows 上先把 Git Bash 风格
    路径统一成盘符形式（/d/foo 在 Windows 语义下会指向"当前盘符根下的 d\\foo"）。
    """
    base = cwd if cwd is not None else Path.cwd()
    text = _windows_drive_form(path) if sys.platform == "win32" else path
    target = Path(text)
    if not target.is_absolute():
        target = base / target
    if target.is_dir():
        raise ToolError(f"不是文件（是目录）：{path}")
    return target


def int_arg(
    args: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """取整数参数：缺失/None 用默认值；接受 int 或数字字符串（模型偶尔把数字写成字符串）。

    其它类型一律抛 ToolError——静默回退会让模型永远学不到错（SPEC §D）。
    给了 minimum/maximum 时越界钳制（bash 的 timeout 用）：模型要"跑一小时"给它的该是上限而不是报错。
    """
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise ToolError(f"参数 {key} 应为整数，收到 {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"参数 {key} 应为整数，收到 {value!r}") from None
    if minimum is not None:
        result = max(result, minimum)
    if maximum is not None:
        result = min(result, maximum)
    return result


# ---- 工具结果长度管理（SPEC §D）：超阈值截断保留头尾，全文写入临时文件 ----

ARTIFACT_DIR = Path(tempfile.gettempdir()) / "codelotte-tool-output"
_MAX_CHARS = 30_000
_HEAD_CHARS = 20_000
_TAIL_CHARS = 8_000


def cap_output(text: str, *, label: str) -> str:
    """超长结果截断：保留头部 + 尾部，中间标注省略量与全文去向，防止单次输出吃光上下文。"""
    if len(text) <= _MAX_CHARS:
        return text
    hint = _save_artifact(text, label)
    omitted = len(text) - _HEAD_CHARS - _TAIL_CHARS
    return (
        f"{text[:_HEAD_CHARS]}\n"
        f"……（中间省略 {omitted} 字符；完整输出共 {len(text)} 字符，{hint}）\n"
        f"{text[-_TAIL_CHARS:]}"
    )


def _save_artifact(text: str, label: str) -> str:
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        path = ARTIFACT_DIR / f"{label}-{stamp}-{uuid.uuid4().hex[:6]}.log"
        path.write_text(text, encoding="utf-8", newline="")
        return f"已写入 {path}，可用 read 工具查看"
    except OSError:
        return "因写入失败未能保存全文"  # 截断提示是展示问题，不能反过来让工具调用失败
