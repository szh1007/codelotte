"""无头执行的收尾报告（票据 07 审查修正）：失败/中断路径也要报账；取消前的用量不能丢。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codelotte.guardrails import GuardrailLimits
from codelotte.loop import AgentLoop
from codelotte.permissions import allow_builtin_tools
from codelotte.providers.base import ProviderError, StreamUsage, TextDelta, UsageEvent
from codelotte.run import print_session_invoice, run_once
from codelotte.sandbox import LocalExecutor
from codelotte.session.context import messages_from_entries
from codelotte.session.store import SessionStore, load_branch, load_entries
from codelotte.tools import default_tools
from tests.fake_client import PAUSE, ScriptedClient, fake_catalog, text_turn, tool_turn


def _loop(
    tmp_path: Path,
    client: ScriptedClient,
    *,
    guardrail_limits: GuardrailLimits | None = None,
) -> AgentLoop:
    path = tmp_path / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():  # 同一路径再次构造 = 模拟 --continue（文件不重置）
        path.write_text("", encoding="utf-8")
    return AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=SessionStore.resume(path),
        model="fake-model",
        catalog=fake_catalog(),
        permissions=allow_builtin_tools(),
        guardrail_limits=guardrail_limits,
    )


def test_report_prints_even_when_provider_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """回归（审查发现）：usage 已落盘但流随后失败——钱花了，账单必须照样打出来。"""
    client = ScriptedClient(
        [[TextDelta("说到一半"), UsageEvent(StreamUsage(10, 5, 4, 6)), ProviderError("断线")]]
    )
    loop = _loop(tmp_path, client)
    with pytest.raises(ProviderError):
        asyncio.run(run_once(loop, "任务"))

    err = capsys.readouterr().err
    assert "tokens in=10 out=5" in err
    assert "账单（会话累计，人民币元）：1 次模型调用" in err
    assert any(e["type"] == "usage" for e in load_entries(loop.session_path))


def test_cancelled_stream_still_records_usage_and_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """回归（审查发现）：用量已收到 = 这次调用已在计费——取消不能丢账，收尾仍要报。"""
    client = ScriptedClient(
        [[TextDelta("写一半"), UsageEvent(StreamUsage(10, 5, 4, 6)), PAUSE]]
    )
    loop = _loop(tmp_path, client)

    async def scenario() -> None:
        task = asyncio.create_task(run_once(loop, "任务"))
        await asyncio.wait_for(client.paused.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    usage = next(e for e in load_entries(loop.session_path) if e["type"] == "usage")
    assert usage["inputTokens"] == 10
    assert usage["cost"] is not None  # 已计价（fake_catalog 里 fake-model 有价目）
    assert "账单（会话累计，人民币元）：1 次模型调用" in capsys.readouterr().err


def test_session_invoice_is_cumulative_from_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """账单口径 = 会话累计：两次运行（模拟 --continue）后，账单覆盖两次的调用。"""
    for _ in range(2):
        loop = _loop(tmp_path, ScriptedClient([text_turn("好", usage=(10, 5, 4, 6))]))
        asyncio.run(run_once(loop, "任务"))
    err = capsys.readouterr().err
    assert "账单（会话累计，人民币元）：2 次模型调用" in err


def test_print_session_invoice_writes_nothing_for_empty_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    loop = _loop(tmp_path, ScriptedClient([[TextDelta("x")]]))
    print_session_invoice(loop)
    assert capsys.readouterr().err == ""


def test_guardrail_circuit_break_reports_and_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """票据 11：-p 模式要把守护事件与终止原因写进 stderr，并以非零退出码表示 run 被强制结束。"""
    turns = [
        tool_turn("read", {"path": "no-such-guardrail-file.txt"}, call_id=f"c{index}")
        for index in range(3)
    ]
    turns.append(text_turn("总结：文件读不到。"))
    loop = _loop(
        tmp_path,
        ScriptedClient(turns),
        guardrail_limits=GuardrailLimits(
            repeat=99, stagnation=99, failure=3, planning=99
        ),
    )
    code = asyncio.run(run_once(loop, "读文件"))

    assert code == 1
    err = capsys.readouterr().err
    assert "守护拦截（推理层）" in err
    assert "熔断" in err
    assert [e for e in load_entries(loop.session_path) if e.get("kind") == "guardrail"]


def test_compaction_is_reported_in_p_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """票据 12：-p 也要把压缩点与触发方式写进 stderr（不打断答案）。"""
    path = tmp_path / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    store = SessionStore.resume(path)
    store.append("message", role="user", content="旧任务")
    store.append(
        "message", role="assistant", content="旧回答", model="fake-model", stopReason="stop"
    )
    store.append(
        "usage",
        model="fake-model",
        inputTokens=90,
        outputTokens=5,
        cacheHitTokens=0,
        cacheMissTokens=0,
        period="peak",
        cost=None,
        currency="CNY",
        requestFingerprint="seed",
    )
    loop = AgentLoop(
        client=ScriptedClient([text_turn("摘要"), text_turn("完成")]),
        tools=default_tools(LocalExecutor()),
        store=store,
        model="fake-model",
        catalog=fake_catalog(),
        permissions=allow_builtin_tools(),
        messages=messages_from_entries(load_branch(path)),
        context_window=100,
    )

    code = asyncio.run(run_once(loop, "新任务"))

    assert code == 0
    err = capsys.readouterr().err
    assert "上下文压缩（硬触发" in err
    assert "90%" in err
    assert [e for e in load_entries(path) if e.get("type") == "compaction"]
