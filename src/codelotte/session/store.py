"""append-only JSONL 会话存储（session/v1）。

一条记录一行、永不改写；每条带 id/parentId 构成链（票据 06 升级为树）。
写入采用「打开-追加-关闭」，进程任何时刻崩溃都不丢已落盘记录；
行尾强制 LF（不用平台默认，保证跨平台可复现）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codelotte import __version__
from codelotte.session.context import messages_from_entries

SCHEMA = "session/v1"

# 合法 JSON 但会被 str.splitlines 按换行拆开的字符（破坏"一条记录一行"不变量）
_LINE_BREAKER_CHARS = (chr(0x2028), chr(0x2029), chr(0x0085))
_BACKSLASH = chr(92)


def project_key(cwd: Path) -> str:
    """把项目路径编码为目录名（沿用 pi 的规则：去首分隔符，斜杠、反斜杠、冒号换成 -）。"""
    trimmed = str(cwd).lstrip("/" + _BACKSLASH)
    for ch in ("/", _BACKSLASH, ":"):
        trimmed = trimmed.replace(ch, "-")
    return f"--{trimmed}--"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _escape_line_breakers(line: str) -> str:
    for ch in _LINE_BREAKER_CHARS:
        if ch in line:
            line = line.replace(ch, _BACKSLASH + f"u{ord(ch):04x}")
    return line


def load_entries(path: Path) -> list[dict[str, Any]]:
    """读整个会话文件的 entry 列表（跳过空行；坏行交给 json 直接暴露，不静默吞）。"""
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def open_session(
    cwd: Path, *, base_dir: Path | None = None, resume: bool = False
) -> tuple["SessionStore", list[dict[str, Any]]]:
    """新会话，或恢复最近一次会话（--continue）。返回 (store, 重建的消息数组)。

    要恢复但没有任何会话文件时抛 FileNotFoundError——调用方转成用户可读的错误。
    """
    if not resume:
        return SessionStore.start(cwd, base_dir=base_dir), []
    path = latest_session_path(cwd, base_dir=base_dir)
    if path is None:
        raise FileNotFoundError(f"没有可继续的会话：{cwd} 下没有历史会话记录")
    return SessionStore.resume(path), messages_from_entries(load_entries(path))


def latest_session_path(cwd: Path, *, base_dir: Path | None = None) -> Path | None:
    """本项目目录下最近活动的会话文件（--continue 用）。没有则返回 None。"""
    base = base_dir if base_dir is not None else Path.home() / ".codelotte" / "sessions"
    directory = base / project_key(cwd)
    if not directory.is_dir():
        return None
    files = list(directory.glob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, p.name))


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_id: str | None = None

    @classmethod
    def start(cls, cwd: Path, *, base_dir: Path | None = None) -> "SessionStore":
        base = (
            base_dir
            if base_dir is not None
            else Path.home() / ".codelotte" / "sessions"
        )
        directory = base / project_key(cwd)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        store = cls(directory / f"{stamp}_{_new_id()[:8]}.jsonl")
        store.append("session", schema=SCHEMA, cwd=str(cwd), version=__version__)
        return store

    @classmethod
    def resume(cls, path: Path) -> "SessionStore":
        """在既有会话文件上继续（--continue）：不新建、不改写，只把 id 链续上。"""
        store = cls(path)
        entries = load_entries(path)
        if entries:
            store._last_id = entries[-1]["id"]
        return store

    def append(self, type_: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "type": type_,
            "id": _new_id(),
            "parentId": self._last_id,
            "timestamp": _now_iso(),
            **fields,
        }
        line = _escape_line_breakers(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        self._last_id = entry["id"]
        return entry
