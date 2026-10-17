"""两类报表共用的文本小工具（压缩回归 / 通用测评）。

单独成模块避免 report.py 与 eval_report.py 各抄一份（审查基线：Duplicated Code）。
"""

from __future__ import annotations

from pathlib import Path

from codelotte.cost import PERIOD_LABELS


def rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "—"
    return f"{numerator}/{denominator} ({numerator / denominator:.0%})"


def short(text: str, limit: int = 240) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def relative(path: str | None, run_dir: Path) -> str:
    if not path:
        return "—"
    try:
        return Path(path).resolve().relative_to(run_dir.resolve()).as_posix()
    except (ValueError, OSError):
        return path


def dirty_text(dirty: bool | None, diff_sha: str | None) -> str:
    if dirty is None:
        return "未知（git 命令失败）"
    if not dirty:
        return "否"
    return f"是（指纹 {diff_sha or 'unknown'}）"


def periods_text(periods: tuple[tuple[str, int], ...]) -> str:
    if not periods:
        return "—"
    return " · ".join(
        f"{PERIOD_LABELS.get(period, period)} {count}" for period, count in periods
    )
