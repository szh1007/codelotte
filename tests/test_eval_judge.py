"""LLM judge 兜底（票据 17）：评分卡解析、κ 校准与可读报告。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from codelotte.evals.judge import (
    JudgeContext,
    JudgeError,
    JudgeSample,
    build_submission,
    calibrate,
    cohen_kappa,
    judge_fingerprint,
    judge_reliability,
    load_calibration,
    parse_judge_payload,
    run_judge_submission,
    write_calibration,
)
from codelotte.evals.tasks import Judge
from tests.fake_client import ScriptedClient, fake_catalog, text_turn


def _judge(*, threshold: float = 0.6, kappa_threshold: float = 0.6) -> Judge:
    return Judge(
        dimensions=("correctness", "clarity"),
        rubric="correctness: 指出 bug；clarity: 结构清晰",
        pass_threshold=threshold,
        kappa_threshold=kappa_threshold,
    )


def _payload(
    *, correctness: float = 0.9, clarity: float = 0.7
) -> str:
    return json.dumps(
        {
            "scores": {"correctness": correctness, "clarity": clarity},
            "reasons": {
                "correctness": "指出了 range(n + 1) 的错误",
                "clarity": "结构清晰",
            },
        },
        ensure_ascii=False,
    )


def _context(client: ScriptedClient) -> JudgeContext:
    return JudgeContext(
        client_factory=lambda: client,
        model="fake-model",
        catalog=fake_catalog(),
    )


def _samples() -> list[JudgeSample]:
    samples: list[JudgeSample] = []
    for index in range(20):
        good = index < 10
        samples.append(
            JudgeSample(
                id=f"s{index:02d}",
                submission=f"submission {index}",
                human_pass=good,
                labeler="author-draft",
            )
        )
    return samples


def test_cohen_kappa_perfect_agreement() -> None:
    kappa, agreement = cohen_kappa([True, True, False, False], [True, True, False, False])

    assert kappa == pytest.approx(1.0)
    assert agreement == pytest.approx(1.0)


def test_cohen_kappa_chance_level_agreement() -> None:
    # judge 全 true，human 一半 true：po=0.5，pe=0.5 → κ=0
    kappa, agreement = cohen_kappa([True] * 4, [True, True, False, False])

    assert kappa == pytest.approx(0.0)
    assert agreement == pytest.approx(0.5)


def test_cohen_kappa_is_undefined_for_a_single_class() -> None:
    kappa, agreement = cohen_kappa([True] * 4, [True] * 4)

    assert kappa is None
    assert agreement == pytest.approx(1.0)


def test_parse_judge_payload_accepts_fenced_json() -> None:
    parsed = parse_judge_payload(
        "```json\n" + _payload() + "\n```", ("correctness", "clarity")
    )

    assert parsed.scores == (("correctness", 0.9), ("clarity", 0.7))
    assert parsed.reasons[0][0] == "correctness"
    assert parsed.overall == pytest.approx(0.8)


def test_parse_judge_payload_rejects_a_missing_dimension() -> None:
    with pytest.raises(JudgeError, match="clarity"):
        parse_judge_payload(
            json.dumps(
                {
                    "scores": {"correctness": 0.9},
                    "reasons": {"correctness": "ok"},
                }
            ),
            ("correctness", "clarity"),
        )


def test_build_submission_caps_large_and_marks_binary_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("hello\n", encoding="utf-8")
    (workspace / "big.txt").write_text("x" * 500, encoding="utf-8")
    (workspace / "blob.bin").write_bytes(b"\xff\xfe\x00\x01")

    submission = build_submission(workspace, max_chars=120)

    assert "a.txt" in submission
    assert "binary" in submission.lower()
    assert "truncated" in submission.lower()


def test_run_judge_submission_prices_usage_and_parses_scores() -> None:
    client = ScriptedClient([text_turn(_payload(), usage=(100, 20, 40, 60))])
    result = asyncio.run(
        run_judge_submission(
            _context(client),
            instruction="写 review.md",
            judge=_judge(threshold=0.7),
            submission="review",
            deterministic_detail="review.md 包含 range(n)",
        )
    )

    assert result.error is None
    assert result.passed is True
    assert result.overall == pytest.approx(0.8)
    assert result.calls == 1
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cost == pytest.approx(0.0002816)
    assert client.tool_schemas == [None]
    assert "correctness" in client.requests[0][-1]["content"]


def test_run_judge_submission_reports_bad_json() -> None:
    client = ScriptedClient([text_turn("not json")])

    result = asyncio.run(
        run_judge_submission(
            _context(client),
            instruction="x",
            judge=_judge(),
            submission="y",
            deterministic_detail="无",
        )
    )

    assert result.error is not None
    assert result.passed is None


def test_calibration_requires_twenty_samples() -> None:
    client = ScriptedClient([text_turn(_payload())] * 19)
    with pytest.raises(JudgeError, match="20"):
        asyncio.run(
            calibrate(
                _context(client),
                instruction="x",
                judge=_judge(),
                samples=_samples()[:19],
            )
        )


def test_calibration_computes_kappa_and_writes_artifacts(tmp_path: Path) -> None:
    # 20 条样本，前 10 条 human=true/judge=true，后 10 条 human=false/judge=false
    turns = []
    for index in range(20):
        score = 0.9 if index < 10 else 0.1
        turns.append(text_turn(_payload(correctness=score, clarity=score)))
    client = ScriptedClient(turns)
    labels = tmp_path / "samples.jsonl"
    labels.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": sample.id,
                    "submission": sample.submission,
                    "human_pass": sample.human_pass,
                    "labeler": sample.labeler,
                },
                ensure_ascii=False,
            )
            for sample in _samples()
        )
        + "\n",
        encoding="utf-8",
    )

    result = asyncio.run(
        calibrate(
            _context(client),
            instruction="x",
            judge=_judge(),
            samples=_samples(),
        )
    )

    assert result.kappa == pytest.approx(1.0)
    assert result.samples == 20
    assert result.cost > 0
    calibration_path = write_calibration(
        tmp_path / "calibration.json",
        task_id="judge-task",
        instruction="写 review",
        judge=_judge(),
        run=result,
        labels_path=labels,
    )
    data = json.loads(calibration_path.read_text(encoding="utf-8"))
    assert data["schema"] == "judge-calibration/v1"
    assert data["kappa"] == pytest.approx(1.0)
    assert data["samples"] == 20
    assert (tmp_path / "calibration.md").is_file()


def test_low_kappa_marks_the_verifier_unreliable(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "judge-calibration/v1",
                "task_id": "t",
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

    calibration = load_calibration(path)
    reliable, warning = judge_reliability(_judge(), calibration)

    assert reliable is False
    assert warning is not None and "κ" in warning


def test_draft_labels_are_marked_unreliable_even_with_high_kappa(
    tmp_path: Path,
) -> None:
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "judge-calibration/v1",
                "task_id": "t",
                "model": "m",
                "samples": 20,
                "labeler": "author-draft",
                "kappa": 0.9,
                "agreement": 0.9,
                "kappa_threshold": 0.6,
                "pass_threshold": 0.6,
                "generated_at": "2026-10-18T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    reliable, warning = judge_reliability(_judge(), load_calibration(path))

    assert reliable is False
    assert warning is not None and "draft" in warning


def test_calibration_binding_rejects_model_or_label_changes(tmp_path: Path) -> None:
    judge = _judge()
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "judge-calibration/v1",
                "task_id": "t",
                "model": "old-model",
                "samples": 20,
                "labeler": "human",
                "kappa": 0.9,
                "agreement": 0.9,
                "kappa_threshold": 0.6,
                "pass_threshold": 0.6,
                "generated_at": "2026-10-18T00:00:00+00:00",
                "judge_fingerprint": judge_fingerprint("t", "x", judge),
                "labels_sha256": "old-labels",
            }
        ),
        encoding="utf-8",
    )

    reliable, warning = judge_reliability(
        judge,
        load_calibration(path),
        task_id="t",
        instruction="x",
        model="new-model",
        labels_sha256="new-labels",
    )

    assert reliable is False
    assert warning is not None
    assert "模型" in warning
    assert "样本文件" in warning


def test_calibration_binding_rejects_a_changed_rubric(tmp_path: Path) -> None:
    old_judge = _judge()
    new_judge = Judge(
        dimensions=("correctness", "clarity"),
        rubric="新的 rubric",
        pass_threshold=0.6,
        kappa_threshold=0.6,
    )
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "judge-calibration/v1",
                "task_id": "t",
                "model": "m",
                "samples": 20,
                "labeler": "human",
                "kappa": 0.9,
                "agreement": 0.9,
                "kappa_threshold": 0.6,
                "pass_threshold": 0.6,
                "generated_at": "2026-10-18T00:00:00+00:00",
                "judge_fingerprint": judge_fingerprint("t", "x", old_judge),
            }
        ),
        encoding="utf-8",
    )

    reliable, warning = judge_reliability(
        new_judge,
        load_calibration(path),
        task_id="t",
        instruction="x",
        model="m",
    )

    assert reliable is False
    assert warning is not None and "过期" in warning


def test_missing_calibration_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(JudgeError, match="校准"):
        load_calibration(tmp_path / "missing.json")
