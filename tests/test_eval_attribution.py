"""失败归因分类器（票据 18）：五类病位、证据、优先级与样本科普。

测试缝是 `classify_entries`（纯函数：会话记录 + 案例事实 → 归因）与
`evaluate_corpus`（人工标注对照）。分类规则要求可解释，所以断言不仅看类别，
也看证据里有没有关键事实。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from codelotte.evals.attribution import (
    FAILURE_CLASSES,
    AttributionError,
    build_attribution_report,
    classify_entries,
    classify_failure,
    evaluate_corpus,
    load_attribution_samples,
    render_attribution_markdown,
)


def _session(*entries: dict[str, object]) -> list[dict[str, object]]:
    base: list[dict[str, object]] = [
        {
            "type": "session",
            "id": "s1",
            "parentId": None,
            "timestamp": "2026-10-18T00:00:00Z",
            "schema": "session/v1",
            "cwd": "/workspace",
            "version": "0.1.0",
        },
        {
            "type": "message",
            "id": "m1",
            "parentId": "s1",
            "role": "user",
            "content": "完成任务",
        },
    ]
    return base + list(entries)


def _guardrail(layer: str = "tool", guard: str = "repeat") -> dict[str, object]:
    return {
        "type": "event",
        "id": f"g-{layer}-{guard}",
        "parentId": "m1",
        "kind": "guardrail",
        "layer": layer,
        "guard": guard,
        "message": f"{layer} 层拦截：{guard}",
        "count": 3,
        "threshold": 3,
    }


def _read(path: str, *, ok: bool = True, content: str = "data") -> list[dict[str, object]]:
    call_id = f"call-{path}"
    return [
        {
            "type": "tool_call",
            "id": f"tc-{path}",
            "parentId": "m1",
            "toolCallId": call_id,
            "name": "read",
            "arguments": {"path": path},
            "env": "local",
        },
        {
            "type": "tool_result",
            "id": f"tr-{path}",
            "parentId": f"tc-{path}",
            "toolCallId": call_id,
            "name": "read",
            "ok": ok,
            "content": content,
        },
    ]


def _compaction(entry_id: str, first_kept: str = "m1") -> dict[str, object]:
    return {
        "type": "compaction",
        "id": entry_id,
        "parentId": "m1",
        "summary": "摘要",
        "firstKeptEntryId": first_kept,
        "constraints": "硬约束",
        "mode": "soft",
    }


def test_returns_one_of_five_classes() -> None:
    result = classify_entries(_session())
    assert result.failure_class in FAILURE_CLASSES


def test_environment_when_trajectory_is_missing(tmp_path: Path) -> None:
    result = classify_failure(tmp_path / "missing.jsonl")
    assert result.failure_class == "environment"
    assert result.confidence == "high"
    assert "轨迹" in result.evidence


def test_case_level_loop_signal_wins_over_missing_trajectory(
    tmp_path: Path,
) -> None:
    """轨迹缺失时，案例级错误里的预算信号仍然优先（审查修正）。"""
    result = classify_failure(
        tmp_path / "missing.jsonl",
        error="ModelCallBudgetExceeded: 超过 max_model_calls=30",
    )
    assert result.failure_class == "loop"


def test_successful_read_is_not_a_tool_schema_error() -> None:
    """成功读到的正文里出现 schema 字样是数据，不是工具用错了。"""
    entries = _session(
        *_read("a.txt", content="错误：缺少必需参数 old_string"),
    )
    result = classify_entries(entries, verifier_detail="内容不符")
    assert result.failure_class == "model"


def test_environment_on_infrastructure_error() -> None:
    result = classify_entries(
        _session(),
        error="RuntimeError: Cannot connect to the Docker daemon",
    )
    assert result.failure_class == "environment"
    assert "Docker" in result.evidence


def test_docker_timeout_stays_environment() -> None:
    result = classify_entries(
        _session(), error="TimeoutError: Cannot connect to the Docker daemon"
    )
    assert result.failure_class == "environment"


def test_timeout_with_many_tool_results_is_loop() -> None:
    entries = _session(
        *_read("a.txt"),
        *_read("b.txt"),
        *_read("c.txt"),
    )
    result = classify_entries(entries, error="TimeoutError: 任务超时")
    assert result.failure_class == "loop"


def test_environment_on_verifier_crash() -> None:
    result = classify_entries(
        _session(), verifier_detail="验收异常：FileNotFoundError: python"
    )
    assert result.failure_class == "environment"
    assert "验收" in result.evidence


def test_loop_on_guardrail_event() -> None:
    result = classify_entries(_session(_guardrail("tool", "repeat")))
    assert result.failure_class == "loop"
    assert result.confidence == "medium"
    assert "repeat" in result.evidence


def test_loop_on_planning_terminate_is_high_confidence() -> None:
    result = classify_entries(_session(_guardrail("planning", "terminate")))
    assert result.failure_class == "loop"
    assert result.confidence == "high"


def test_loop_on_iteration_limit() -> None:
    result = classify_entries(
        _session(
            {
                "type": "event",
                "id": "it",
                "parentId": "m1",
                "kind": "iterationLimit",
                "iterations": 50,
            }
        )
    )
    assert result.failure_class == "loop"
    assert "迭代" in result.evidence


def test_loop_on_model_call_budget() -> None:
    result = classify_entries(
        _session(),
        error="ModelCallBudgetExceeded: 超过 max_model_calls=30",
    )
    assert result.failure_class == "loop"
    assert "max_model_calls" in result.evidence


def test_tool_schema_on_parse_error() -> None:
    entries = _session(
        {
            "type": "tool_call",
            "id": "tc-bad",
            "parentId": "m1",
            "toolCallId": "call-bad",
            "name": "edit",
            "arguments": "{not json",
            "parseError": "参数不是合法 JSON",
            "env": "local",
        }
    )
    result = classify_entries(entries)
    assert result.failure_class == "tool_schema"
    assert "合法 JSON" in result.evidence


def test_tool_schema_on_missing_argument() -> None:
    entries = _session(
        {
            "type": "tool_call",
            "id": "tc-edit",
            "parentId": "m1",
            "toolCallId": "call-edit",
            "name": "edit",
            "arguments": {},
            "env": "local",
        },
        {
            "type": "tool_result",
            "id": "tr-edit",
            "parentId": "tc-edit",
            "toolCallId": "call-edit",
            "name": "edit",
            "ok": False,
            "content": "错误：缺少必需参数 old_string（应为非空字符串）",
        },
    )
    result = classify_entries(entries)
    assert result.failure_class == "tool_schema"
    assert "缺少必需参数" in result.evidence


def test_tool_schema_on_unknown_tool() -> None:
    entries = _session(
        {
            "type": "tool_result",
            "id": "tr-search",
            "parentId": "m1",
            "toolCallId": "call-search",
            "name": "search",
            "ok": False,
            "content": "错误：未知工具：search",
        }
    )
    result = classify_entries(entries)
    assert result.failure_class == "tool_schema"
    assert "未知工具" in result.evidence


def test_context_loss_when_rereading_after_compaction() -> None:
    entries = _session(
        *_read("a.txt"),
        _compaction("c1"),
        *_read("a.txt"),
    )
    result = classify_entries(entries)
    assert result.failure_class == "context_loss"
    assert "a.txt" in result.evidence
    assert "压缩" in result.evidence


def test_context_loss_needs_a_reread() -> None:
    """只有压缩、没有重新读取，不足以归为上下文丢失——应回落到模型判断。"""
    entries = _session(*_read("a.txt"), _compaction("c1"), *_read("b.txt"))
    result = classify_entries(entries)
    assert result.failure_class == "model"


def test_model_fallback_includes_verifier_detail() -> None:
    result = classify_entries(
        _session(), verifier_detail="内容不符：notes.txt 缺少 for i in range(n):"
    )
    assert result.failure_class == "model"
    assert "notes.txt" in result.evidence
    assert result.confidence == "low"


def test_flagged_case_is_attributed_to_model() -> None:
    result = classify_entries(
        _session(), verifier_detail="保护文件被改动：protected.txt", flagged=True
    )
    assert result.failure_class == "model"
    assert "越界" in result.evidence


def test_environment_wins_over_earlier_loop_signal() -> None:
    result = classify_entries(
        _session(_guardrail("tool", "repeat")),
        error="ConnectionError: 连接被重置",
    )
    assert result.failure_class == "environment"


def test_loop_wins_over_context_loss() -> None:
    result = classify_entries(
        _session(*_read("a.txt"), _compaction("c1"), *_read("a.txt"), _guardrail()),
        verifier_detail="内容不符",
    )
    assert result.failure_class == "loop"


def _write_session(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _corpus(tmp_path: Path) -> Path:
    _write_session(tmp_path / "loop.jsonl", _session(_guardrail()))
    _write_session(tmp_path / "model.jsonl", _session())
    labels = tmp_path / "labels.jsonl"
    rows = [
        {
            "id": "loop-guardrail",
            "session": "loop.jsonl",
            "human_class": "loop",
            "labeler": "tester",
        },
        {
            "id": "model-wrong",
            "session": "model.jsonl",
            "human_class": "model",
            "labeler": "tester",
        },
    ]
    labels.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return labels


def test_evaluate_corpus_reports_accuracy_and_confusion(tmp_path: Path) -> None:
    samples = load_attribution_samples(_corpus(tmp_path))
    run = evaluate_corpus(samples, base_dir=tmp_path)
    assert run.accuracy == 1.0
    assert run.correct == 2
    assert run.total == 2
    assert run.confusion[("loop", "loop")] == 1
    assert run.confusion[("model", "model")] == 1


def test_evaluate_corpus_counts_mismatches(tmp_path: Path) -> None:
    _write_session(tmp_path / "model.jsonl", _session())
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "id": "wrong-label",
                "session": "model.jsonl",
                "human_class": "loop",
                "labeler": "tester",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    run = evaluate_corpus(load_attribution_samples(labels), base_dir=tmp_path)
    assert run.accuracy == 0.0
    assert run.confusion[("loop", "model")] == 1


def test_load_samples_rejects_unknown_class(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    labels.write_text(
        json.dumps(
            {
                "id": "x",
                "session": "missing.jsonl",
                "human_class": "magic",
                "labeler": "tester",
            }
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(AttributionError, match="human_class"):
        load_attribution_samples(labels)


def test_load_samples_rejects_duplicate_ids(tmp_path: Path) -> None:
    labels = tmp_path / "labels.jsonl"
    row = {
        "id": "dup",
        "session": "missing.jsonl",
        "human_class": "model",
        "labeler": "tester",
    }
    labels.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(AttributionError, match="重复"):
        load_attribution_samples(labels)


def test_render_markdown_marks_draft_labels(tmp_path: Path) -> None:
    samples = load_attribution_samples(_corpus(tmp_path))
    draft = [
        replace(sample, labeler="author-draft") for sample in samples
    ]
    draft_run = evaluate_corpus(draft, base_dir=tmp_path)
    text = render_attribution_markdown(draft_run, samples_path=_corpus(tmp_path))
    assert "author-draft" in text
    assert "⚠" in text
    assert "混淆矩阵" in text


def test_build_attribution_report_writes_md_and_json(tmp_path: Path) -> None:
    samples = load_attribution_samples(_corpus(tmp_path))
    run = evaluate_corpus(samples, base_dir=tmp_path)
    path = build_attribution_report(tmp_path / "out", run, samples_path=_corpus(tmp_path))
    assert path.name == "attribution-report.md"
    payload = json.loads((path.parent / "attribution-report.json").read_text("utf-8"))
    assert payload["accuracy"] == 1.0
    assert payload["confusion"]["loop"]["loop"] == 1
