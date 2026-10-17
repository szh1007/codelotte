"""通用测评（票据 15）：pass^k、成本/时段、快照、失败定位与报表。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from codelotte.evals.runner import run_eval_suite
from codelotte.evals.tasks import FileExpectation, Snapshot, Task, Verifier
from codelotte.sandbox import LocalExecutor
from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn


def _task(*, expected: str = "hello", snapshot: Snapshot | None = None) -> Task:
    return Task(
        id="write-hello",
        bucket="A",
        instruction="write hello",
        setup={},
        verifier=Verifier(files=(FileExpectation(path="out.txt", equals=expected),)),
        snapshot=snapshot,
    )


def _run(
    tmp_path: Path,
    task: Task,
    *,
    repetitions: int,
    content: str = "hello",
    repo_root: Path | None = None,
):
    def client_factory() -> ScriptedClient:
        return ScriptedClient(
            [
                tool_turn("write", {"path": "out.txt", "content": content}),
                text_turn("done"),
            ]
        )

    return asyncio.run(
        run_eval_suite(
            [task],
            repetitions=repetitions,
            run_id="test-run",
            runs_root=tmp_path / "runs",
            repo_root=repo_root or tmp_path,
            model="fake-model",
            reasoning_effort="high",
            catalog=fake_catalog(),
            context_window=1000,
            client_factory=client_factory,
            executor_factory=LocalExecutor,
            compaction_limits=None,
            guardrail_limits=None,
            seed=0,
            command="codelotte eval run --repeat 3",
        )
    )


def test_pass_pow_k_requires_every_repetition_to_pass(tmp_path: Path) -> None:
    meta, cases = _run(tmp_path, _task(), repetitions=3)

    assert meta.repetitions == 3
    assert len(cases) == 3
    assert all(case.passed for case in cases)
    # 时段依运行当天是工作日/周末而变，测试只断言"两次调用落在同一个实际时段"
    assert all(len(case.periods) == 1 and case.periods[0][1] == 2 for case in cases)
    period = cases[0].periods[0][0]
    assert period in {"peak", "offpeak"}
    for case in cases:
        assert case.session_path is not None
        assert Path(case.session_path).is_file()

    run_dir = tmp_path / "runs" / meta.run_id
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    (summary,) = data["summaries"]
    assert summary["pass_pow_k"] is True
    assert summary["attempts"] == 3 and summary["passed"] == 3
    assert summary["periods"] == [[period, 6]]
    assert len(data["cases"]) == 3

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "pass^3" in markdown
    assert "write-hello" in markdown
    assert ("峰值" in markdown) or ("低谷" in markdown)
    assert "失败案例" in markdown and "无。" in markdown
    assert b"\r\n" not in (run_dir / "report.md").read_bytes()


def test_failure_is_located_by_session_path_in_the_report(tmp_path: Path) -> None:
    meta, cases = _run(tmp_path, _task(expected="hello"), repetitions=2, content="bye")

    assert all(not case.passed for case in cases)
    assert all(case.error is None for case in cases)  # 验收失败不是运行错误
    run_dir = tmp_path / "runs" / meta.run_id
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    (summary,) = data["summaries"]
    assert summary["pass_pow_k"] is False
    assert summary["passed"] == 0

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "失败案例" in markdown
    assert "write-hello" in markdown
    assert cases[0].session_path is not None
    assert Path(cases[0].session_path).name in markdown


def test_snapshot_task_is_extracted_and_scripted_before_the_agent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=eval-test",
            "-c",
            "user.email=eval-test@example.invalid",
            "commit",
            "-qm",
            "snapshot",
        ],
        cwd=repo,
        check=True,
    )
    task = Task(
        id="snapshot-task",
        bucket="B",
        instruction="write hello",
        setup={},
        snapshot=Snapshot(ref="HEAD", repo=".", script="echo init > init.txt"),
        verifier=Verifier(
            files=(
                FileExpectation(path="out.txt", equals="hello"),
                FileExpectation(path="init.txt", contains="init"),
                FileExpectation(path="tracked.txt", contains="tracked"),
            )
        ),
    )

    meta, cases = _run(tmp_path, task, repetitions=1, repo_root=repo)

    assert cases[0].passed is True
    assert meta.tasks[0].snapshot_ref is not None
    assert len(meta.tasks[0].snapshot_ref) == 40
