"""无头执行的收尾报告（票据 07 审查修正）：失败/中断路径也要报账；取消前的用量不能丢。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codelotte.loop import AgentLoop
from codelotte.permissions import allow_builtin_tools
from codelotte.providers.base import ProviderError, StreamUsage, TextDelta, UsageEvent
from codelotte.run import print_session_invoice, run_once
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import SessionStore, load_entries
from codelotte.tools import default_tools
from tests.fake_client import PAUSE, ScriptedClient, fake_catalog, text_turn


def _loop(tmp_path: Path, client: ScriptedClient) -> AgentLoop:
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
