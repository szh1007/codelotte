"""AgentLoop 事件流测试（票据 05）：增量直通、工具时序、记录先于事件、失败/中断的部分落盘。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from codelotte.loop import MAX_ITERATIONS, AgentLoop, ToolFinished, ToolRequested, TurnEnded
from codelotte.providers.base import ProviderError, StreamEnd, TextDelta, ToolCall, ToolCallsEvent
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import SessionStore, load_entries
from codelotte.tools import default_tools
from tests.fake_client import PAUSE, ScriptedClient, text_turn, tool_turn


def _store(tmp_path: Path) -> SessionStore:
    path = tmp_path / "session.jsonl"
    path.write_text("", encoding="utf-8")
    return SessionStore.resume(path)


def _loop(tmp_path: Path, client: ScriptedClient) -> AgentLoop:
    return AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=_store(tmp_path),
        model="fake-model",
    )


async def _collect(loop: AgentLoop, prompt: str = "任务") -> list[object]:
    return [event async for event in loop.run_turn(prompt)]


def test_text_turn_streams_deltas_then_ends(tmp_path: Path) -> None:
    client = ScriptedClient([text_turn("你好")])
    loop = _loop(tmp_path, client)
    events = asyncio.run(_collect(loop))

    assert isinstance(events[0], TextDelta)
    assert events[0].text == "你好"
    assert isinstance(events[-1], TurnEnded)
    assert events[-1].stop_reason == "stop"
    assert events[-1].hit_iteration_cap is False
    assert events[-1].calls_made == 1

    entries = load_entries(loop.session_path)
    assert [e["type"] for e in entries] == ["message", "message", "usage"]
    assert entries[0]["role"] == "user"
    assert entries[1]["role"] == "assistant"
    assert entries[1]["stopReason"] == "stop"


def test_tool_call_runs_real_tool_and_loops_back(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("读完了")])
    loop = _loop(tmp_path, client)
    events = asyncio.run(_collect(loop))

    requested = [e for e in events if isinstance(e, ToolRequested)]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert len(requested) == len(finished) == 1
    assert requested[0].name == "read"
    assert finished[0].ok is True
    assert "hello" in finished[0].content
    assert isinstance(events[-1], TurnEnded)
    assert events[-1].calls_made == 2

    # 第二次请求：assistant 回传 tool_calls（原始文本）+ tool 消息（真实工具结果）
    second = client.requests[1]
    assert second[1]["tool_calls"][0]["function"]["name"] == "read"
    assert second[2]["role"] == "tool"
    assert "hello" in second[2]["content"]  # 真实工具结果回填

    entries = load_entries(loop.session_path)
    kinds = [e["type"] for e in entries]
    assert kinds == ["message", "message", "usage", "tool_call", "tool_result", "message", "usage"]
    assert entries[3]["env"] == "local"  # 执行环境可审计（SPEC §E）
    assistant_with_call = entries[1]
    assert assistant_with_call["stopReason"] == "tool_calls"
    assert assistant_with_call["toolCalls"][0]["arguments"] == json.dumps({"path": str(target)})


def test_events_arrive_only_after_records_land(tmp_path: Path) -> None:
    """记录是事实源：事件到达时，对应的记录已经在文件里。"""
    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("好了")])
    loop = _loop(tmp_path, client)

    async def scenario() -> None:
        async for event in loop.run_turn("任务"):
            kinds = [e["type"] for e in load_entries(loop.session_path)]
            if isinstance(event, ToolRequested):
                assert "tool_call" in kinds
            elif isinstance(event, ToolFinished):
                assert "tool_result" in kinds
            elif isinstance(event, TurnEnded):
                assert "usage" in kinds  # 终轮的 assistant + usage 已落盘

    asyncio.run(scenario())


def test_provider_failure_stores_partial_then_raises(tmp_path: Path) -> None:
    client = ScriptedClient([[TextDelta("说了一半"), ProviderError("断线了")]])
    loop = _loop(tmp_path, client)

    async def scenario() -> list[object]:
        collected: list[object] = []
        with pytest.raises(ProviderError):
            async for event in loop.run_turn("任务"):
                collected.append(event)
        return collected

    events = asyncio.run(scenario())
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["说了一半"]

    entries = load_entries(loop.session_path)
    assistant = entries[-1]
    assert assistant["role"] == "assistant"
    assert assistant["stopReason"] == "interrupted"
    assert assistant["content"] == "说了一半"


def test_cancellation_stores_partial_and_reraises(tmp_path: Path) -> None:
    """Ctrl+C 中断：已看到的文本先落盘（stopReason=interrupted），再放行取消。"""
    client = ScriptedClient([[TextDelta("已看到的"), PAUSE]])
    loop = _loop(tmp_path, client)

    async def scenario() -> None:
        task = asyncio.create_task(_collect(loop))
        await asyncio.wait_for(client.paused.wait(), 5)  # 确定已卡在流中间
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    entries = load_entries(loop.session_path)
    assistant = entries[-1]
    assert assistant["stopReason"] == "interrupted"
    assert assistant["content"] == "已看到的"


def test_iteration_cap_ends_turn_with_event(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)})])  # 永远请求工具（剧本复用）
    loop = _loop(tmp_path, client)
    events = asyncio.run(_collect(loop))

    ended = events[-1]
    assert isinstance(ended, TurnEnded)
    assert ended.hit_iteration_cap is True
    assert ended.calls_made == MAX_ITERATIONS
    entries = load_entries(loop.session_path)
    assert entries[-1]["kind"] == "iterationLimit"


def test_malformed_call_is_not_executed(tmp_path: Path) -> None:
    bad = ToolCall(id="bad", name="read", arguments='{"path": ', parse_error="参数不是合法 JSON 对象")
    client = ScriptedClient(
        [[ToolCallsEvent((bad,)), StreamEnd("tool_calls")], text_turn("自纠完成")]
    )
    loop = _loop(tmp_path, client)
    events = asyncio.run(_collect(loop))

    requested = [e for e in events if isinstance(e, ToolRequested)]
    assert requested[0].parse_error == "参数不是合法 JSON 对象"
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].ok is False
    assert "错误：工具 read" in finished[0].content

    entries = load_entries(loop.session_path)
    call_entry = next(e for e in entries if e["type"] == "tool_call")
    assert call_entry["parseError"]
    assert call_entry["arguments"] == '{"path": '  # 无法解析时记原始文本
    # 模型看到错误文本并继续（第二个剧本被消费）
    assert client.requests[1][-1]["role"] == "tool"
