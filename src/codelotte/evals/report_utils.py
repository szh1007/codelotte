"""两类报表共用的文本小工具（压缩回归 / 通用测评）。

单独成模块避免 report.py 与 eval_report.py 各抄一份（审查基线：Duplicated Code）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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


def display_path(path: Path) -> str:
    """报告里优先显示仓库相对路径（绝对路径不可移植）。"""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def report_paths(root: Path) -> list[Path]:
    """run 目录（或 runs 根目录）下的 report.json；文件也接受。

    对照/自检的父报表没有 cases，真正的案例在 `harnesses/<组>/report.json`；
    递归查找能同时覆盖两种布局。
    """
    if root.is_file():
        return [root] if root.name == "report.json" else []
    if not root.is_dir():
        return []
    paths = sorted(root.rglob("report.json"))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_report(path: Path) -> Mapping[str, Any]:
    """读 report.json；坏文件/非对象直接抛 ValueError（带路径上下文）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"跑数报表读不动：{path}（{exc}）") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"跑数报表不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"跑数报表顶层应是对象：{path}")
    return payload
