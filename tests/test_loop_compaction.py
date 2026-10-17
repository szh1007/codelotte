"""压缩 v1 的 run 级行为（票据 12）：双触发、摘要调用、compaction 落盘、约束重注入与续跑。

剧本化假 Provider 驱动真实 AgentLoop + 真工具；触发用 API usage（第一次响应返回的 input
tokens），窗口用测试注入的小值。纯判定逻辑在 test_compaction.py。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from codelotte.compaction import COMPACTION_CONSTRAINTS, CompactionLimits
from codelotte.loop import AgentLoop, CompactionEvent, TextDelta, RunEnded
from codelotte.permissions import allow_builtin_tools
from codelotte.sandbox import LocalExecutor
from codelotte.session.context import messages_from_entries
from codelotte.session.store import SessionStore, load_branch, load_entries
from codelotte.tools import default_tools
from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn

SUMMARY_OUTPUT = (
    "1. 任务目标：完成测试\n"
    "2. 已完成事项：读过旧文件\n"
    "3. 关键决策及其理由：先读后写\n"
    "4. 活跃约束：不要改工作区外文件\n"
    "5. 涉及文件清单：old.txt\n"
    "6. 当前未解决问题：还没写结果\n"
    "7. 下一步：写 out.txt"
)


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore.start(tmp_path / "project", base_dir=tmp_path / "sessions")


def _seed_history(store: SessionStore, *, input_tokens: int = 600_000) -> None:
    store.append("message", role="user", content="旧任务")
    store.append(
        "message", role="assistant", content="旧回答", model="fake-model", stopReason="stop"
    )
    store.append(
        "usage",
        model="fake-model",
        inputTokens=input_tokens,
        outputTokens=10,
        cacheHitTokens=0,
        cacheMissTokens=0,
        period="peak",
        cost=None,
        currency="CNY",
        requestFingerprint="seed",
    )


def _loop(
    store: SessionStore,
    client: ScriptedClient,
    *,
    context_window: int,
    messages: list[dict] | None = None,
    compaction_limits: CompactionLimits | None = None,
) -> AgentLoop:
    return AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=store,
        model="fake-model",
        catalog=fake_catalog(),
        permissions=allow_builtin_tools(),
        messages=messages,
        context_window=context_window,
        compaction_limits=compaction_limits,
    )


async def _collect(loop: AgentLoop, prompt: str) -> list[object]:
    return [event async for event in loop.run(prompt)]


def _compactions(loop: AgentLoop) -> list[dict]:
    return [entry for entry in load_entries(loop.session_path) if entry["type"] == "compaction"]


def test_soft_trigger_before_a_turn_summarizes_old_history_and_keeps_the_new_prompt(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _seed_history(store)  # 最后 usage = 600k / 1M = 60%
    messages = messages_from_entries(load_branch(store.path))
    client = ScriptedClient(
        [text_turn(SUMMARY_OUTPUT, usage=(20, 10, 0, 0)), text_turn("继续完成")]
    )
    loop = _loop(store, client, context_window=1_000_000, messages=messages)

    events = asyncio.run(_collect(loop, "新任务"))

    compacted = [event for event in events if isinstance(event, CompactionEvent)]
    assert len(compacted) == 1
    event = compacted[0]
    assert event.mode == "soft" and event.utilization == 0.6
    assert event.window == 1_000_000 and event.before_tokens == 600_000
    assert event.after_tokens > 0 and event.warning is None

    entries = _compactions(loop)
    assert len(entries) == 1
    entry = entries[0]
    new_prompt = next(
        record
        for record in load_entries(loop.session_path)
        if record.get("type") == "message" and record.get("content") == "新任务"
    )
    assert entry["summary"] == SUMMARY_OUTPUT
    assert entry["constraints"] == COMPACTION_CONSTRAINTS
    assert entry["firstKeptEntryId"] == new_prompt["id"]
    assert entry["mode"] == "soft" and entry["window"] == 1_000_000
    assert entry["estimatedAfterTokens"] == event.after_tokens
    assert "utilization" not in entry  # 百分比不落盘，展示时由 beforeTokens/window 现算

    # 摘要请求：无工具、最后一条是七项模板指令；旧消息还在，原始记录没被删除
    assert client.tool_schemas[0] is None
    assert "七个标题" in client.requests[0][-1]["content"]
    raw = load_entries(loop.session_path)
    assert any(r.get("content") == "旧任务" for r in raw)
    assert any(r.get("content") == "旧回答" for r in raw)

    # 压缩后的实际请求：system 摘要 + 当前用户消息；旧消息不进请求
    roles = [message["role"] for message in client.requests[1]]
    assert roles == ["system", "user"]
    assert "1. 任务目标" in client.requests[1][0]["content"]
    assert COMPACTION_CONSTRAINTS in client.requests[1][0]["content"]
    assert client.requests[1][1]["content"] == "新任务"
    assert all("旧任务" not in str(message.get("content", "")) for message in client.requests[1])

    # 摘要调用不落成 assistant 消息；usage 照记；恢复装配与实时一致
    assistants = [
        record.get("content")
        for record in load_entries(loop.session_path)
        if record.get("type") == "message" and record.get("role") == "assistant"
    ]
    assert assistants == ["旧回答", "继续完成"]
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages

    ended = events[-1]
    assert isinstance(ended, RunEnded)
    assert ended.calls_made == 2  # 摘要调用 + 正常调用
    assert any(isinstance(event, TextDelta) and event.text == "继续完成" for event in events)


def test_hard_trigger_mid_turn_compacts_before_the_next_request_and_work_continues(
    tmp_path: Path,
) -> None:
    read_target = tmp_path / "old.txt"
    read_target.write_text("old content\n", encoding="utf-8")
    write_target = tmp_path / "out.txt"
    store = _store(tmp_path)
    client = ScriptedClient(
        [
            tool_turn("read", {"path": str(read_target)}, usage=(90, 5, 0, 0)),
            text_turn(SUMMARY_OUTPUT, usage=(20, 10, 0, 0)),
            tool_turn("write", {"path": str(write_target), "content": "OK"}, usage=(10, 5, 0, 0)),
            text_turn("完成"),
        ]
    )
    loop = _loop(store, client, context_window=100)

    events = asyncio.run(_collect(loop, "任务"))

    assert write_target.read_text(encoding="utf-8") == "OK"  # 压缩后工具链继续完成
    compacted = [event for event in events if isinstance(event, CompactionEvent)]
    assert len(compacted) == 1
    event = compacted[0]
    assert event.mode == "hard" and event.utilization == 0.9

    entry = _compactions(loop)[0]
    latest_read_call = next(
        record
        for record in load_entries(loop.session_path)
        if record.get("type") == "message"
        and record.get("role") == "assistant"
        and record.get("toolCalls")
    )
    assert entry["firstKeptEntryId"] == latest_read_call["id"]
    # 请求 0 工具请求 → 请求 1 摘要（无工具）→ 请求 2 压缩后的工具请求 → 请求 3 终答
    assert [schema is not None for schema in client.tool_schemas] == [True, False, True, True]
    post = client.requests[2]
    assert [message["role"] for message in post] == ["system", "user", "assistant", "tool"]
    assert not any(message.get("role") == "user" and message.get("content") == "任务" for message in post)
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages

    ended = events[-1]
    assert isinstance(ended, RunEnded) and ended.calls_made == 4  # 工具/摘要/工具/终答


def test_window_lowered_to_120_percent_still_hard_triggers(tmp_path: Path) -> None:
    """用户把窗口从 1M 下调到 500k：600k/500k = 120% → 硬触发（不等边界）。"""
    store = _store(tmp_path)
    _seed_history(store, input_tokens=600_000)
    messages = messages_from_entries(load_branch(store.path))
    client = ScriptedClient([text_turn(SUMMARY_OUTPUT), text_turn("继续")])
    loop = _loop(store, client, context_window=500_000, messages=messages)

    events = asyncio.run(_collect(loop, "新任务"))

    event = next(event for event in events if isinstance(event, CompactionEvent))
    assert event.mode == "hard" and event.utilization == 1.2
    assert _compactions(loop)[0]["window"] == 500_000


def test_below_soft_threshold_does_not_compact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(
        "usage",
        model="fake-model",
        inputTokens=500,
        outputTokens=1,
        cacheHitTokens=0,
        cacheMissTokens=0,
        period="peak",
        cost=None,
        currency="CNY",
        requestFingerprint="seed",
    )
    client = ScriptedClient([text_turn("答")])
    loop = _loop(store, client, context_window=1000)

    events = asyncio.run(_collect(loop, "任务"))

    assert not [event for event in events if isinstance(event, CompactionEvent)]
    assert len(client.tool_schemas) == 1 and client.tool_schemas[0] is not None
    ended = events[-1]
    assert isinstance(ended, RunEnded) and ended.calls_made == 1


def test_window_smaller_than_the_minimum_keep_set_warns_and_still_compacts(
    tmp_path: Path,
) -> None:
    """最小保留集 + 摘要都超过窗口：压到最小集为止并明确提示（不假装达标）。"""
    big = tmp_path / "big.txt"
    big.write_text("x" * 800, encoding="utf-8")
    store = _store(tmp_path)
    client = ScriptedClient(
        [
            tool_turn("read", {"path": str(big)}, usage=(90, 5, 0, 0)),
            text_turn(SUMMARY_OUTPUT),
            text_turn("完成"),
        ]
    )
    loop = _loop(store, client, context_window=100)

    events = asyncio.run(_collect(loop, "任务"))

    event = next(event for event in events if isinstance(event, CompactionEvent))
    assert event.mode == "hard"
    assert event.after_tokens > event.window
    assert event.warning is not None and "最小保留集" in event.warning
    entry = _compactions(loop)[0]
    assert entry["warning"] == event.warning


def test_configured_thresholds_control_the_trigger(tmp_path: Path) -> None:
    """settings.json 的 compaction*Threshold 必须真的进触发判定（票据 13 回归发现）。

    600k / 1M = 60%：默认软阈值（60%）会压缩；用户把软阈值调到 70% 后不该压缩。
    """
    store = _store(tmp_path)
    _seed_history(store, input_tokens=600_000)
    messages = messages_from_entries(load_branch(store.path))
    client = ScriptedClient([text_turn("继续")])
    loop = _loop(
        store,
        client,
        context_window=1_000_000,
        messages=messages,
        compaction_limits=CompactionLimits(soft=0.7, hard=0.9),
    )

    events = asyncio.run(_collect(loop, "新任务"))

    assert not [event for event in events if isinstance(event, CompactionEvent)]
    assert len(client.requests) == 1
