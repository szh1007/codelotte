"""TUI 与 HTML 导出共用的展示模板（票据 08）。

把"工具块标题 / 参数预览 / 耗时"这类两边必须一致的东西收在一处——"导出与界面逐项一致"
（票据 08 验收）从口号变成结构保证：同一句话由同一个函数产出。
显示上限（截断长度）按介质传参：终端窄、网页宽，数值各留各的。
"""

from __future__ import annotations

import json

from codelotte.guardrails import STOP_CIRCUIT, STOP_PLANNING


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


_GUARDRAIL_LAYER_LABELS = {"tool": "工具层", "reasoning": "推理层", "planning": "规划层"}


def guardrail_notice(layer: str, message: str) -> str:
    """死循环防御事件的一句话（TUI 对话流与 HTML/Markdown 导出共用，票据 11）。"""
    label = _GUARDRAIL_LAYER_LABELS.get(layer, layer or "未知层")
    return f"🛡 守护拦截（{label}）：{message}"


_GUARDRAIL_STOP_LABELS = {STOP_CIRCUIT: "连续失败熔断", STOP_PLANNING: "规划层温和终止"}


def guardrail_stop_text(stop: str) -> str:
    """回合终止原因的中文说法（TUI 展示用；不把内部 token 直接给用户）。"""
    return _GUARDRAIL_STOP_LABELS.get(stop, stop)


def compaction_after_share(after_tokens: int, window: int) -> float:
    """压缩后估算占比（窗口缺失/为 0 时返回 0；TUI、导出与 -p 共用）。"""
    return after_tokens / window if window else 0.0


def compaction_utilization(
    before_tokens: int, window: int, stored: object = None
) -> float:
    """触发时占比：优先用事件值；历史记录不落百分比时由 beforeTokens/window 现算。"""
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return float(stored)
    return before_tokens / window if window else 0.0


def compaction_title(mode: str, utilization: float, after_share: float) -> str:
    """压缩点标题（TUI 折叠块与导出的同一句话，票据 12）。"""
    label = "硬触发" if mode == "hard" else "软触发"
    return f"🗜 上下文压缩（{label} · {utilization:.0%} → 预计 {after_share:.0%}）"
