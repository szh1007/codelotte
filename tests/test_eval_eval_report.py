"""通用测评报表（票据 15）：pass^k 口径、失败定位与落盘文件。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from codelotte.evals.eval_report import summarize_eval, write_eval_report
from codelotte.evals.meta import EvalRunMeta, TaskMeta
from codelotte.evals.results import EvalCaseResult


def _case(
    task_id: str,
    repetition: int,
    *,
    passed: bool,
    cost: float = 0.01,
    duration: float = 1.0,
    periods: tuple[tuple[str, int], ...] = (("peak", 1),),
    error: str | None = None,
) -> EvalCaseResult:
    return EvalCaseResult(
        task_id=task_id,
        bucket="B",
        repetition=repetition,
        passed=passed,
        verifier_detail="验收通过" if passed else "内容不符",
        model_calls=2,
        input_tokens=100,
        output_tokens=50,
        cost=cost,
        duration_seconds=duration,
        periods=periods,
        session_path=f"sessions/{task_id}-r{repetition}/s.jsonl",
        workspace=f"workspaces/{task_id}-r{repetition}",
        error=error,
    )


def _meta() -> EvalRunMeta:
    return EvalRunMeta(
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
        repetitions=3,
        seed=7,
        tasks=(
            TaskMeta(id="a", bucket="A", sha256="a-sha"),
            TaskMeta(
                id="b",
                bucket="B",
                sha256="b-sha",
                snapshot_ref="deadbeef" * 5,
            ),
        ),
        command="codelotte eval run --repeat 3",
    )


def test_summarize_eval_requires_all_repetitions_for_pass_pow_k() -> None:
    cases = [
        _case("a", 1, passed=True),
        _case("a", 2, passed=True),
        _case("a", 3, passed=True),
        _case("b", 1, passed=True),
        _case("b", 2, passed=False),
        _case("b", 3, passed=True),
    ]

    summaries = summarize_eval(cases, repetitions=3)

    assert [summary.task_id for summary in summaries] == ["a", "b"]
    a, b = summaries
    assert a.pass_pow_k is True and a.pass_rate == 1.0
    assert b.pass_pow_k is False and b.pass_rate == 2 / 3
    assert a.model_calls == 6
    assert a.periods == (("peak", 3),)


def test_summarize_eval_does_not_grant_pass_pow_k_when_a_case_is_missing() -> None:
    (summary,) = summarize_eval([_case("a", 1, passed=True)], repetitions=3)

    assert summary.pass_pow_k is False


def test_report_includes_judge_scores_reasons_and_kappa_warning(tmp_path: Path) -> None:
    case = _case("a", 1, passed=True)
    case = replace(
        case,
        judge_used=True,
        judge_passed=True,
        judge_overall=0.9,
        judge_scores=(("correctness", 0.9),),
        judge_reasons=(("correctness", "指出 bug"),),
        judge_kappa=0.2,
        judge_samples=20,
        judge_reliable=False,
        judge_warning="κ=0.20 < 阈值 0.60，judge 验收器不可靠",
        judge_calls=1,
        judge_cost=0.001,
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    write_eval_report(run_dir, _meta(), [case])

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## LLM judge" in markdown
    assert "overall 0.90" in markdown
    assert "指出 bug" in markdown
    assert "κ=0.20" in markdown
    assert "⚠ 不可靠" in markdown
    assert "judge" in markdown


def test_write_eval_report_contains_failure_session_and_periods(tmp_path: Path) -> None:
    cases = [
        _case("a", 1, passed=True),
        _case("a", 2, passed=False, periods=(("offpeak", 1),)),
        _case("a", 3, passed=False, error="boom", periods=(("offpeak", 1),)),
    ]
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    report_path = write_eval_report(run_dir, _meta(), cases)

    assert report_path == run_dir / "report.md"
    markdown = report_path.read_text(encoding="utf-8")
    assert "# 评测报表" in markdown
    assert "pass^3" in markdown
    assert "失败案例" in markdown
    assert "sessions/a-r2/s.jsonl" in markdown
    assert "boom" in markdown
    assert "峰值" in markdown and "低谷" in markdown
    assert "deadbeef" in markdown  # 任务快照 ref 进复现锁定表

    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert data["meta"]["repetitions"] == 3
    assert data["meta"]["seed"] == 7
    assert data["summaries"][0]["pass_pow_k"] is False
    assert len(data["cases"]) == 3

    for name in ("report.md", "report.json"):
        assert b"\r\n" not in (run_dir / name).read_bytes(), name
