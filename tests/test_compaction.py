"""压缩 v1 的纯逻辑（票据 12）：双触发、任务边界、最小保留集、摘要请求与压缩后装配。

触发判定的输入是活动分支 entry 列表 + 上一次请求的 usage；不碰网络、不碰文件。
端到端（摘要调用、compaction 落盘、TUI/导出）在 test_loop_compaction / test_export。
"""

from __future__ import annotations

from typing import Any

import pytest

from codelotte.compaction import (
    HARD_THRESHOLD,
    SOFT_THRESHOLD,
    SUMMARY_SECTIONS,
    build_compaction_messages,
    build_summary_messages,
    context_tokens_from_entries,
    estimate_tokens,
    is_git_commit_command,
    minimum_keep_index,
    plan_compaction,
    task_boundaries,
)
from codelotte.session.context import messages_from_entries
from codelotte.session.store import SessionError


def _entry(entry_id: str, type_: str, **fields: Any) -> dict[str, Any]:
    return {"id": entry_id, "parentId": None, "type": type_, **fields}


def _user(entry_id: str, content: str = "任务") -> dict[str, Any]:
    return _entry(entry_id, "message", role="user", content=content)


def _assistant(entry_id: str, *, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return _entry(
        entry_id,
        "message",
        role="assistant",
        content="",
        stopReason="tool_calls" if tool_calls else "stop",
        toolCalls=tool_calls,
    )


def _bash_call(entry_id: str, call_id: str, command: str) -> dict[str, Any]:
    return _entry(entry_id, "tool_call", toolCallId=call_id, name="bash", arguments={"command": command})


def _result(entry_id: str, call_id: str, *, ok: bool = True) -> dict[str, Any]:
    return _entry(entry_id, "tool_result", toolCallId=call_id, name="bash", ok=ok, content="ok")


def _branch() -> list[dict[str, Any]]:
    return [
        _entry("s", "session"),
        _user("u1", "第一个任务"),
        _assistant("a1", tool_calls=[{"id": "c1", "name": "bash", "arguments": "{}"}]),
        _bash_call("tc1", "c1", "git commit -m done"),
        _result("tr1", "c1"),
        _user("u2", "第二个任务"),
        _assistant("a2"),
    ]


def test_estimate_tokens_is_chars_over_four_including_tool_arguments() -> None:
    messages = [
        {"role": "user", "content": "x" * 40},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"arguments": "y" * 40}}]},
    ]
    assert estimate_tokens(messages) == 20


def test_git_commit_detection_is_command_segment_aware() -> None:
    assert is_git_commit_command("git commit -m msg")
    assert is_git_commit_command("cd repo && git -C . commit --amend")
    assert is_git_commit_command("git add . && git commit")
    assert not is_git_commit_command("git log --grep=commit")
    assert not is_git_commit_command("git commit-tree deadbeef")
    assert not is_git_commit_command("echo git commit")
    assert not is_git_commit_command("git status")


def test_task_boundaries_are_user_messages_and_successful_git_commits() -> None:
    entries = _branch()
    # 1 = 第一条用户消息；2 = 声明 git commit 的 assistant；5 = 第二条用户消息
    assert task_boundaries(entries) == [1, 2, 5]

    failed = _branch()
    failed[4]["ok"] = False
    assert task_boundaries(failed) == [1, 5]


def test_minimum_keep_set_is_the_latest_turn_or_model_round() -> None:
    assert minimum_keep_index([_user("u")]) == 0
    assert minimum_keep_index([_user("u"), _assistant("a")]) == 1
    entries = [_user("u"), _assistant("a"), _bash_call("tc", "c", "ls"), _result("tr", "c")]
    assert minimum_keep_index(entries) == 1  # 最近一轮 = 最后一条 assistant 及其工具链
    assert minimum_keep_index([_entry("s", "session")]) is None
    assert minimum_keep_index([_entry("s", "session"), _entry("c", "compaction")]) is None


def test_soft_trigger_compacts_at_the_latest_task_boundary() -> None:
    entries = _branch()
    decision = plan_compaction(entries, input_tokens=600_000, context_window=1_000_000)
    assert decision is not None
    assert decision.mode == "soft"
    assert decision.cut_index == 5  # 最近的用户消息；不切当前最新一轮
    assert decision.first_kept_entry_id == "u2"
    assert decision.utilization == 0.6

    assert plan_compaction(entries, input_tokens=590_000, context_window=1_000_000) is None


def test_hard_trigger_cuts_at_the_minimum_keep_set_even_without_a_boundary() -> None:
    entries = [_user("u"), _assistant("a1"), _bash_call("tc", "c", "ls"), _result("tr", "c")]
    decision = plan_compaction(entries, input_tokens=850_000, context_window=1_000_000)
    assert decision is not None
    assert decision.mode == "hard"
    assert decision.cut_index == 1  # 最近一条 assistant（不是任务边界）
    assert decision.first_kept_entry_id == "a1"


def test_utilization_above_100_percent_is_still_a_hard_trigger() -> None:
    """用户中途把窗口从 80w 下调到 50w：600k/50w = 120% 仍要触发。"""
    entries = _branch()
    decision = plan_compaction(entries, input_tokens=600_000, context_window=500_000)
    assert decision is not None
    assert decision.mode == "hard"
    assert decision.utilization == 1.2


def test_soft_trigger_waits_when_there_is_no_new_task_boundary() -> None:
    entries = [
        _entry("s", "session"),
        _assistant("a1"),
        _bash_call("tc", "c", "ls"),
        _result("tr", "c"),
    ]
    assert plan_compaction(entries, input_tokens=700_000, context_window=1_000_000) is None
    hard = plan_compaction(entries, input_tokens=900_000, context_window=1_000_000)
    assert hard is not None and hard.mode == "hard"


def test_no_compaction_after_a_compaction_without_new_rounds() -> None:
    entries = [
        _entry("s", "session"),
        _user("u"),
        _assistant("a"),
        _entry("cmp", "compaction", summary="旧摘要", firstKeptEntryId="a", estimatedAfterTokens=100),
    ]
    assert plan_compaction(entries, input_tokens=2_000_000, context_window=1_000_000) is None


def test_boundaries_before_the_last_compaction_are_not_reused() -> None:
    entries = [
        _entry("s", "session"),
        _user("u1"),
        _assistant("a1"),
        _entry("cmp", "compaction", summary="旧摘要", firstKeptEntryId="a1", estimatedAfterTokens=100),
        _user("u2"),
        _assistant("a2", tool_calls=[{"id": "c2", "name": "bash", "arguments": "{}"}]),
        _bash_call("tc2", "c2", "git commit -m two"),
        _result("tr2", "c2"),
        _user("u3"),
        _assistant("a3"),
    ]
    decision = plan_compaction(entries, input_tokens=650_000, context_window=1_000_000)
    assert decision is not None and decision.mode == "soft"
    assert decision.cut_index == 8  # 只考虑上次压缩之后的边界
    assert decision.first_kept_entry_id == "u3"


def test_context_tokens_prefers_the_last_usage_or_compaction_estimate() -> None:
    assert context_tokens_from_entries([_entry("s", "session")]) == 0
    entries = [
        _entry("u", "usage", inputTokens=600_000),
        _entry("cmp", "compaction", estimatedAfterTokens=250_000),
        _entry("u2", "usage", inputTokens=300_000),
    ]
    assert context_tokens_from_entries(entries) == 300_000
    assert context_tokens_from_entries(entries[:2]) == 250_000


def test_summary_request_keeps_the_prefix_and_asks_for_seven_sections() -> None:
    prefix = [{"role": "user", "content": "旧任务"}]
    request = build_summary_messages(prefix)
    assert request[0] == prefix[0]
    instruction = request[-1]
    assert instruction["role"] == "user"
    for section in SUMMARY_SECTIONS:
        assert section in instruction["content"]


def test_compacted_context_has_summary_and_constraints_before_the_kept_round() -> None:
    kept = [{"role": "assistant", "content": "继续"}]
    messages = build_compaction_messages("摘要正文", "硬约束正文", kept)
    assert messages[0]["role"] == "system"
    assert "摘要正文" in messages[0]["content"]
    assert "硬约束正文" in messages[0]["content"]  # 摘要之外单独重注入
    assert messages[1]["role"] == "user"  # kept 以 assistant 开头时补一条 user 桥
    assert messages[2:] == kept


def test_compacted_context_does_not_add_a_bridge_when_kept_starts_with_user() -> None:
    kept = [{"role": "user", "content": "新任务"}]
    messages = build_compaction_messages("摘要", "约束", kept)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1] == kept[0]


def test_thresholds_are_the_documented_sixty_and_eighty_five() -> None:
    assert SOFT_THRESHOLD == 0.60
    assert HARD_THRESHOLD == 0.85


def test_compaction_entry_replaces_old_messages_but_keeps_the_suffix() -> None:

    entries = [
        _entry("s", "session"),
        _user("u1", "旧任务"),
        _entry("a1", "message", role="assistant", content="旧回答"),
        _user("u2", "保留的任务"),
        _entry(
            "a2",
            "message",
            role="assistant",
            content="",
            stopReason="tool_calls",
            toolCalls=[{"id": "c2", "name": "read", "arguments": '{"path": "x"}'}],
        ),
        _entry("tc2", "tool_call", toolCallId="c2", name="read", arguments={"path": "x"}),
        _entry("tr2", "tool_result", toolCallId="c2", name="read", ok=True, content="文件内容"),
        _entry(
            "cmp",
            "compaction",
            summary="摘要正文",
            firstKeptEntryId="u2",
            constraints="硬约束正文",
            estimatedAfterTokens=100,
        ),
    ]
    messages = messages_from_entries(entries)
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool"]
    assert messages[0]["role"] == "system"
    assert "摘要正文" in messages[0]["content"] and "硬约束正文" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "保留的任务"}
    assert messages[3]["content"] == "文件内容"
    assert all("旧" not in str(message.get("content", "")) for message in messages)


def test_entries_after_the_compaction_are_replayed_on_top() -> None:

    entries = [
        _entry("s", "session"),
        _user("u1", "旧任务"),
        _entry(
            "cmp",
            "compaction",
            summary="摘要",
            firstKeptEntryId="u1",
            constraints="约束",
            estimatedAfterTokens=50,
        ),
        _user("u2", "压缩后继续"),
        _entry("a2", "message", role="assistant", content="完成"),
    ]
    messages = messages_from_entries(entries)
    assert [message["role"] for message in messages] == ["system", "user", "user", "assistant"]
    assert messages[1] == {"role": "user", "content": "旧任务"}  # 保留段以 user 开头，不加桥
    assert messages[2]["content"] == "压缩后继续"


def test_only_the_latest_compaction_applies() -> None:

    entries = [
        _entry("s", "session"),
        _user("u1", "第一段"),
        _entry("a1", "message", role="assistant", content="回答一"),
        _entry("cmp1", "compaction", summary="旧摘要", firstKeptEntryId="a1", constraints="约束"),
        _user("u2", "第二段"),
        _entry("a2", "message", role="assistant", content="回答二"),
        _entry("cmp2", "compaction", summary="新摘要", firstKeptEntryId="u2", constraints="约束"),
    ]
    messages = messages_from_entries(entries)
    assert "新摘要" in messages[0]["content"] and "旧摘要" not in messages[0]["content"]
    assert [message["role"] for message in messages] == ["system", "user", "assistant"]


def test_broken_first_kept_pointer_is_a_readable_session_error() -> None:
    missing = [
        _entry("s", "session"),
        _user("u"),
        _entry("cmp", "compaction", summary="摘要", firstKeptEntryId="nope"),
    ]
    with pytest.raises(SessionError, match="firstKeptEntryId"):
        messages_from_entries(missing)

    future = [
        _entry("s", "session"),
        _user("u"),
        _entry("cmp", "compaction", summary="摘要", firstKeptEntryId="u2"),
        _user("u2", "在压缩之后"),
    ]
    with pytest.raises(SessionError, match="压缩"):
        messages_from_entries(future)


def test_thresholds_are_configurable_for_the_same_context() -> None:
    """同样的 50%：默认 60% 不压；软 50%/硬 75% 时软触发；75% 时硬触发。"""
    entries = _branch()
    assert plan_compaction(entries, input_tokens=500_000, context_window=1_000_000) is None
    soft = plan_compaction(
        entries,
        input_tokens=500_000,
        context_window=1_000_000,
        soft=0.5,
        hard=0.75,
    )
    assert soft is not None and soft.mode == "soft"
    hard = plan_compaction(
        entries,
        input_tokens=750_000,
        context_window=1_000_000,
        soft=0.5,
        hard=0.75,
    )
    assert hard is not None and hard.mode == "hard"


def test_compaction_limits_take_settings_overrides_with_defaults() -> None:
    from codelotte.compaction import CompactionLimits
    from codelotte.config import Settings

    assert CompactionLimits.from_settings(Settings()) == CompactionLimits()
    limits = CompactionLimits.from_settings(
        Settings(compaction_soft_threshold=0.5, compaction_hard_threshold=0.8)
    )
    assert limits == CompactionLimits(soft=0.5, hard=0.8)
    one_sided = CompactionLimits.from_settings(
        Settings(compaction_soft_threshold=0.5)
    )
    assert one_sided == CompactionLimits(soft=0.5, hard=0.85)
