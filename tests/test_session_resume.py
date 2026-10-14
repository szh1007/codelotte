"""会话恢复（票据 05 --continue 的地基）：最近会话定位、追加恢复、消息重建的确定性。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from codelotte.session.context import messages_from_entries
from codelotte.session.store import (
    SessionStore,
    latest_session_path,
    load_entries,
    open_session,
)


def test_start_then_resume_continues_same_file_and_chain(tmp_path: Path) -> None:
    store = SessionStore.start(tmp_path / "proj", base_dir=tmp_path / "sessions")
    store.append("message", role="user", content="第一问")
    before = load_entries(store.path)

    resumed = SessionStore.resume(store.path)
    resumed.append("message", role="assistant", content="第一答")

    entries = load_entries(store.path)
    assert [e["type"] for e in entries] == ["session", "message", "message"]
    assert entries[2]["parentId"] == before[-1]["id"]  # id 链续上，不重开文件


def test_latest_session_path_picks_the_most_recent(tmp_path: Path) -> None:
    base = tmp_path / "sessions"
    cwd = tmp_path / "proj"
    assert latest_session_path(cwd, base_dir=base) is None  # 目录都不存在

    store = SessionStore.start(cwd, base_dir=base)
    older = store.path
    newer = store.path.with_name("20990101T000000Z_newer01.jsonl")
    newer.write_text("", encoding="utf-8")
    now = time.time()
    os.utime(older, (now - 10, now - 10))
    os.utime(newer, (now, now))
    assert latest_session_path(cwd, base_dir=base) == newer


def test_open_session_fresh_and_resume(tmp_path: Path) -> None:
    base = tmp_path / "sessions"
    cwd = tmp_path / "proj"

    store, messages = open_session(cwd, base_dir=base)
    assert messages == []
    assert load_entries(store.path)[0]["type"] == "session"

    with pytest.raises(FileNotFoundError):
        open_session(cwd / "elsewhere", base_dir=base, resume=True)

    store.append("message", role="user", content="你好")
    resumed, messages = open_session(cwd, base_dir=base, resume=True)
    assert resumed.path == store.path
    assert messages == [{"role": "user", "content": "你好"}]


def _entries() -> list[dict]:
    return [
        {"type": "session", "schema": "session/v1"},
        {"type": "message", "role": "user", "content": "第一问"},
        {
            "type": "message",
            "role": "assistant",
            "content": "",
            "model": "m",
            "stopReason": "tool_calls",
            "reasoningContent": "先想",
            "toolCalls": [{"id": "c1", "name": "read", "arguments": '{"path": "a.txt"}'}],
        },
        {"type": "usage"},
        {"type": "tool_call", "toolCallId": "c1", "name": "read", "arguments": {"path": "a.txt"}},
        {"type": "tool_result", "toolCallId": "c1", "name": "read", "ok": True, "content": "文件内容"},
        {"type": "message", "role": "assistant", "content": "答完了", "model": "m", "stopReason": "stop"},
        {"type": "usage"},
    ]


def test_messages_rebuilt_exactly() -> None:
    messages = messages_from_entries(_entries())
    assert messages == [
        {"role": "user", "content": "第一问"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "先想",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": '{"path": "a.txt"}'}}
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "文件内容"},
        {"role": "assistant", "content": "答完了"},
    ]
    # 键序固定（前缀缓存逐字节稳定的前提）
    assert list(messages[1].keys()) == ["role", "content", "reasoning_content", "tool_calls"]
    # 确定性：同一份记录装配两次逐字节一致
    assert json.dumps(messages, ensure_ascii=False) == json.dumps(
        messages_from_entries(_entries()), ensure_ascii=False
    )


def test_interrupted_assistant_is_skipped() -> None:
    entries = [
        {"type": "message", "role": "user", "content": "问题"},
        {"type": "message", "role": "assistant", "content": "说到一半", "stopReason": "interrupted"},
    ]
    assert messages_from_entries(entries) == [{"role": "user", "content": "问题"}]


def test_missing_tool_result_gets_interrupted_note() -> None:
    """回合在工具执行中被中断：协议要求每个 tool_call 都有 tool 消息，缺的补中断说明。"""
    entries = [
        {"type": "message", "role": "user", "content": "问题"},
        {
            "type": "message",
            "role": "assistant",
            "content": "",
            "stopReason": "tool_calls",
            "toolCalls": [
                {"id": "a", "name": "bash", "arguments": "{}"},
                {"id": "b", "name": "bash", "arguments": "{}"},
            ],
        },
        {"type": "tool_result", "toolCallId": "a", "name": "bash", "ok": True, "content": "输出"},
        # b 没有结果：回合在这里被中断
        {"type": "message", "role": "user", "content": "继续"},
    ]
    messages = messages_from_entries(entries)
    assert [m["role"] for m in messages] == ["user", "assistant", "tool", "tool", "user"]
    assert messages[2]["tool_call_id"] == "a"
    assert messages[3]["tool_call_id"] == "b"
    assert "中断" in messages[3]["content"]
