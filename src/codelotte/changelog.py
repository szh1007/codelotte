"""启动时的更新提示（settings.json 的 lastChangelogVersion，pi 的 what's-new 行为）。

CHANGELOG.md 在仓库根（随仓库走；从安装包运行时读不到就静默跳过）；每条以
`## [x.y.z]` 开头。落后当前版本就提示新增条目，一致/回退/首次运行都不提示——
版本号是否写回由 config.record_changelog_version 负责，本模块只做纯文本判断。
"""

from __future__ import annotations

import re
from pathlib import Path

CHANGELOG_PATH = Path(__file__).resolve().parents[2] / "CHANGELOG.md"

_HEADING = re.compile(r"^##\s+\[?(\d+(?:\.\d+)*)\]?")


def _version_key(text: str) -> tuple[int, ...]:
    """版本号 → 可比较的元组；认不出来（含 "1.0.0rc1" 这类带后缀的）返回 ()，不提示、不猜。"""
    numbers: list[int] = []
    for part in text.strip().lstrip("vV").split("."):
        if not part.isdigit():
            return ()
        numbers.append(int(part))
    return tuple(numbers)


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """补零到同段数再比（"0.1" 与 "0.1.0" 等价，不因写法差异误报更新）。"""
    size = max(len(left), len(right))
    padded_left = left + (0,) * (size - len(left))
    padded_right = right + (0,) * (size - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


def should_record(stored: str | None, current: str) -> bool:
    """版本水位该不该更新：仅"首次（无值）"或"落后 current"才写。

    一致不写（幂等）；**回退不写**——跑过新版本再回到旧版，水位不能被拉低，否则再升级会
    重放整段更新内容（审查修正：原来只挡相等，回退也被改写）。认不出的值当成"坏了"修正为
    current（手误/乱码自愈），这是唯一的例外。
    """
    if stored is None:
        return True
    stored_key, current_key = _version_key(stored), _version_key(current)
    if not stored_key or not current_key:
        return True  # 认不出来：修成当前版本
    return _compare(stored_key, current_key) < 0


def _entries(text: str) -> list[tuple[str, str]]:
    """CHANGELOG.md → [(版本号, 正文)]（按文件顺序）。"""
    entries: list[tuple[str, str]] = []
    version: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            if version is not None:
                entries.append((version, "\n".join(body).strip()))
            version, body = heading.group(1), []
        elif version is not None:
            body.append(line)
    if version is not None:
        entries.append((version, "\n".join(body).strip()))
    return entries


def changelog_notice(
    stored: str | None, current: str, *, path: Path | None = None
) -> str | None:
    """stored 落后 current 时返回"更新内容"文本；其余情况（首次运行/一致/回退/读不到
    CHANGELOG）返回 None。"""
    if stored is None:
        return None  # 首次运行：静默记下当前版本，不倒历史
    stored_key, current_key = _version_key(stored), _version_key(current)
    if not stored_key or not current_key or _compare(stored_key, current_key) >= 0:
        return None
    changelog = path if path is not None else CHANGELOG_PATH
    try:
        text = changelog.read_text(encoding="utf-8")
    except OSError:
        return None
    newer = [
        (version, body)
        for version, body in _entries(text)
        if (entry_key := _version_key(version))
        and _compare(stored_key, entry_key) < 0
        and _compare(entry_key, current_key) <= 0
    ]
    if not newer:
        return None
    lines = [f"更新内容（{stored} → {current}）："]
    for version, body in newer:
        lines.append(f"【{version}】")
        lines.extend(line for line in body.splitlines() if line.strip())
    return "\n".join(lines)
