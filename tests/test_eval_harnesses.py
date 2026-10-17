"""Agent harness 缝（票据 16）：对照组与三种控制 agent 走同一条验收管线。

Seam：`execute_harness(task, harness, …)`。
- 对照组（raw）证明"裸模型一次调用"能拿到什么；
- 控制 agent 证明评测器本身不瞎打分：oracle 全过、no-op 全败、cheating 全败且被标记。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codelotte.evals.execution import execute_harness
from codelotte.evals.harnesses import (
    CheatingHarness,
    NoOpHarness,
    OracleHarness,
    RawHarness,
)
from codelotte.evals.tasks import FileExpectation, Task, Verifier
from tests.fake_client import ScriptedClient, fake_catalog, text_turn


def _run(task: Task, harness, tmp_path: Path):
    return asyncio.run(
        execute_harness(
            task,
            harness,
            workspace=tmp_path / "workspace",
            session_root=tmp_path / "sessions",
            repo_root=None,
            snapshot_ref=None,
        )
    )


def _raw_task(*, expected: str = "x") -> Task:
    return Task(
        id="raw-baseline",
        bucket="A",
        instruction="say hello",
        setup={"in.txt": "x\n"},
        verifier=Verifier(
            files=(FileExpectation(path="out.txt", equals=expected),)
        ),
    )


def test_raw_harness_makes_one_call_without_tools(tmp_path: Path) -> None:
    client = ScriptedClient([text_turn("hello")])
    harness = RawHarness(client=client, model="fake-model", catalog=fake_catalog())

    execution = _run(_raw_task(), harness, tmp_path)

    # 裸单轮 API 没有工具循环：模型说了 hello，但没有任何文件被写出来
    assert execution.completed is False
    assert execution.model_calls == 1
    assert client.tool_schemas == [None]
    assert client.requests[0][0]["role"] == "user"
    assert execution.input_tokens == 10
    assert execution.output_tokens == 5
    assert execution.cost == pytest.approx(0.00006)
    # 时段按运行当天是工作日/周末而变；这里只断言"一次调用落在一个实际时段"
    (period, count), = execution.periods
    assert period in {"peak", "offpeak"} and count == 1
    assert execution.session_path is not None
    trace = Path(execution.session_path).read_text(encoding="utf-8")
    assert '"type": "baseline_request"' in trace
    assert "hello" in trace


def test_oracle_control_applies_gold_files_and_passes(tmp_path: Path) -> None:
    task = Task(
        id="oracle",
        bucket="A",
        instruction="x",
        setup={"calc.py": "bad\n", "notes.txt": ""},
        verifier=Verifier(
            python="from pathlib import Path; assert Path('calc.py').read_text() == 'good\\n'",
            files=(FileExpectation(path="notes.txt", contains="for i in range(n):"),),
        ),
        oracle_files={
            "calc.py": "good\n",
            "notes.txt": "for i in range(n):\n",
        },
    )

    execution = _run(task, OracleHarness(), tmp_path)

    assert execution.completed is True
    assert execution.model_calls == 0
    assert execution.flagged is False


def test_oracle_control_derives_equals_expectations_without_gold_files(
    tmp_path: Path,
) -> None:
    task = Task(
        id="oracle-derived",
        bucket="A",
        instruction="x",
        setup={},
        verifier=Verifier(
            files=(FileExpectation(path="out.txt", equals="hello\n"),)
        ),
    )

    execution = _run(task, OracleHarness(), tmp_path)

    assert execution.completed is True


def test_noop_control_fails_every_task(tmp_path: Path) -> None:
    execution = _run(_raw_task(), NoOpHarness(), tmp_path)

    assert execution.completed is False
    assert execution.flagged is False
    assert execution.model_calls == 0


def test_a_crashing_harness_still_locates_its_newest_trace(tmp_path: Path) -> None:
    """外层超时/异常时 harness 来不及返回 session_path；仍要能从新增文件里定位轨迹。"""

    class CrashingHarness:
        name = "crash"
        kind = "agent"
        isolation = "none"

        async def run(self, task, *, workspace, session_root, case_name):
            del task, workspace, case_name
            (session_root / "r1-mini-home").mkdir()
            (session_root / "r1-mini-home" / "seen.json").write_text(
                "{}", encoding="utf-8"
            )
            (session_root / "r1-trail.jsonl").write_text(
                "{}\n", encoding="utf-8"
            )
            raise RuntimeError("boom")

    task = Task(
        id="crash",
        bucket="A",
        instruction="x",
        setup={"a.txt": "a"},
        verifier=Verifier(python="pass"),
    )

    execution = _run(task, CrashingHarness(), tmp_path)

    assert execution.error is not None and "boom" in execution.error
    assert execution.session_path is not None
    assert Path(execution.session_path).name == "r1-trail.jsonl"


def test_cheating_control_is_scored_zero_and_flags_protected_files(
    tmp_path: Path,
) -> None:
    task = Task(
        id="cheating",
        bucket="B",
        instruction="x",
        setup={"protected.txt": "locked\n"},
        verifier=Verifier(
            files=(
                FileExpectation(path="out.txt", equals="good\n"),
                FileExpectation(path="protected.txt", unchanged=True),
            )
        ),
    )

    execution = _run(task, CheatingHarness(), tmp_path)

    assert execution.completed is False
    assert execution.flagged is True
    assert execution.flag_reason is not None
    assert "protected.txt" in execution.flag_reason
    assert (tmp_path / "workspace" / "protected.txt").read_text(
        encoding="utf-8"
    ).startswith("locked\nCHEATED")
