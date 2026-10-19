"""归因/回归命令的 CLI 端到端（票据 18）。"""

from __future__ import annotations

import json
from pathlib import Path

from codelotte.evals.tasks import load_task
from tests.support import run_cli

TASK = '''id = "002-fix-off-by-one"
bucket = "A"
instruction = "修复 bug"

[setup.files]
"calc.py" = "print('x')\\n"

[verifier]
python = "assert True"
'''


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
            "content": "do it",
        },
    ]
    entries.extend(extra)
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _corpus(tmp_path: Path, *, labeler: str = "tester") -> Path:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    loop = _session(
        sessions / "loop.jsonl",
        {
            "type": "event",
            "id": "g1",
            "parentId": "m1",
            "kind": "guardrail",
            "layer": "tool",
            "guard": "repeat",
            "message": "工具层拦截：重复 read",
        },
    )
    model = _session(sessions / "model.jsonl")
    context = _session(
        sessions / "context.jsonl",
        {
            "type": "tool_call",
            "id": "tc1",
            "parentId": "m1",
            "toolCallId": "c1",
            "name": "read",
            "arguments": {"path": "a.txt"},
        },
        {"type": "compaction", "id": "cp", "parentId": "tc1", "summary": "s"},
        {
            "type": "tool_call",
            "id": "tc2",
            "parentId": "cp",
            "toolCallId": "c2",
            "name": "read",
            "arguments": {"path": "a.txt"},
        },
    )
    schema = _session(
        sessions / "schema.jsonl",
        {
            "type": "tool_call",
            "id": "tc3",
            "parentId": "m1",
            "toolCallId": "c3",
            "name": "edit",
            "arguments": "{bad",
            "parseError": "参数不是合法 JSON",
        },
    )
    rows = [
        ("loop-a", loop, "loop"),
        ("loop-b", loop, "loop"),
        ("model-a", model, "model"),
        ("model-b", model, "model"),
        ("context-a", context, "context_loss"),
        ("context-b", context, "context_loss"),
        ("schema-a", schema, "tool_schema"),
        ("schema-b", schema, "tool_schema"),
        ("env-a", tmp_path / "missing-a.jsonl", "environment"),
        ("env-b", tmp_path / "missing-b.jsonl", "environment"),
    ]
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": sample_id,
                    "session": str(session),
                    "human_class": human_class,
                    "labeler": labeler,
                },
                ensure_ascii=False,
            )
            for sample_id, session, human_class in rows
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return labels


def test_attribute_command_writes_accuracy_report(tmp_path: Path) -> None:
    labels = _corpus(tmp_path)
    out = tmp_path / "out"

    result = run_cli("eval", "attribute", "--samples", str(labels), "--out", str(out))

    assert result.returncode == 0, result.stderr
    assert "准确率 10/10（100.0%）" in result.stdout
    report = out / "attribution-report.md"
    assert report.is_file()
    assert "混淆矩阵" in report.read_text(encoding="utf-8")
    payload = json.loads((out / "attribution-report.json").read_text(encoding="utf-8"))
    assert payload["accuracy"] == 1.0


def test_attribute_command_flags_draft_labels(tmp_path: Path) -> None:
    labels = _corpus(tmp_path, labeler="author-draft")
    out = tmp_path / "out"

    result = run_cli("eval", "attribute", "--samples", str(labels), "--out", str(out))

    assert result.returncode == 1
    assert "草稿标注" in result.stdout
    assert "⚠" in (out / "attribution-report.md").read_text(encoding="utf-8")


def test_attribute_dry_run_writes_nothing(tmp_path: Path) -> None:
    labels = _corpus(tmp_path)
    out = tmp_path / "out"

    result = run_cli(
        "eval", "attribute", "--samples", str(labels), "--out", str(out), "--dry-run"
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert not out.exists()


def test_attribute_rejects_too_few_samples(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "id": "only-one",
                "session": str(tmp_path / "x.jsonl"),
                "human_class": "model",
                "labeler": "tester",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_cli("eval", "attribute", "--samples", str(labels))

    assert result.returncode == 2
    assert "至少需要" in result.stderr


def _run_dir(tmp_path: Path, *, passed: bool = False) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    payload = {
        "meta": {"run_id": "run-1"},
        "cases": [
            {
                "task_id": "002-fix-off-by-one",
                "repetition": 1,
                "passed": passed,
                "harness": "codelotte",
                "session_path": None,
                "verifier_detail": "内容不符",
                "error": None,
                "flagged": False,
                "failure_class": "loop",
                "failure_confidence": "high",
                "failure_evidence": "工具层拦截：重复调用 read",
                "failure_signals": ["guardrail:tool:repeat"],
            }
        ],
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def test_regression_command_generates_a_runnable_task(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "002.toml").write_text(TASK, encoding="utf-8", newline="\n")
    out = tmp_path / "regressions" / "regression-002.toml"

    result = run_cli(
        "eval",
        "regression",
        "--run",
        str(_run_dir(tmp_path)),
        "--task",
        "002-fix-off-by-one",
        "--tasks",
        str(tasks),
        "--out",
        str(out),
    )

    assert result.returncode == 0, result.stderr
    task = load_task(out)
    # 仓库里已有示例回归任务时 id 会追加 -2，避免与既有任务冲突
    assert task.id.startswith("regression-002-fix-off-by-one")
    assert task.instruction == "修复 bug"
    text = out.read_text(encoding="utf-8")
    assert "# 来源：run run-1 / 002-fix-off-by-one r1" in text
    assert "# 归因：循环（高）—— 工具层拦截：重复调用 read" in text


def test_regression_refuses_passing_case(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "002.toml").write_text(TASK, encoding="utf-8", newline="\n")

    result = run_cli(
        "eval",
        "regression",
        "--run",
        str(_run_dir(tmp_path, passed=True)),
        "--task",
        "002-fix-off-by-one",
        "--tasks",
        str(tasks),
        "--out",
        str(tmp_path / "out.toml"),
    )

    assert result.returncode == 2
    assert "只从失败生成" in result.stderr
    assert not (tmp_path / "out.toml").exists()


def test_regression_dry_run_writes_nothing(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "002.toml").write_text(TASK, encoding="utf-8", newline="\n")
    out = tmp_path / "out.toml"

    result = run_cli(
        "eval",
        "regression",
        "--run",
        str(_run_dir(tmp_path)),
        "--task",
        "002-fix-off-by-one",
        "--tasks",
        str(tasks),
        "--out",
        str(out),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert not out.exists()


def test_attribute_command_includes_failure_distribution_from_runs(tmp_path: Path) -> None:
    labels = _corpus(tmp_path)
    out = tmp_path / "out"
    run = _run_dir(tmp_path)

    result = run_cli(
        "eval",
        "attribute",
        "--samples",
        str(labels),
        "--out",
        str(out),
        "--run",
        str(run),
    )

    assert result.returncode == 0, result.stderr
    report = (out / "attribution-report.md").read_text(encoding="utf-8")
    assert "## 失败分布" in report
    assert "循环" in report
    payload = json.loads((out / "attribution-report.json").read_text(encoding="utf-8"))
    assert payload["failure_distribution"]["attributed"]["loop"] == 1
    assert payload["failure_distribution"]["total_failures"] == 1
