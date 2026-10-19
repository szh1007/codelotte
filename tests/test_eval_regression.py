"""强制压缩运行器（票据 13）：真实 loop + 剧本化 Provider + 真工具。

测试缝 = Provider 缝（SPEC 测试决策）：压缩策略、摘要调用、checkpoint 探针、
文件验收全部走真实代码路径；只有模型输出是剧本。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from codelotte.compaction import CompactionLimits
from codelotte.evals.regression import (
    CaseResult,
    checkpoint_prompt,
    forced_policy,
    run_case,
)
from codelotte.evals.tasks import Checkpoint, FileExpectation, Task, Verifier
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import load_entries
from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn

SUMMARY = (
    "1. 任务目标：把 in.txt 写到 out.txt\n"
    "2. 已完成事项：读取 in.txt\n"
    "3. 关键决策及其理由：先读后写\n"
    "4. 活跃约束：不要修改 in.txt\n"
    "5. 涉及文件清单：in.txt\n"
    "6. 当前未解决问题：还没写 out.txt\n"
    "7. 下一步：写 out.txt"
)
CHECKPOINT_ANSWER = "1. 把 in.txt 的内容写到 out.txt。"


def _task() -> Task:
    return Task(
        id="copy-file",
        bucket="A",
        instruction="把 in.txt 的内容写到 out.txt",
        setup={"in.txt": "hello\n"},
        verifier=Verifier(files=(FileExpectation(path="out.txt", equals="hello"),)),
        checkpoints=(
            Checkpoint(question="任务目标是什么？", facts=(("out.txt",), ("in.txt",))),
        ),
    )


def _run(
    tmp_path: Path,
    task: Task,
    *,
    k: int,
    agent_scripts: list[list[object]],
    probe_scripts: list[list[object]] | None = None,
    session_root: Path | None = None,
) -> CaseResult:
    agent = ScriptedClient(agent_scripts)
    probe = ScriptedClient(probe_scripts or [])
    return asyncio.run(
        run_case(
            task,
            k=k,
            repetition=1,
            workspace=tmp_path / "workspace",
            session_root=session_root or tmp_path / "sessions",
            model="fake-model",
            catalog=fake_catalog(),
            client=agent,
            probe_client=probe,
            executor_factory=LocalExecutor,
            context_window=1000,
        )
    )


def test_forces_one_compaction_and_probes_the_compacted_context(tmp_path: Path) -> None:
    agent = ScriptedClient(
        [
            tool_turn("read", {"path": "in.txt"}),
            text_turn(SUMMARY),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn("完成"),
        ]
    )
    probe = ScriptedClient([text_turn(CHECKPOINT_ANSWER)])
    result = asyncio.run(
        run_case(
            _task(),
            k=1,
            repetition=1,
            workspace=tmp_path / "workspace",
            session_root=tmp_path / "sessions",
            model="fake-model",
            catalog=fake_catalog(),
            client=agent,
            probe_client=probe,
            executor_factory=LocalExecutor,
            context_window=1000,
        )
    )

    assert result.completed is True
    assert result.valid is True
    assert result.compactions == 1
    assert result.model_calls == 4  # read / 摘要 / write / 终答
    assert len(result.checkpoints) == 1
    assert result.checkpoints[0].scores[0].passed is True
    assert result.retention_passed == 1 and result.retention_total == 1

    # 探针是带外请求：无工具、最后一条是问题集，首条 system 是压缩摘要
    assert probe.tool_schemas == [None]
    probe_messages = probe.requests[0]
    assert probe_messages[0]["role"] == "system"
    assert "1. 任务目标" in probe_messages[0]["content"]
    assert probe_messages[-1]["role"] == "user"
    assert "任务目标是什么？" in probe_messages[-1]["content"]
    assert checkpoint_prompt(_task().checkpoints) in probe_messages[-1]["content"]

    # 原始轨迹落盘：压缩 entry 与工具链都在会话文件里
    assert result.session_path is not None
    entries = load_entries(Path(result.session_path))
    assert [entry["type"] for entry in entries].count("compaction") == 1
    assert (tmp_path / "workspace" / "out.txt").read_text(encoding="utf-8") == "hello"


def test_runs_exactly_k_compactions_when_there_are_enough_turns(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _task(),
        k=2,
        agent_scripts=[
            tool_turn("read", {"path": "in.txt"}),
            text_turn(SUMMARY),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn(SUMMARY),
            text_turn("完成"),
        ],
        probe_scripts=[text_turn(CHECKPOINT_ANSWER), text_turn(CHECKPOINT_ANSWER)],
    )

    assert result.compactions == 2
    assert result.valid is True
    assert [observation.compaction for observation in result.checkpoints] == [1, 2]
    assert result.retention_passed == 2


def test_flags_a_run_that_needs_more_turns_than_the_task_has(tmp_path: Path) -> None:
    """k=5 但任务只有两个 turn：只压到 2 次——报表必须标为无效，不能冒充 5 次。"""
    result = _run(
        tmp_path,
        _task(),
        k=5,
        agent_scripts=[
            tool_turn("read", {"path": "in.txt"}),
            text_turn(SUMMARY),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn(SUMMARY),
            text_turn("完成"),
        ],
        probe_scripts=[text_turn(CHECKPOINT_ANSWER), text_turn(CHECKPOINT_ANSWER)],
    )

    assert result.compactions == 2
    assert result.valid is False
    assert result.completed is True  # 任务本身仍完成了，失效的是"k 次压缩"这个实验条件


def test_k_zero_is_the_no_compression_control(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _task(),
        k=0,
        agent_scripts=[
            tool_turn("read", {"path": "in.txt"}),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn("完成"),
        ],
    )

    assert result.compactions == 0
    assert result.valid is True
    assert result.completed is True
    assert result.checkpoints == ()
    assert result.model_calls == 3


def test_records_verifier_failure_as_not_completed(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        _task(),
        k=0,
        agent_scripts=[
            tool_turn("write", {"path": "out.txt", "content": "bye"}),
            text_turn("完成"),
        ],
    )

    assert result.completed is False
    assert "内容不符" in result.verifier_detail


def test_python_verifier_runs_inside_the_workspace(tmp_path: Path) -> None:
    task = replace(
        _task(),
        verifier=Verifier(
            python="from calc import add\nassert add(1, 2) == 3\nprint('ok')"
        ),
        setup={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    result = _run(
        tmp_path,
        task,
        k=0,
        agent_scripts=[text_turn("完成")],
    )

    assert result.completed is True
    assert result.verifier_detail == "验收通过"


def test_reports_python_verifier_failure(tmp_path: Path) -> None:
    task = replace(_task(), verifier=Verifier(python="raise SystemExit(3)"))
    result = _run(
        tmp_path,
        task,
        k=0,
        agent_scripts=[text_turn("完成")],
    )

    assert result.completed is False
    assert "退出码 3" in result.verifier_detail


def test_relative_session_root_is_resolved_before_the_workspace_chdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """相对 --out 的会话必须落在 run 根，不能落进被测工作区（审查发现的污染路径）。"""
    monkeypatch.chdir(tmp_path)
    result = _run(
        tmp_path,
        _task(),
        k=0,
        agent_scripts=[
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn("完成"),
        ],
        session_root=Path("sessions"),
    )

    assert result.session_path is not None
    session = Path(result.session_path)
    assert session.is_relative_to(tmp_path / "sessions")
    assert not session.is_relative_to(tmp_path / "workspace")


def test_stops_at_the_model_call_budget(tmp_path: Path) -> None:
    task = replace(_task(), max_model_calls=1)
    result = _run(
        tmp_path,
        task,
        k=0,
        agent_scripts=[
            tool_turn("read", {"path": "in.txt"}),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn("完成"),
        ],
    )

    # 软上限：第 2 次调用的 usage 到了才中止（精确配额需要改 loop，v0 不做）
    assert result.model_calls == 2
    assert result.error is not None and "max_model_calls" in result.error
    assert result.completed is False


def _policy_entries() -> list[dict[str, object]]:
    return [
        {"type": "session", "id": "s"},
        {"type": "message", "id": "u1", "role": "user", "content": "go"},
        {"type": "message", "id": "a1", "role": "assistant", "content": "one"},
        {"type": "tool_call", "id": "tc1", "toolCallId": "c1", "name": "read", "arguments": {}},
        {"type": "tool_result", "id": "tr1", "toolCallId": "c1", "name": "read", "ok": True},
        {"type": "message", "id": "a2", "role": "assistant", "content": "two"},
        {"type": "tool_call", "id": "tc2", "toolCallId": "c2", "name": "read", "arguments": {}},
        {"type": "tool_result", "id": "tr2", "toolCallId": "c2", "name": "read", "ok": True},
        {"type": "message", "id": "a3", "role": "assistant", "content": "three"},
    ]


def test_wide_strategy_keeps_two_turns_at_the_cut() -> None:
    policy = forced_policy(1, strategy="wide")

    decision = policy(
        _policy_entries(),
        input_tokens=1,
        context_window=1000,
        limits=CompactionLimits(),
    )

    assert decision is not None
    assert decision.first_kept_entry_id == "a2"
    assert decision.mode == "hard"


def test_wide_strategy_falls_back_when_there_is_only_one_turn() -> None:
    entries = _policy_entries()[:3]
    policy = forced_policy(1, strategy="wide")

    decision = policy(
        entries,
        input_tokens=1,
        context_window=1000,
        limits=CompactionLimits(),
    )

    assert decision is not None
    assert decision.first_kept_entry_id == "a1"


def test_run_case_records_the_compact_template(tmp_path: Path) -> None:
    agent = ScriptedClient(
        [
            tool_turn("read", {"path": "in.txt"}),
            text_turn(SUMMARY),
            tool_turn("write", {"path": "out.txt", "content": "hello"}),
            text_turn("完成"),
        ]
    )
    probe = ScriptedClient([text_turn(CHECKPOINT_ANSWER)])

    result = asyncio.run(
        run_case(
            _task(),
            k=1,
            repetition=1,
            workspace=tmp_path / "workspace",
            session_root=tmp_path / "sessions",
            model="fake-model",
            catalog=fake_catalog(),
            client=agent,
            probe_client=probe,
            executor_factory=LocalExecutor,
            context_window=1000,
            template="compact",
        )
    )

    assert result.template == "compact"
    summary_request = agent.requests[1][-1]["content"]
    assert "1. 任务目标" in summary_request
    assert "3. 活跃约束" in summary_request
    assert "关键决策及其理由" not in summary_request
