"""对照报表与控制 agent 自检（票据 16）：三组并列、自检结论与失败定位。"""

from __future__ import annotations

import json
from pathlib import Path

from codelotte.evals.compare import (
    HarnessRun,
    evaluate_controls,
    write_comparison_report,
)
from codelotte.evals.meta import EvalRunMeta, TaskMeta
from codelotte.evals.results import EvalCaseResult


def _case(
    task_id: str,
    *,
    passed: bool,
    harness: str,
    cost: float = 0.01,
    duration: float = 1.0,
    flagged: bool = False,
) -> EvalCaseResult:
    return EvalCaseResult(
        task_id=task_id,
        bucket="A",
        repetition=1,
        passed=passed,
        verifier_detail="验收通过" if passed else "内容不符",
        model_calls=1,
        input_tokens=10,
        output_tokens=5,
        cost=cost,
        duration_seconds=duration,
        periods=(("peak", 1),),
        session_path=f"sessions/{harness}-{task_id}.json",
        workspace=f"workspaces/{harness}-{task_id}",
        harness=harness,
        flagged=flagged,
        flag_reason="保护文件被改动：protected.txt" if flagged else None,
    )


def _meta(harness: str) -> EvalRunMeta:
    return EvalRunMeta(
        run_id=harness,
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
        repetitions=1,
        seed=0,
        tasks=(TaskMeta(id="001-audit-report", bucket="A", sha256="a-sha"),),
        command="codelotte eval compare",
        harness=harness,
        harness_kind="control" if harness in {"oracle", "no-op", "cheating"} else "agent",
        isolation="none" if harness in {"oracle", "no-op", "cheating"} else "local",
    )


def _run(harness: str, cases: list[EvalCaseResult]) -> HarnessRun:
    return HarnessRun(
        name=harness,
        kind="control" if harness in {"oracle", "no-op", "cheating"} else "agent",
        isolation="none" if harness in {"oracle", "no-op", "cheating"} else "local",
        meta=_meta(harness),
        cases=tuple(cases),
    )


def test_control_self_check_accepts_the_expected_pattern() -> None:
    runs = [
        _run("oracle", [_case("t1", passed=True, harness="oracle")]),
        _run("no-op", [_case("t1", passed=False, harness="no-op")]),
        _run(
            "cheating",
            [_case("t1", passed=False, harness="cheating", flagged=True)],
        ),
    ]

    checks = evaluate_controls(runs)

    assert checks
    assert all(check.passed for check in checks)


def test_control_self_check_rejects_an_oracle_failure() -> None:
    runs = [
        _run("oracle", [_case("t1", passed=False, harness="oracle")]),
        _run("no-op", [_case("t1", passed=False, harness="no-op")]),
        _run(
            "cheating",
            [_case("t1", passed=False, harness="cheating", flagged=True)],
        ),
    ]

    checks = evaluate_controls(runs)

    assert any(not check.passed and check.harness == "oracle" for check in checks)


def test_control_self_check_rejects_an_unflagged_cheat() -> None:
    runs = [
        _run("oracle", [_case("t1", passed=True, harness="oracle")]),
        _run("no-op", [_case("t1", passed=False, harness="no-op")]),
        _run("cheating", [_case("t1", passed=False, harness="cheating")]),
    ]

    checks = evaluate_controls(runs)

    assert any(not check.passed and check.harness == "cheating" for check in checks)


def test_compare_report_has_a_task_level_three_way_table(tmp_path: Path) -> None:
    runs = [
        _run(
            "codelotte",
            [
                _case("001-audit-report", passed=True, harness="codelotte", cost=0.02),
                _case("002-fix", passed=False, harness="codelotte", cost=0.03),
            ],
        ),
        _run(
            "mini-swe-agent",
            [
                _case("001-audit-report", passed=False, harness="mini-swe-agent"),
                _case("002-fix", passed=True, harness="mini-swe-agent"),
            ],
        ),
        _run(
            "raw",
            [
                _case("001-audit-report", passed=False, harness="raw"),
                _case("002-fix", passed=False, harness="raw"),
            ],
        ),
    ]

    report = write_comparison_report(
        tmp_path, runs, command="codelotte eval compare", mode="compare"
    )

    markdown = report.read_text(encoding="utf-8")
    assert "任务级并列对比" in markdown
    assert "codelotte" in markdown
    assert "mini-swe-agent" in markdown
    assert "裸单轮 API" in markdown
    assert "001-audit-report" in markdown and "002-fix" in markdown
    assert "¥" in markdown and "s" in markdown
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["mode"] == "compare"
    assert [item["name"] for item in data["harnesses"]] == [
        "codelotte",
        "mini-swe-agent",
        "raw",
    ]
    assert len(data["harnesses"][0]["summaries"]) == 2
    assert b"\r\n" not in report.read_bytes()


def test_controls_report_prepends_the_self_check(tmp_path: Path) -> None:
    runs = [
        _run("oracle", [_case("t1", passed=True, harness="oracle")]),
        _run("no-op", [_case("t1", passed=False, harness="no-op")]),
        _run(
            "cheating",
            [_case("t1", passed=False, harness="cheating", flagged=True)],
        ),
    ]

    report = write_comparison_report(
        tmp_path, runs, command="codelotte eval controls", mode="controls"
    )

    markdown = report.read_text(encoding="utf-8")
    assert "控制 agent 自检" in markdown
    assert "自检结论" in markdown
    assert "通过" in markdown
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert data["mode"] == "controls"
    assert data["checks"] and all(check["passed"] for check in data["checks"])
