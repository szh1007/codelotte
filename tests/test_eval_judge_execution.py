"""judge 接进执行管线（票据 17）：确定性优先、成本/分数进入案例结果。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from codelotte.evals.execution import execute_harness
from codelotte.evals.harness_types import HarnessExecution
from codelotte.evals.judge import JudgeContext
from codelotte.evals.tasks import FileExpectation, Judge, Task, Verifier
from tests.fake_client import ScriptedClient, fake_catalog, text_turn


class _WriteHarness:
    name = "write"
    kind = "agent"
    isolation = "none"

    def __init__(self, content: str) -> None:
        self.content = content

    async def run(self, task, *, workspace, session_root, case_name):
        del task, session_root, case_name
        (workspace / "out.txt").write_text(self.content, encoding="utf-8")
        return HarnessExecution()


def _judge(*, calibration: str | None = None) -> Judge:
    return Judge(
        dimensions=("correctness",),
        rubric="correctness: 内容正确",
        pass_threshold=0.6,
        calibration=calibration,
    )


def _task(*, with_judge: bool, calibration: str | None = None) -> Task:
    return Task(
        id="judge-case",
        bucket="A",
        instruction="写 out.txt",
        setup={"in.txt": "x\n"},
        verifier=Verifier(
            files=(FileExpectation(path="out.txt", equals="hello\n"),),
            judge=_judge(calibration=calibration) if with_judge else None,
        ),
    )


def _context(client: ScriptedClient) -> JudgeContext:
    return JudgeContext(
        client_factory=lambda: client,
        model="fake-model",
        catalog=fake_catalog(),
    )


def _judge_payload(score: float) -> str:
    return json.dumps(
        {
            "scores": {"correctness": score},
            "reasons": {"correctness": "看起来正确"},
        },
        ensure_ascii=False,
    )


def _run(task: Task, harness, tmp_path: Path, *, judge_context=None):
    return asyncio.run(
        execute_harness(
            task,
            harness,
            workspace=tmp_path / "workspace",
            session_root=tmp_path / "sessions",
            repo_root=tmp_path,
            snapshot_ref=None,
            judge_context=judge_context,
        )
    )


def test_task_without_judge_never_calls_the_judge_client(tmp_path: Path) -> None:
    judge_client = ScriptedClient([text_turn(_judge_payload(0.9))])

    execution = _run(
        _task(with_judge=False),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is True
    assert execution.judge_used is False
    assert judge_client.requests == []


def test_deterministic_failure_skips_the_judge(tmp_path: Path) -> None:
    judge_client = ScriptedClient([text_turn(_judge_payload(0.9))])

    execution = _run(
        _task(with_judge=True),
        _WriteHarness("bye\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is False
    assert execution.judge_used is False
    assert judge_client.requests == []


def test_judge_runs_after_deterministic_pass_and_adds_its_cost(
    tmp_path: Path,
) -> None:
    judge_client = ScriptedClient([text_turn(_judge_payload(0.9), usage=(100, 20, 40, 60))])

    execution = _run(
        _task(with_judge=True),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is True
    assert execution.judge_used is True
    assert execution.judge_passed is True
    assert execution.judge_overall == 0.9
    assert execution.judge_calls == 1
    assert execution.model_calls == 1
    assert execution.judge_cost > 0
    # 这条案例的 harness 没有模型调用，总成本就等于 judge 成本
    assert execution.cost == execution.judge_cost
    assert execution.judge_reliable is False  # 没配校准文件


def test_judge_only_task_runs_without_deterministic_checks(tmp_path: Path) -> None:
    judge_client = ScriptedClient([text_turn(_judge_payload(0.9))])
    task = Task(
        id="judge-only",
        bucket="A",
        instruction="写结果并接受 judge",
        setup={"in.txt": "x\n"},
        verifier=Verifier(judge=_judge()),
    )

    execution = _run(
        task,
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is True
    assert execution.judge_used is True
    assert execution.judge_passed is True


def test_judge_can_fail_a_deterministically_passing_task(tmp_path: Path) -> None:
    judge_client = ScriptedClient([text_turn(_judge_payload(0.1))])

    execution = _run(
        _task(with_judge=True),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is False
    assert execution.judge_passed is False
    assert "judge overall=0.10" in execution.verifier_detail


def test_judge_without_a_context_is_a_case_error(tmp_path: Path) -> None:
    execution = _run(
        _task(with_judge=True),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=None,
    )

    assert execution.completed is False
    assert execution.judge_used is True
    assert execution.judge_error is not None
    assert "没有配置 judge 模型" in execution.judge_error


def test_low_kappa_marks_the_warning_but_keeps_the_score(tmp_path: Path) -> None:
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "schema": "judge-calibration/v1",
                "task_id": "judge-case",
                "model": "m",
                "samples": 20,
                "labeler": "author-draft",
                "kappa": 0.2,
                "agreement": 0.6,
                "kappa_threshold": 0.6,
                "pass_threshold": 0.6,
                "generated_at": "2026-10-18T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    judge_client = ScriptedClient([text_turn(_judge_payload(0.9))])

    execution = _run(
        _task(with_judge=True, calibration="calibration.json"),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is True
    assert execution.judge_overall == 0.9
    assert execution.judge_reliable is False
    assert execution.judge_kappa == 0.2
    assert execution.judge_warning is not None
    assert "不可靠" in execution.judge_warning


def test_judge_error_fails_the_case(tmp_path: Path) -> None:
    judge_client = ScriptedClient([text_turn("not json")])

    execution = _run(
        _task(with_judge=True),
        _WriteHarness("hello\n"),
        tmp_path,
        judge_context=_context(judge_client),
    )

    assert execution.completed is False
    assert execution.judge_error is not None
    assert "judge" in execution.verifier_detail
