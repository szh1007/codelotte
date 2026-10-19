"""`eval defense` 的 CLI 端到端（票据 21）。"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import run_cli


def _session(path: Path, *extra: dict[str, object]) -> Path:
    entries: list[dict[str, object]] = [
        {"type": "session", "id": "s1", "parentId": None, "schema": "session/v1"},
        {"type": "message", "id": "m1", "parentId": "s1", "role": "user", "content": "do it"},
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
        "guard": "stagnation",
        "message": "工具层拦截：结果相同",
        "count": 2,
        "threshold": 2,
    }


def _run_dir(tmp_path: Path) -> Path:
    session = _session(tmp_path / "sessions" / "normal.jsonl")
    looped = _session(tmp_path / "sessions" / "looped.jsonl", _guardrail())
    run = tmp_path / "run"
    run.mkdir()
    payload = {
        "meta": {"run_id": "run-1", "harness": "codelotte", "harness_kind": "agent"},
        "cases": [
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
                "session_path": str(session),
            },
        ],
    }
    (run / "report.json").write_text(json.dumps(payload), encoding="utf-8")
    return run


def test_defense_dry_run_prints_plan_and_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "out"

    result = run_cli(
        "eval",
        "defense",
        "--run",
        str(_run_dir(tmp_path)),
        "--out",
        str(out),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "repeat-block" in result.stdout
    assert "dry-run" in result.stdout
    assert not out.exists()


def test_defense_command_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "out"

    result = run_cli(
        "eval",
        "defense",
        "--run",
        str(_run_dir(tmp_path)),
        "--out",
        str(out),
    )

    assert result.returncode == 0, result.stderr
    assert "[defense]" in result.stdout
    report = out / "defense-report.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "注入拦截" in text and "误报审计" in text
    payload = json.loads((out / "defense-report.json").read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["injection"]["attempts"] == 1
