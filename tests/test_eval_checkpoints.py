"""Checkpoint 评分（票据 13）：确定性比对为主，人工标注是补充。

评分规则：每个问题的事实组全部命中才算通过；每组给若干可接受替代表述。
编号解析失败时整段答案作为兜底，并标记 structured=False（报表里可见）。
"""

from __future__ import annotations

from codelotte.evals.checkpoints import (
    CheckpointScore,
    score_answer,
    split_sections,
)
from codelotte.evals.tasks import Checkpoint

CHECKPOINTS = (
    Checkpoint(question="任务目标是什么？", facts=(("report.txt",), ("TODO",))),
    Checkpoint(question="完成了哪些步骤？", facts=(("a.txt",), ("read", "读取"))),
    Checkpoint(question="有哪些约束？", facts=(("顺序", "依次"), ("不得", "不要"))),
)

ANSWER = """1. 目标是生成 report.txt，统计每个文件的 TODO。
2. 已经读取了 a.txt。
3. 必须按顺序输出，不得写其他内容。
"""


def test_scores_numbered_answers_question_by_question() -> None:
    result = score_answer(ANSWER, CHECKPOINTS)

    assert result.structured is True
    assert [score.passed for score in result.scores] == [True, True, True]
    assert all(score.local_passed for score in result.scores)
    assert all(score.misplaced == () for score in result.scores)
    assert all(isinstance(score, CheckpointScore) for score in result.scores)


def test_missing_fact_fails_only_that_question() -> None:
    answer = ANSWER.replace("统计每个文件的 TODO", "生成报告").replace(
        "a.txt", "某个文件"
    )

    result = score_answer(answer, CHECKPOINTS)

    assert [score.passed for score in result.scores] == [False, False, True]
    assert result.scores[0].missing == ("TODO",)
    assert result.scores[1].missing == ("a.txt",)


def test_accepts_alternative_phrasings() -> None:
    answer = """1. 生成 report.txt，数一下 TODO。
2. 读取了 a.txt。
3. 依次输出，不要多写。
"""

    result = score_answer(answer, CHECKPOINTS)

    assert all(score.passed for score in result.scores)


def test_a_fact_missing_everywhere_still_fails() -> None:
    """整段都没提到的 TODO 仍然算丢失（保留率不是只看分段）。"""
    answer = """1. 目标是生成 report.txt。
2. 读取了 a.txt。
3. 必须按顺序输出，不得写其他内容。
"""

    result = score_answer(answer, CHECKPOINTS)

    assert [score.passed for score in result.scores] == [False, True, True]
    assert result.scores[0].missing == ("TODO",)


def test_a_fact_answered_in_another_section_is_retained_but_marked_misplaced() -> None:
    """序号写在约束段而不是目标段：保留率算命中，分段合规单独记录。"""
    answer = """1. 目标是生成 report.txt，并注意 TODO。
2. 读取了 a.txt。
3. 必须按顺序输出，不得写其他内容。
"""

    answer_without_todo = answer.replace("，并注意 TODO", "")
    result = score_answer(answer_without_todo, CHECKPOINTS)
    assert result.scores[0].passed is False  # 整段确实没有 TODO

    result = score_answer(answer, CHECKPOINTS)
    assert result.scores[0].passed is True
    assert result.scores[0].local_passed is True  # TODO 在目标段
    # 构造一个跨段例子：目标段不提 TODO，约束段提到
    crossed = """1. 目标是生成 report.txt。
2. 读取了 a.txt。
3. TODO 必须按顺序输出，不得写其他内容。
"""
    crossed_result = score_answer(crossed, CHECKPOINTS)
    assert crossed_result.scores[0].passed is True
    assert crossed_result.scores[0].local_passed is False
    assert crossed_result.scores[0].misplaced == ("TODO",)


def test_unstructured_answer_is_flagged_but_still_scored() -> None:
    result = score_answer(
        "目标 report.txt TODO；读取了 a.txt；按顺序不得多写。", CHECKPOINTS
    )

    assert result.structured is False
    assert all(score.passed for score in result.scores)


def test_split_sections_handles_chinese_and_parenthesized_numbering() -> None:
    sections, structured = split_sections(
        "1、第一段\n2）第二段\n3. 第三段\n", 3
    )

    assert structured is True
    assert sections == ["第一段", "第二段", "第三段"]
