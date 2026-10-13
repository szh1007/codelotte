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

SCHEMA = "session/v1"


def project_key(cwd: Path) -> str:
    """把项目路径编码为目录名（沿用 pi 的规则：去首分隔符，斜杠、反斜杠、冒号换成 -）。"""
    trimmed = str(cwd).lstrip("/\\")
    for ch in ("/", "\\", ":"):
        trimmed = trimmed.replace(ch, "-")
    return f"--{trimmed}--"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_id: str | None = None

    @classmethod
    def start(cls, cwd: Path, *, base_dir: Path | None = None) -> "SessionStore":
        base = base_dir if base_dir is not None else Path.home() / ".codelotte" / "sessions"
        directory = base / project_key(cwd)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        store = cls(directory / f"{stamp}_{_new_id()[:8]}.jsonl")
        store.append("session", schema=SCHEMA, cwd=str(cwd), version=__version__)
        return store

    def append(self, type_: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "type": type_,
            "id": _new_id(),
            "parentId": self._last_id,
            "timestamp": _now_iso(),
            **fields,
        }
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        self._last_id = entry["id"]
        return entry
