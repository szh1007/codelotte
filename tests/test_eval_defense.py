"""E5 防御有效性：死循环剧本、注入拦截聚合与误报审计（票据 21）。

测试缝：
- `run_loop_scenarios` 用真实 `AgentLoop` + 脚本化 Provider 跑生产 guardrail；
- `collect_injection_results` 从真实 run 的 report.json 汇总注入任务；
- `audit_false_positives` 从正常任务的会话里数 guardrail 事件；
- `build_defense_report` 写 Markdown/JSON。
"""

from __future__ import annotations

import json
from pathlib import Path

from codelotte.evals.defense import (
    audit_false_positives,
    build_defense_report,
    collect_injection_results,
    collect_loop_pressure_results,
    run_loop_scenarios,
)


def _session(path: Path, *extra: dict[str, object]) -> Path:
    entries: list[dict[str, object]] = [
        {
            "type": "session",
            "id": "s1",
            "parentId": None,
            "schema": "session/v1",
        },
        {
            "type": "message",
            "id": "m1",
            "parentId": "s1",
            "role": "user",
            "content": "完成任务",
        },
    ]
    entries.extend(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _guardrail() -> dict[str, object]:
    return {
        "type": "event",
        "id": "g1",
        "parentId": "m1",
        "kind": "guardrail",
        "layer": "tool",
        "guard": "repeat",
        "message": "工具层拦截：重复调用",
        "count": 3,
        "threshold": 3,
    }


def _report(path: Path, cases: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {"run_id": path.parent.name, "harness": "codelotte", "harness_kind": "agent"},
        "cases": cases,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_loop_scenarios_intercept_all_positive_and_keep_normal_clean(
    tmp_path: Path,
) -> None:
    results = {item.name: item for item in run_loop_scenarios(tmp_path / "sessions")}

    assert set(results) == {
        "repeat-block",
        "stagnation-block",
        "failure-circuit",
        "planning-terminate",
        "batch-repeat",
        "normal-long-varied",
        "normal-retry",
        "normal-single-duplicate",
    }
    assert all(item.passed for item in results.values())
    assert "repeat" in results["repeat-block"].observed
    assert results["repeat-block"].executed_calls == 2
    assert "stagnation" in results["stagnation-block"].observed
    assert results["stagnation-block"].executed_calls == 2
    assert "circuitBreaker" in results["failure-circuit"].observed
    assert results["failure-circuit"].guard_stop == "circuitBreaker"
    assert "terminate" in results["planning-terminate"].observed
    assert results["planning-terminate"].guard_stop == "planning"
    assert "repeat" in results["batch-repeat"].observed
    assert results["batch-repeat"].executed_calls == 2
    for name in ("normal-long-varied", "normal-retry", "normal-single-duplicate"):
        assert results[name].kind == "normal"
        assert results[name].observed == ()
    assert results["normal-long-varied"].executed_calls == 40
    # 每个剧本都有可复查的会话证据
    for item in results.values():
        assert Path(item.session).is_file()


def test_collect_injection_results_counts_all_codelotte_attempts(tmp_path: Path) -> None:
    report = _report(
        tmp_path / "run" / "report.json",
        [
            {
                "task_id": "004-prompt-injection-resistance",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
            },
            {
                "task_id": "004-prompt-injection-resistance",
                "bucket": "B",
                "repetition": 2,
                "passed": False,
                "harness": "codelotte",
                "flagged": True,
            },
            {
                "task_id": "010-injection-in-comment",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
            },
            {
                "task_id": "004-prompt-injection-resistance",
                "bucket": "B",
                "repetition": 1,
                "passed": False,
                "harness": "raw",
            },
            {
                "task_id": "001-audit-report",
                "bucket": "A",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
            },
        ],
    )

    result = collect_injection_results([report.parent])

    assert result.attempts == 3
    assert result.resisted == 2
    assert result.failed == 1
    assert result.flagged == 1
    assert result.rate == 2 / 3
    assert result.by_task["004-prompt-injection-resistance"] == (2, 1)
    assert result.by_task["010-injection-in-comment"] == (1, 1)


def test_collect_loop_pressure_results_counts_guardrail_events(tmp_path: Path) -> None:
    session = _session(tmp_path / "sessions" / "loop.jsonl", _guardrail())
    report = _report(
        tmp_path / "run" / "report.json",
        [
            {
                "task_id": "013-repeat-pressure",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(session),
            },
            {
                "task_id": "013-repeat-pressure",
                "bucket": "B",
                "repetition": 2,
                "passed": False,
                "harness": "codelotte",
                "session_path": None,
            },
        ],
    )

    result = collect_loop_pressure_results([report.parent])

    assert result.attempts == 2
    assert result.intercepted == 1
    assert result.completed == 1
    assert result.rate == 0.5
    assert result.by_task["013-repeat-pressure"] == (2, 1)


def test_audit_false_positives_reads_normal_task_sessions(tmp_path: Path) -> None:
    dirty = _session(tmp_path / "sessions" / "dirty.jsonl", _guardrail())
    clean = _session(tmp_path / "sessions" / "clean.jsonl")
    report = _report(
        tmp_path / "run" / "report.json",
        [
            {
                "task_id": "001-audit-report",
                "bucket": "A",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(dirty),
            },
            {
                "task_id": "002-fix-off-by-one",
                "bucket": "A",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(clean),
            },
            {
                "task_id": "004-prompt-injection-resistance",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(dirty),
            },
        ],
    )

    audit = audit_false_positives([report.parent])

    assert audit.normal_cases == 2
    assert audit.cases_with_guardrail == 1
    assert audit.fatal_cases == 0
    assert audit.events == 1
    assert audit.by_guard == {"repeat": 1}
    assert audit.rate == 0.5


def test_build_defense_report_writes_markdown_and_json(tmp_path: Path) -> None:
    clean = _session(tmp_path / "sessions" / "clean.jsonl")
    looped = _session(tmp_path / "sessions" / "looped.jsonl", _guardrail())
    report = _report(
        tmp_path / "run" / "report.json",
        [
            {
                "task_id": "010-injection-in-comment",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
            },
            {
                "task_id": "013-repeat-pressure",
                "bucket": "B",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(looped),
            },
            {
                "task_id": "001-audit-report",
                "bucket": "A",
                "repetition": 1,
                "passed": True,
                "harness": "codelotte",
                "session_path": str(clean),
            },
        ],
    )
    out = tmp_path / "defense"

    path = build_defense_report(out, run_dirs=[report.parent])

    text = path.read_text(encoding="utf-8")
    assert "# 防御有效性" in text
    assert "死循环剧本" in text
    assert "真实模型死循环压力" in text
    assert "注入拦截" in text
    assert "误报审计" in text
    payload = json.loads((out / "defense-report.json").read_text(encoding="utf-8"))
    assert payload["loop"]["interception_rate"] == 1.0
    assert payload["loop_pressure"]["attempts"] == 1
    assert payload["loop_pressure"]["intercepted"] == 1
    assert payload["injection"]["attempts"] == 1
    assert payload["false_positive"]["normal_cases"] == 1
    assert payload["passed"] is True
