"""死循环三层防御的回合级行为（票据 11）：拦截 → 记录 → 提醒模型 / 熔断 / 终止。

剧本化假 Provider 驱动真实 AgentLoop：断言事件流、会话记录、回传模型的消息与恢复一致性。
纯状态机（阈值/计数/误报边界）在 test_guardrails.py。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from codelotte.guardrails import (
    GUARD_CIRCUIT,
    GUARD_REINJECT,
    GUARD_REPEAT,
    GUARD_STAGNATION,
    GUARD_TERMINATE,
    GuardrailLimits,
)
from codelotte.loop import AgentLoop, GuardrailTriggered, ToolFinished, TurnEnded
from codelotte.permissions import ALLOW, DENY, PermissionLayer, Rule
from codelotte.providers.base import StreamEnd, StreamUsage, ToolCall, ToolCallsEvent, UsageEvent
from codelotte.session.context import messages_from_entries
from codelotte.session.store import SessionStore, load_branch, load_entries
from codelotte.tools import Tool, ToolError
from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn


def _store(tmp_path: Path) -> SessionStore:
    path = tmp_path / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return SessionStore.resume(path)


def _loop(
    tmp_path: Path,
    client: ScriptedClient,
    tools: tuple[Tool, ...],
    *,
    limits: GuardrailLimits | None = None,
    permissions: PermissionLayer | None = None,
) -> AgentLoop:
    if permissions is None:
        permissions = PermissionLayer(
            [
                Rule(tool=tool.name, pattern=None, verdict=ALLOW, source="test", text=tool.name)
                for tool in tools
            ]
        )
    return AgentLoop(
        client=client,
        tools=tools,
        store=_store(tmp_path),
        model="fake-model",
        catalog=fake_catalog(),
        permissions=permissions,
        guardrail_limits=limits,
    )


async def _collect(loop: AgentLoop, prompt: str = "把计数器跑一遍") -> list[object]:
    return [event async for event in loop.run_turn(prompt)]


def _tool(name: str, handler: Any) -> Tool:
    return Tool(name=name, description="", parameters={"type": "object"}, handler=handler)


def _counter_tool(calls: list[int]) -> Tool:
    async def handler(_args: dict[str, Any]) -> str:
        calls.append(1)
        return f"run {len(calls)}"

    return _tool("counter", handler)


def _constant_tool(calls: list[int]) -> Tool:
    async def handler(_args: dict[str, Any]) -> str:
        calls.append(1)
        return "same"

    return _tool("constant", handler)


def _boom_tool(calls: list[int]) -> Tool:
    async def handler(_args: dict[str, Any]) -> str:
        calls.append(1)
        raise ToolError("boom")

    return _tool("boom", handler)


def _echo_tool(calls: list[int]) -> Tool:
    async def handler(args: dict[str, Any]) -> str:
        calls.append(1)
        return f"echo {args['n']}"

    return _tool("echo", handler)


def _guardrail_entries(loop: AgentLoop) -> list[dict[str, Any]]:
    return [
        entry
        for entry in load_entries(loop.session_path)
        if entry.get("type") == "event" and entry.get("kind") == "guardrail"
    ]


def test_repeat_interception_is_recorded_and_planning_reinjects_the_goal(
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    client = ScriptedClient(
        [
            tool_turn("counter", {}, call_id="c1"),
            tool_turn("counter", {}, call_id="c2"),
            tool_turn("counter", {}, call_id="c3"),
            text_turn("我换个做法完成了"),
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_counter_tool(calls),),
        limits=GuardrailLimits(
            repeat=3, stagnation=99, failure=99, planning=2
        ),
    )
    events = asyncio.run(_collect(loop))

    # 第 3 次相同调用被拦：只执行了前两次，结果以错误文本回给模型
    assert len(calls) == 2
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert [(e.layer, e.guard) for e in triggered] == [
        ("tool", GUARD_REPEAT),
        ("planning", GUARD_REINJECT),
    ]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [e.ok for e in finished] == [True, True, False]
    assert "守护拦截" in finished[-1].content

    entries = _guardrail_entries(loop)
    assert [(e["layer"], e["guard"]) for e in entries] == [
        ("tool", GUARD_REPEAT),
        ("planning", GUARD_REINJECT),
    ]
    tool_event = entries[0]
    assert tool_event["count"] == 3 and tool_event["threshold"] == 3
    assert tool_event["tool"] == "counter" and tool_event["toolCallId"] == "c3"
    assert "任务目标" in entries[1]["injected"] and "硬约束" in entries[1]["injected"]

    # 规划层提醒作为 user 消息追加在工具结果之后，模型下一轮看得到
    reinjected = client.requests[3][-1]
    assert reinjected["role"] == "user"
    assert "规划层提醒" in reinjected["content"] and "把计数器跑一遍" in reinjected["content"]

    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop is None
    # 恢复路径（--continue）重建的消息数组与实时逐条一致（注入的提醒不能丢）
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages


def test_identical_results_are_intercepted_as_stagnation(tmp_path: Path) -> None:
    calls: list[int] = []
    client = ScriptedClient(
        [
            tool_turn("constant", {}, call_id="c1"),
            tool_turn("constant", {}, call_id="c2"),
            tool_turn("constant", {}, call_id="c3"),
            text_turn("换个做法"),
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_constant_tool(calls),),
        limits=GuardrailLimits(repeat=99, stagnation=2, failure=99, planning=2),
    )
    events = asyncio.run(_collect(loop))

    assert len(calls) == 2
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert triggered[0].layer == "tool" and triggered[0].guard == GUARD_STAGNATION
    assert "没有进展" in triggered[0].message
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[-1].ok is False and "没有进展" in finished[-1].content


def test_consecutive_failures_circuit_break_with_a_summary_call(tmp_path: Path) -> None:
    calls: list[int] = []
    client = ScriptedClient(
        [
            tool_turn("boom", {}, call_id="c1"),
            tool_turn("boom", {}, call_id="c2"),
            tool_turn("boom", {}, call_id="c3"),
            text_turn("总结：工具一直失败，卡在 boom。"),
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_boom_tool(calls),),
        limits=GuardrailLimits(repeat=99, stagnation=99, failure=3, planning=99),
    )
    events = asyncio.run(_collect(loop))

    assert len(calls) == 3
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [e.ok for e in finished] == [False, False, False]
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert [(e.layer, e.guard) for e in triggered] == [("reasoning", GUARD_CIRCUIT)]

    # 熔断后的总结调用禁用工具；提醒要求模型总结现状
    assert client.tool_schemas[:3] == [client.tool_schemas[0]] * 3
    assert client.tool_schemas[0] is not None
    assert client.tool_schemas[3] is None
    reminder = client.requests[3][-1]
    assert reminder["role"] == "user" and "推理层熔断" in reminder["content"]
    assert "把计数器跑一遍" in reminder["content"]

    ended = events[-1]
    assert isinstance(ended, TurnEnded)
    assert ended.guardrail_stop == GUARD_CIRCUIT
    assert ended.calls_made == 4

    entries = _guardrail_entries(loop)
    assert len(entries) == 1 and entries[0]["layer"] == "reasoning"
    assert entries[0]["injected"] == reminder["content"]
    summary = [e for e in load_entries(loop.session_path) if e.get("type") == "message"]
    assert summary[-1]["role"] == "assistant"
    assert "总结：工具一直失败" in summary[-1]["content"]

    # 会话状态完好：重建消息与实时一致；同一 loop 继续下一回合仍能正常跑
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages
    follow_up = asyncio.run(_collect(loop, "继续"))
    assert isinstance(follow_up[-1], TurnEnded) and follow_up[-1].guardrail_stop is None
    assert any(
        message.get("role") == "assistant" and "总结" in str(message.get("content"))
        for message in client.requests[4]
    )


def test_permission_denials_count_toward_the_failure_circuit(tmp_path: Path) -> None:
    calls: list[int] = []

    async def handler(_args: dict[str, Any]) -> str:  # pragma: no cover - 被权限层拦住
        calls.append(1)
        return "never"

    client = ScriptedClient(
        [
            tool_turn("blocked", {}, call_id="c1"),
            tool_turn("blocked", {}, call_id="c2"),
            tool_turn("blocked", {}, call_id="c3"),
            text_turn("总结：权限一直拒绝。"),
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_tool("blocked", handler),),
        limits=GuardrailLimits(repeat=99, stagnation=99, failure=3, planning=99),
        permissions=PermissionLayer(
            [Rule(tool="blocked", pattern=None, verdict=DENY, source="test", text="blocked")]
        ),
    )
    events = asyncio.run(_collect(loop))

    assert calls == []  # 权限层拦住，工具从未执行
    denied = [e for e in load_entries(loop.session_path) if e.get("type") == "permission"]
    assert len(denied) == 3 and all(entry["allowed"] is False for entry in denied)
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert triggered and triggered[-1].guard == GUARD_CIRCUIT
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop == GUARD_CIRCUIT


def test_planning_terminates_after_the_configured_number_of_interceptions(
    tmp_path: Path,
) -> None:
    calls: list[int] = []
    client = ScriptedClient(
        [
            tool_turn("counter", {}, call_id="c1"),
            tool_turn("counter", {}, call_id="c2"),
            tool_turn("counter", {}, call_id="c3"),
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_counter_tool(calls),),
        limits=GuardrailLimits(repeat=2, stagnation=99, failure=99, planning=2),
    )
    events = asyncio.run(_collect(loop))

    assert len(calls) == 1  # 第一次放行；之后都被拦
    assert len(client.requests) == 3  # 终止后不再请求模型
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert [(e.layer, e.guard) for e in triggered] == [
        ("tool", GUARD_REPEAT),
        ("planning", GUARD_REINJECT),
        ("tool", GUARD_REPEAT),
        ("planning", GUARD_TERMINATE),
    ]
    assert "温和终止" in triggered[-1].message

    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop == "planning"
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages
    entries = _guardrail_entries(loop)
    assert [e["guard"] for e in entries] == [
        GUARD_REPEAT,
        GUARD_REINJECT,
        GUARD_REPEAT,
        GUARD_TERMINATE,
    ]


def test_malformed_calls_count_toward_the_failure_circuit(tmp_path: Path) -> None:
    def malformed(call_id: str) -> list[object]:
        bad = ToolCall(
            id=call_id,
            name="read",
            arguments='{"path": ',
            parse_error="参数不是合法 JSON 对象",
        )
        return [ToolCallsEvent((bad,)), UsageEvent(StreamUsage(10, 5, 0, 0)), StreamEnd("tool_calls")]

    client = ScriptedClient(
        [malformed("c1"), malformed("c2"), malformed("c3"), text_turn("总结：参数一直畸形")]
    )
    loop = _loop(
        tmp_path,
        client,
        (_counter_tool([]),),
        limits=GuardrailLimits(repeat=99, stagnation=99, failure=3, planning=99),
    )
    events = asyncio.run(_collect(loop))

    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [e.ok for e in finished] == [False, False, False]
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop == GUARD_CIRCUIT


def test_a_long_normal_task_is_never_intercepted(tmp_path: Path) -> None:
    """误报保护：40 轮参数与结果都在变化的工具调用，不应触发任何一层。"""
    calls: list[int] = []
    turns: list[list[object]] = [
        tool_turn("echo", {"n": index}, call_id=f"c{index}") for index in range(40)
    ]
    turns.append(text_turn("做完了"))
    client = ScriptedClient(turns)
    loop = _loop(tmp_path, client, (_echo_tool(calls),))
    events = asyncio.run(_collect(loop))

    assert len(calls) == 40
    assert not [e for e in events if isinstance(e, GuardrailTriggered)]
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop is None
    assert _guardrail_entries(loop) == []


def test_tool_layer_blocks_do_not_count_toward_the_failure_circuit(tmp_path: Path) -> None:
    """三层独立：工具层拦截交给规划层处理，不推进推理层的失败计数。

    一批 3 次相同调用（repeat=2）：第 1 次执行、后两次被拦；failure=2 若把拦截算失败
    就会立刻熔断。正确行为是只重注入，不熔断。
    """
    calls: list[int] = []
    parallel = [
        ToolCallsEvent(
            tuple(
                ToolCall(id=f"p{index}", name="counter", arguments="{}")
                for index in range(3)
            )
        ),
        UsageEvent(StreamUsage(10, 5, 0, 0)),
        StreamEnd("tool_calls"),
    ]
    client = ScriptedClient([parallel, text_turn("我换个做法")])
    loop = _loop(
        tmp_path,
        client,
        (_counter_tool(calls),),
        limits=GuardrailLimits(repeat=2, stagnation=99, failure=2, planning=2),
    )
    events = asyncio.run(_collect(loop))

    assert len(calls) == 1
    triggered = [e for e in events if isinstance(e, GuardrailTriggered)]
    assert [(e.layer, e.guard) for e in triggered] == [
        ("tool", GUARD_REPEAT),
        ("tool", GUARD_REPEAT),
        ("planning", GUARD_REINJECT),
    ]
    assert not [e for e in triggered if e.guard == GUARD_CIRCUIT]
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop is None


def test_summary_call_tool_calls_are_ignored_when_tools_are_disabled(tmp_path: Path) -> None:
    """熔断总结禁用工具：端点若硬塞回 tool_calls，也不能落成没有 tool 应答的孤立调用。"""
    calls: list[int] = []
    ghost = ToolCall(id="ghost", name="bash", arguments="{}")
    summary_turn: list[object] = [
        ToolCallsEvent((ghost,)),
        *text_turn("总结：工具一直失败。"),
    ]
    client = ScriptedClient(
        [
            tool_turn("boom", {}, call_id="c1"),
            tool_turn("boom", {}, call_id="c2"),
            tool_turn("boom", {}, call_id="c3"),
            summary_turn,
        ]
    )
    loop = _loop(
        tmp_path,
        client,
        (_boom_tool(calls),),
        limits=GuardrailLimits(repeat=99, stagnation=99, failure=3, planning=99),
    )
    events = asyncio.run(_collect(loop))

    assert client.tool_schemas[3] is None
    assistant_messages = [
        entry
        for entry in load_entries(loop.session_path)
        if entry.get("type") == "message" and entry.get("role") == "assistant"
    ]
    assert "toolCalls" not in assistant_messages[-1]
    assert assistant_messages[-1]["content"] == "总结：工具一直失败。"
    assert "ghost" not in {
        entry.get("toolCallId")
        for entry in load_entries(loop.session_path)
        if entry.get("type") == "tool_call"
    }
    assert messages_from_entries(load_branch(loop.session_path)) == loop.messages
    ended = events[-1]
    assert isinstance(ended, TurnEnded) and ended.guardrail_stop == GUARD_CIRCUIT
