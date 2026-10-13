"""会话存储单元测试（票据 02，session/v1）。"""

from __future__ import annotations

import json
from pathlib import Path

from codelotte.session.store import SessionStore, project_key


def _read_entries(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_start_writes_header_entry(tmp_path: Path) -> None:
    store = SessionStore.start(Path("D:/work/proj"), base_dir=tmp_path / "sessions")
    entries = _read_entries(store.path)
    assert len(entries) == 1
    header = entries[0]
    assert header["type"] == "session"
    assert header["schema"] == "session/v1"
    assert header["cwd"].endswith("proj")
    assert header["id"]


def test_append_chains_parent_ids(tmp_path: Path) -> None:
    store = SessionStore.start(Path("D:/work/proj"), base_dir=tmp_path)
    first = store.append("message", role="user", content="你好")
    second = store.append("message", role="assistant", content="你好！")
    entries = _read_entries(store.path)
    assert entries[1]["parentId"] == entries[0]["id"]
    assert entries[2]["parentId"] == entries[1]["id"]
    assert first["id"] != second["id"]


def test_entries_keep_chinese_readable(tmp_path: Path) -> None:
    store = SessionStore.start(Path("D:/work/proj"), base_dir=tmp_path)
    store.append("message", role="user", content="递归是什么")
    raw = store.path.read_text(encoding="utf-8")
    assert "递归是什么" in raw


def test_file_uses_plain_lf(tmp_path: Path) -> None:
    store = SessionStore.start(Path("D:/work/proj"), base_dir=tmp_path)
    store.append("message", role="user", content="x")
    assert b"\r\n" not in store.path.read_bytes()


def test_project_key_encoding(tmp_path: Path) -> None:
    key = project_key(Path("D:/__WorkSpace__/codelotte"))
    assert key.startswith("--") and key.endswith("--")
    assert "/" not in key and "\\" not in key and ":" not in key


def test_line_breakers_are_escaped_so_records_stay_one_line(tmp_path: Path) -> None:
    store = SessionStore.start(Path("D:/work/proj"), base_dir=tmp_path)
    store.append("message", role="user", content="line1\u2028line2\u0085line3")
    lines = [x for x in store.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2  # 头记录 + 1 条消息，未被 U+2028/U+0085 拆行
    entry = json.loads(lines[1])
    assert entry["content"] == "line1\u2028line2\u0085line3"
