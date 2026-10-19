"""压缩回归报表（票据 13）：聚合口径与落盘文件。

报表是实验的最终产物：完成率、有效完成率、状态保留率必须口径明确；
report.json / report.md / annotations.csv / checkpoints.jsonl 四件套齐备。
"""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

from codelotte.evals.checkpoints import CheckpointScore
from codelotte.evals.regression import CaseResult, CheckpointObservation
from codelotte.evals.report import summarize, write_report
from codelotte.evals.suite import RunMeta, TaskMeta


def _observation(passed: int, total: int = 1, compaction: int = 1) -> CheckpointObservation:
    scores = tuple(
        CheckpointScore(
            question=f"问题 {index}",
            passed=index < passed,
            local_passed=index < passed,
            matched=("fact",) if index < passed else (),
            missing=() if index < passed else ("fact",),
            misplaced=(),
        )
        for index in range(total)
    )
    return CheckpointObservation(
        compaction=compaction,
        answer="1. 回答",
        structured=True,
        scores=scores,
    )


def _case(
    task_id: str,
    k: int,
    *,
    completed: bool,
    compactions: int | None = None,
    retention: tuple[int, int] = (1, 1),
    error: str | None = None,
) -> CaseResult:
    observations = tuple(
        _observation(retention[0], retention[1], compaction=index + 1)
        for index in range(compactions if compactions is not None else k)
    )
    return CaseResult(
        task_id=task_id,
        bucket="A",
        k=k,
        repetition=1,
        completed=completed,
        verifier_detail="验收通过" if completed else "内容不符",
        compactions=compactions if compactions is not None else k,
        checkpoints=observations,
        model_calls=4,
        input_tokens=100,
        output_tokens=50,
        probe_input_tokens=20,
        probe_output_tokens=10,
        cost=0.01,
        probe_cost=0.001,
        duration_seconds=1.5,
        session_path="sessions/t.jsonl",
        workspace="workspaces/t",
        error=error,
    )


def _meta() -> RunMeta:
    return RunMeta(
        run_id="run-1",
        started_at="2026-10-18T00:00:00+00:00",
        finished_at="2026-10-18T00:01:00+00:00",
        git_ref="abc1234",
        git_dirty=False,
        git_diff_sha=None,
        python="3.13.0",
        codelotte_version="0.1.0",
        uv_lock_sha="lock-sha",
        model="deepseek-flash",
        reasoning_effort="high",
        context_window=1_000_000,
        soft=0.6,
        hard=0.85,
        k_values=(0, 1, 3),
        repetitions=1,
        seed=7,
        tasks=(
            TaskMeta(id="a", bucket="A", sha256="a-sha"),
            TaskMeta(id="b", bucket="A", sha256="b-sha"),
        ),
        command="codelotte eval compaction --k 0,1,3",
    )


CASES = [
    _case("a", 0, completed=True, retention=(3, 3)),
    _case("a", 1, completed=True, retention=(2, 3)),
    _case("b", 0, completed=True, retention=(3, 3)),
    _case("b", 1, completed=False, retention=(1, 3)),
    _case("b", 1, completed=True, compactions=0, retention=(0, 0), error="boom"),
]


def test_summarize_uses_attempted_valid_and_retention_rates() -> None:
    summary = {group.k: group for group in summarize(CASES)}

    zero = summary[0]
    assert (zero.attempted, zero.completed, zero.valid) == (2, 2, 2)
    # k=0 没有压缩，也就没有 checkpoint——保留率口径为 0/0（报表显示“—”）
    assert zero.retention_total == 0

    one = summary[1]
    assert (one.attempted, one.completed) == (3, 2)
    assert (one.valid, one.valid_completed) == (2, 1)
    assert one.retention_passed == 3 and one.retention_total == 6
    assert one.invalid == 1


def test_write_report_produces_the_four_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    report_path = write_report(run_dir, _meta(), CASES)

    assert report_path == run_dir / "report.md"
    markdown = report_path.read_text(encoding="utf-8")
    assert "# 压缩回归报表" in markdown
    assert "完成率" in markdown and "状态保留率" in markdown
    assert "k=0" in markdown and "k=1" in markdown
    assert "人工标注" in markdown

    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert data["meta"]["git_ref"] == "abc1234"
    assert data["meta"]["seed"] == 7
    assert len(data["cases"]) == len(CASES)

    rows = list(csv.DictReader((run_dir / "annotations.csv").open(encoding="utf-8")))
    assert rows
    assert set(rows[0]) >= {"task_id", "k", "question", "auto_pass", "human_pass", "answer"}
    assert all(row["human_pass"] == "" for row in rows)

    lines = (run_dir / "checkpoints.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == sum(len(case.checkpoints) for case in CASES)
    first = json.loads(lines[0])
    assert first["task_id"] == "a" and first["structured"] is True

    # 会话/导出/报表统一 LF（csv 模块默认 CRLF，Windows write_text 也会转 CRLF——都显式关掉）
    for name in ("report.json", "annotations.csv", "report.md", "checkpoints.jsonl"):
        assert b"\r\n" not in (run_dir / name).read_bytes(), name


def test_summarize_groups_strategy_and_template_combos() -> None:
    cases = [
        _case("a", 1, completed=True),
        replace(
            _case("a", 1, completed=False),
            strategy="wide",
            template="compact",
        ),
    ]

    summaries = summarize(cases)

    assert [(group.strategy, group.template, group.k) for group in summaries] == [
        ("minimal", "seven", 1),
        ("wide", "compact", 1),
    ]
    assert summaries[0].attempted == summaries[1].attempted == 1


def test_report_labels_strategy_template_combinations(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    meta = replace(_meta(), combos=(("minimal", "seven"), ("wide", "compact")))
    cases = [
        _case("a", 1, completed=True),
        replace(
            _case("a", 1, completed=False),
            strategy="wide",
            template="compact",
        ),
    ]

    write_report(run_dir, meta, cases)

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "minimal / seven" in markdown
    assert "wide / compact" in markdown
    rows = list(csv.DictReader((run_dir / "annotations.csv").open(encoding="utf-8")))
    assert rows and rows[0]["strategy"] == "minimal"
    assert rows[0]["template"] == "seven"
