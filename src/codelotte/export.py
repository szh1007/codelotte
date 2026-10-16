"""会话导出（票据 08，SPEC §M）：会话记录 → 单文件 HTML / Markdown。

两种格式两条消费路径：HTML 是**分享面**（单文件自包含、零外链零脚本、浏览器直接开）；
Markdown 是**终端/编辑器直接读**的面（不用开浏览器；助手回答本身就是 markdown，原样渲染
反而更可读）。

共同纪律：
- **纯函数**——只读记录（由调用方读好传入），同样输入两次渲染逐字节一致：不掺导出时间戳、
  不查文件系统、不依赖遍历顺序（不碰 set/dict 的哈希序）；
- **内容逐字来自执行记录**——只做转义与截断标注，不美化不改写（证据的可信度在此）；
- 结构性逃逸都堵死：HTML 一切文本走 `html.escape`；Markdown 的围栏按内容动态加长
  （内容里的 ``` 冲不出围栏）、表格单元格转义 `|`。

三块视图：时间线（消息 + 工具调用 + 标记层）/ 成本面板（每次调用 token、时段、
命中率、费用与合计）/ 价目脚注。合计与命中率复用 cost.Ledger——与 TUI 同源，不多算一份。
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from codelotte.cost import (
    CURRENCY_LABELS,
    PERIOD_LABELS,
    Catalog,
    Ledger,
    call_record_from_entry,
    format_money,
)
from codelotte.display import args_preview, duration_text, tool_title
from codelotte.session.context import INTERRUPTED_TOOL_NOTE

_RESULT_LIMIT = 2000  # 摘要上限：与 TUI 同一纪律（超限截断并标注），数值按介质（终端窄、网页宽）
_ARG_LIMIT = 120

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1rem 4rem; background: #f6f7f9; color: #1c1e21;
       font: 15px/1.6 -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
main, header, footer { max-width: 920px; margin: 0 auto; }
h1 { font-size: 1.3rem; margin: 0 0 .3rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .8rem; }
.meta { color: #666; font-size: .85rem; }
section { margin-top: 1.5rem; }
.user { background: #e8f1fe; border: 1px solid #cfe0fb; border-radius: 8px;
        padding: .6rem .9rem; margin: 1rem 0 .4rem; }
.user .who { font-weight: 600; color: #1a56b0; margin-bottom: .2rem; }
.assistant { background: #fff; border: 1px solid #e3e5e8; border-radius: 8px;
             padding: .6rem .9rem; margin: 0 0 1rem; }
.text { white-space: pre-wrap; word-break: break-word; }
details { background: #fff; border: 1px solid #e3e5e8; border-radius: 8px;
          margin: .4rem 0; }
details > summary { cursor: pointer; padding: .45rem .9rem; font-family: ui-monospace, Consolas, monospace;
                    font-size: .85rem; color: #444; }
details[open] > summary { border-bottom: 1px solid #eef0f2; }
details > .body { padding: .6rem .9rem; }
details.tool-failed > summary { color: #b3261e; }
details.tool-interrupted > summary { color: #8a6d00; }
pre { margin: 0; padding: .5rem .7rem; background: #f3f4f6; border-radius: 6px;
      white-space: pre-wrap; word-break: break-word; font: 13px/1.5 ui-monospace, Consolas, monospace; }
.reasoning > summary { color: #6b7280; font-style: italic; }
.marker { margin: .6rem 0; padding: .35rem .8rem; border-left: 3px solid #93a3b8;
          background: #eef1f5; border-radius: 0 6px 6px 0; font-size: .85rem; color: #445; }
.marker.warn { border-color: #d29922; background: #fdf5e4; color: #6d4c00; }
.badge { display: inline-block; font-size: .75rem; padding: .05rem .5rem; border-radius: 999px;
         background: #ffefc7; color: #6d4c00; margin-left: .5rem; }
table { border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #e3e5e8;
        border-radius: 8px; overflow: hidden; font-size: .85rem; }
th, td { padding: .45rem .7rem; border-bottom: 1px solid #eef0f2; text-align: left;
         font-variant-numeric: tabular-nums; }
th { background: #f0f2f5; font-weight: 600; }
tr:last-child td { border-bottom: none; }
.total { font-weight: 600; }
.peak { color: #b3261e; } .offpeak { color: #1a7f37; }
.notes { color: #666; font-size: .8rem; margin-top: .6rem; }
footer { margin-top: 3rem; color: #888; font-size: .8rem; border-top: 1px solid #e3e5e8; padding-top: .8rem; }
"""


def _esc(text: object) -> str:
    """一切进 HTML 的文本都走这里（含引号）——不给注入留任何语境。"""
    return html.escape(str(text), quote=True)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _clip(text: str, limit: int) -> str:
    """截断并**标注**（逐字纪律：截了要说，不悄悄改内容）。"""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…（共 {len(text)} 字符，已截断）"


def _stamp(iso: object) -> str:
    """记录里的 UTC 时间戳 → 分钟精度显示（不做时区换算：导出跨机器可复现）。"""
    text = str(iso or "")
    if len(text) >= 16 and text[10] == "T":
        return text[:16].replace("T", " ") + " UTC"
    return text


def _args_text(entry: dict[str, Any]) -> str:
    arguments = entry.get("arguments")
    if isinstance(arguments, str):  # 参数畸形时记录的是原始文本
        return arguments
    return json.dumps(arguments, ensure_ascii=False, indent=2)


def _render_message(entry: dict[str, Any]) -> str:
    role = entry.get("role")
    if role == "user":
        body = _esc(entry.get("content", ""))
        return f'<div class="user"><div class="who">❯ 用户</div><div class="text">{body}</div></div>'
    parts: list[str] = []
    if entry.get("reasoningContent"):
        parts.append(
            '<details class="reasoning"><summary>思考过程</summary>'
            f'<div class="body"><pre>{_esc(entry["reasoningContent"])}</pre></div></details>'
        )
    interrupted = entry.get("stopReason") == "interrupted"
    badge = '<span class="badge">⏸ 本回合在此中断（已落盘）</span>' if interrupted else ""
    content = _esc(entry.get("content", "")) or "（无文本）"
    parts.append(f'<div class="assistant"><div class="text">{content}{badge}</div></div>')
    return "".join(parts)


def _render_tool_call(entry: dict[str, Any], result: dict[str, Any] | None) -> str:
    name = str(entry.get("name", "?"))
    preview = args_preview(name, entry.get("arguments"), limit=_ARG_LIMIT)
    parse_error = entry.get("parseError")
    if parse_error is not None:
        cls, status = "tool-failed", "✗ 参数畸形，未执行"
    elif result is None:
        cls, status = "tool-interrupted", "⏸ 已中断"
    elif result.get("ok"):
        cls, status = "", "✓"
    else:
        cls, status = "tool-failed", "✗"
    if result is None:
        result_body = INTERRUPTED_TOOL_NOTE
    else:
        duration = result.get("durationMs")
        head = duration_text(duration) + "\n" if isinstance(duration, int) else ""
        result_body = head + _clip(str(result.get("content", "")), _RESULT_LIMIT)
    error_note = f"\n（参数畸形：{parse_error}）" if parse_error is not None else ""
    return (
        f'<details class="{cls}"><summary>{_esc(tool_title(name, preview, status))}</summary>'
        f'<div class="body"><div class="args"><pre>{_esc(_clip(_args_text(entry), _RESULT_LIMIT))}</pre></div>'
        f'<div class="result"><pre>{_esc(result_body)}</pre>{_esc(error_note)}</div></div></details>'
    )


def _render_marker(entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if entry.get("type") == "event" and kind == "fork":
        return '<div class="marker">⎇ 分支点：会话从此处 fork 出新分支</div>'
    if entry.get("type") == "event" and kind == "iterationLimit":
        return (
            f'<div class="marker warn">⚠ 达到迭代上限（{_esc(entry.get("iterations", "?"))} 轮），'
            "回合被强制结束</div>"
        )
    typename = _esc(entry.get("type", "?"))
    detail = f"（kind={_esc(kind)}）" if kind else ""
    return f'<div class="marker">记录：{typename}{detail}</div>'


def _render_timeline(entries: list[dict[str, Any]]) -> str:
    call_ids = {e.get("toolCallId") for e in entries if e.get("type") == "tool_call"}
    results = {
        e.get("toolCallId"): e for e in entries if e.get("type") == "tool_result"
    }
    blocks: list[str] = []
    for entry in entries:
        kind = entry.get("type")
        if kind == "message":
            blocks.append(_render_message(entry))
        elif kind == "tool_call":
            blocks.append(_render_tool_call(entry, results.get(entry.get("toolCallId"))))
        elif kind == "tool_result":
            if entry.get("toolCallId") not in call_ids:  # 孤儿结果：照实画出，不藏
                ok = "✓" if entry.get("ok") else "✗"
                blocks.append(
                    f'<div class="marker">工具结果（无对应调用）{ok}：'
                    f"{_esc(_clip(str(entry.get('content', '')), 300))}</div>"
                )
        elif kind == "event":
            blocks.append(_render_marker(entry))
        # session / usage 在页头与成本面板呈现；未知类型如实标注（前向兼容）
        elif kind not in ("session", "usage"):
            blocks.append(_render_marker(entry))
    if not blocks:
        return '<div class="marker">（这条分支还没有记录）</div>'
    return "\n".join(blocks)


def _render_cost_panel(entries: list[dict[str, Any]], catalog: Catalog) -> str:
    usages = [e for e in entries if e.get("type") == "usage"]
    if not usages:
        return '<div class="marker">（这次会话没有记录的模型调用）</div>'
    ledger = Ledger()
    rows: list[str] = []
    for index, entry in enumerate(usages, 1):
        record = call_record_from_entry(entry)
        ledger.record(record)
        period = PERIOD_LABELS.get(record.period, record.period or "—")
        period_cls = "peak" if record.period == "peak" else "offpeak"
        cached = record.cache_hit_tokens + record.cache_miss_tokens
        rate = f"{record.cache_hit_tokens / cached:.0%}" if cached else "—"
        cost_text = (
            format_money(record.cost, catalog.currency) if record.cost is not None else "—"
        )
        rows.append(
            f"<tr><td>{index}</td><td>{_esc(_stamp(entry.get('timestamp')))}</td>"
            f"<td>{_esc(record.model)}</td>"
            f'<td class="{period_cls}">{_esc(period)}</td>'
            f"<td>{record.cache_hit_tokens} / {record.cache_miss_tokens}</td>"
            f"<td>{record.output_tokens}</td><td>{rate}</td><td>{_esc(cost_text)}</td></tr>"
        )
    currency_label = CURRENCY_LABELS.get(catalog.currency, catalog.currency)
    total_cost = format_money(ledger.cost, catalog.currency) if ledger.priced else "—"
    totals = (
        f'<tr class="total"><td colspan="4">合计 {len(ledger.calls)} 次调用（{_esc(currency_label)}）</td>'
        f"<td>{ledger.cache_hit_tokens} / {ledger.cache_miss_tokens}</td>"
        f"<td>{ledger.output_tokens}</td>"
        f"<td>{_esc(ledger.hit_rate_text)}</td><td>{_esc(total_cost)}</td></tr>"
    )
    notes = _price_notes(usages, catalog)
    note_html = (
        f'<div class="notes">价目（{_esc(currency_label)} / M tokens）：'
        + "；".join(_esc(note) for note in notes)
        + "</div>"
    )
    return (
        "<table><thead><tr><th>#</th><th>时间</th><th>模型</th><th>时段</th>"
        "<th>输入 命中/未命中</th><th>输出</th><th>命中率</th><th>费用</th></tr></thead>"
        f"<tbody>{''.join(rows)}{totals}</tbody></table>{note_html}"
    )


def _price_notes(usages: list[dict[str, Any]], catalog: Catalog) -> list[str]:
    """价目脚注（两种格式共用；这里给原文，HTML 侧负责转义）。"""
    notes: list[str] = []
    for model in dict.fromkeys(str(e.get("model", "")) for e in usages):
        info = catalog.models.get(model)
        if info is None:
            notes.append(f"{model}：目录里没有它的价目，只有 token 记录")
            continue
        notes.append(
            f"{model}：命中 {info.cache_hit_price} · 未命中 {info.cache_miss_price} · "
            f"输出 {info.output_price}（高峰价；空闲 = 高峰 × {catalog.off_peak_multiplier}）"
        )
    return notes


def render_session_html(
    entries: list[dict[str, Any]], catalog: Catalog, *, session_name: str
) -> str:
    """会话记录（一条分支）→ 单文件自包含 HTML 文本。

    entries 由调用方读出（load_branch）；本函数不碰文件系统、不掺时间戳，
    同样输入逐字节同输出（票据 08 验收：纯函数性）。
    """
    header = next((e for e in entries if e.get("type") == "session"), {})
    tool_calls = sum(1 for e in entries if e.get("type") == "tool_call")
    usages = sum(1 for e in entries if e.get("type") == "usage")
    meta_bits = [
        f"文件 {_esc(session_name)}",
        f"记录 {len(entries)} 条（工具调用 {tool_calls} 次 · 模型调用 {usages} 次）",
    ]
    if header.get("cwd"):
        meta_bits.append(f"工作目录 {_esc(header['cwd'])}")
    if header.get("version"):
        meta_bits.append(f"codelotte {_esc(header['version'])}")
    if header.get("schema"):
        meta_bits.append(f"schema {_esc(header['schema'])}")
    meta = " · ".join(meta_bits)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>codelotte 会话 · {_esc(session_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
<h1>codelotte 会话回放</h1>
<div class="meta">{meta}</div>
</header>
<main>
<section id="timeline">
<h2>时间线</h2>
{_render_timeline(entries)}
</section>
<section id="cost">
<h2>成本面板</h2>
{_render_cost_panel(entries, catalog)}
</section>
</main>
<footer>内容逐字来自会话记录的直接渲染（不可手工修改）；零外链、断网可开。</footer>
</body>
</html>
"""


# ---- Markdown 格式（终端/编辑器直接读的面）----


def _md_heading(text: object) -> str:
    """标题/标记里的文本压成一行（只折行、不压空格：保留 tool_title 的分隔间距）。

    工具名、会话名等来自模型输出——换行会撑破标题结构，必须折掉；空格无害，保留原样
    才能与 TUI 显示的是同一句话。
    """
    return re.sub(r"[\r\n]+", " ", str(text)).strip()


def _md_cell(value: object) -> str:
    """表格单元格：竖线转义、折行压平（表格结构不能被内容撑破）。"""
    return _md_heading(value).replace("|", "\\|")


def _md_fence(text: str, lang: str = "text") -> str:
    """内容围栏：长度取内容里最长反引号串 + 1（至少 3）——内容里的 ``` 冲不出围栏。"""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{text}\n{ticks}"


def _md_message(entry: dict[str, Any]) -> str:
    role = entry.get("role")
    parts = ["### ❯ 用户" if role == "user" else "### 🤖 助手", ""]
    if entry.get("reasoningContent"):
        parts += ["**🧠 思考过程**", "", _md_fence(str(entry["reasoningContent"])), ""]
    parts.append(str(entry.get("content", "")) or "（无文本）")
    if entry.get("stopReason") == "interrupted":
        parts += ["", "> ⏸ 本回合在此中断（已落盘）"]
    return "\n".join(parts)


def _md_tool_call(entry: dict[str, Any], result: dict[str, Any] | None) -> str:
    name = str(entry.get("name", "?"))
    preview = args_preview(name, entry.get("arguments"), limit=_ARG_LIMIT)
    parse_error = entry.get("parseError")
    if parse_error is not None:
        status = "✗ 参数畸形，未执行"
    elif result is None:
        status = "⏸ 已中断"
    elif result.get("ok"):
        status = "✓"
    else:
        status = "✗"
    arguments = entry.get("arguments")
    parts = [
        f"### {_md_heading(tool_title(name, preview, status))}",
        "",
        _md_fence(_clip(_args_text(entry), _RESULT_LIMIT), "json" if isinstance(arguments, dict) else "text"),
        "",
    ]
    if parse_error is not None:
        parts += [f"> ⚠ 参数畸形：{_md_heading(parse_error)}", ""]
    if result is None:
        parts.append(f"结果：{INTERRUPTED_TOOL_NOTE}")
    else:
        duration = result.get("durationMs")
        label = f"结果{duration_text(duration)}：" if isinstance(duration, int) else "结果："
        parts += [label, "", _md_fence(_clip(str(result.get("content", "")), _RESULT_LIMIT))]
    return "\n".join(parts)


def _md_marker(entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if entry.get("type") == "event" and kind == "fork":
        return "> ⎇ 分支点：会话从此处 fork 出新分支"
    if entry.get("type") == "event" and kind == "iterationLimit":
        return f"> ⚠ 达到迭代上限（{_md_heading(entry.get('iterations', '?'))} 轮），回合被强制结束"
    typename = _md_heading(entry.get("type", "?"))
    detail = f"（kind={_md_heading(kind)}）" if kind else ""
    return f"> 记录：{typename}{detail}"


def _md_timeline(entries: list[dict[str, Any]]) -> str:
    call_ids = {e.get("toolCallId") for e in entries if e.get("type") == "tool_call"}
    results = {e.get("toolCallId"): e for e in entries if e.get("type") == "tool_result"}
    blocks: list[str] = []
    for entry in entries:
        kind = entry.get("type")
        if kind == "message":
            blocks.append(_md_message(entry))
        elif kind == "tool_call":
            blocks.append(_md_tool_call(entry, results.get(entry.get("toolCallId"))))
        elif kind == "tool_result":
            if entry.get("toolCallId") not in call_ids:  # 孤儿结果：照实画出，不藏
                ok = "✓" if entry.get("ok") else "✗"
                clipped = _clip(str(entry.get("content", "")), 300)
                blocks.append(f"> ⚙ 工具结果（无对应调用）{ok}：{_md_cell(clipped)}")
        elif kind == "event":
            blocks.append(_md_marker(entry))
        # session / usage 在页头与成本面板呈现；未知类型如实标注（前向兼容）
        elif kind not in ("session", "usage"):
            blocks.append(_md_marker(entry))
    return "\n\n".join(blocks) if blocks else "（这条分支还没有记录）"


def _md_cost_panel(entries: list[dict[str, Any]], catalog: Catalog) -> str:
    usages = [e for e in entries if e.get("type") == "usage"]
    if not usages:
        return "（这次会话没有记录的模型调用）"
    ledger = Ledger()
    lines = [
        "| # | 时间 | 模型 | 时段 | 输入 命中/未命中 | 输出 | 命中率 | 费用 |",
        "|---|------|------|------|------------------|------|--------|------|",
    ]
    for index, entry in enumerate(usages, 1):
        record = call_record_from_entry(entry)
        ledger.record(record)
        period = PERIOD_LABELS.get(record.period, record.period or "—")
        cached = record.cache_hit_tokens + record.cache_miss_tokens
        rate = f"{record.cache_hit_tokens / cached:.0%}" if cached else "—"
        cost_text = (
            format_money(record.cost, catalog.currency) if record.cost is not None else "—"
        )
        lines.append(
            f"| {index} | {_md_cell(_stamp(entry.get('timestamp')))} | {_md_cell(record.model)} | "
            f"{_md_cell(period)} | {record.cache_hit_tokens} / {record.cache_miss_tokens} | "
            f"{record.output_tokens} | {rate} | {_md_cell(cost_text)} |"
        )
    currency_label = CURRENCY_LABELS.get(catalog.currency, catalog.currency)
    total_cost = format_money(ledger.cost, catalog.currency) if ledger.priced else "—"
    lines.append(
        f"| **合计** | {_md_cell(f'{len(ledger.calls)} 次调用（{currency_label}）')} | | | "
        f"{ledger.cache_hit_tokens} / {ledger.cache_miss_tokens} | {ledger.output_tokens} | "
        f"{_md_cell(ledger.hit_rate_text)} | {_md_cell(total_cost)} |"
    )
    return "\n".join(lines)


def render_session_markdown(
    entries: list[dict[str, Any]], catalog: Catalog, *, session_name: str
) -> str:
    """会话记录（一条分支）→ Markdown 文本（终端/编辑器直接读）。

    纯函数纪律与 HTML 版一致（无时间戳、同输入逐字节同输出）。消息文本**原样输出**
    （助手回答本身就是 markdown，渲染出来更可读）；结构安全靠动态围栏与表格转义。
    """
    header = next((e for e in entries if e.get("type") == "session"), {})
    usages = [e for e in entries if e.get("type") == "usage"]
    tool_calls = sum(1 for e in entries if e.get("type") == "tool_call")
    meta_bits = [
        f"文件 {_md_heading(session_name)}",
        f"记录 {len(entries)} 条（工具调用 {tool_calls} 次 · 模型调用 {len(usages)} 次）",
    ]
    if header.get("cwd"):
        meta_bits.append(f"工作目录 {_md_heading(header['cwd'])}")
    if header.get("version"):
        meta_bits.append(f"codelotte {_md_heading(header['version'])}")
    if header.get("schema"):
        meta_bits.append(f"schema {_md_heading(header['schema'])}")
    currency_label = CURRENCY_LABELS.get(catalog.currency, catalog.currency)
    parts = [
        "# codelotte 会话回放",
        "",
        " · ".join(meta_bits),
        "",
        "## 时间线",
        "",
        _md_timeline(entries),
        "",
        "## 成本面板",
        "",
        _md_cost_panel(entries, catalog),
    ]
    notes = _price_notes(usages, catalog)
    if notes:
        parts += ["", f"价目（{currency_label} / M tokens）：" + "；".join(notes)]
    parts += ["", "---", "", "内容逐字来自会话记录的直接渲染（不可手工修改）。"]
    return "\n".join(parts) + "\n"
