"""Checkpoint 的确定性评分（票据 13）。

压缩后问模型"任务目标/已完成/约束"，再按任务预定义的事实组逐条比对。规则刻意简单：
- 每个问题只看自己编号段（避免别的问题里的词"串门"）；
- 每个事实组给若干可接受替代表述，任一命中即可；所有组命中才算这个问题通过；
- 编号解析失败时整段答案作为兜底，并标记 structured=False——报表里保留这个事实，
  人工标注时优先复核这些行。

这不是 LLM judge；它是可复现的代理指标，人工标注是补充（见 docs/tech/compaction-regression.md）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from codelotte.evals.tasks import Checkpoint

_SECTION_MARKER = re.compile(r"(?m)^\s*(\d+)\s*[.、)）．:：]\s*")
_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """大小写无关、空白折叠——中英文答案用同一条比对规则。"""
    return _WHITESPACE.sub(" ", text).strip().casefold()


@dataclass(frozen=True)
class CheckpointScore:
    """一个 checkpoint 问题的判定。matched/missing 用事实组的首个替代表述做标签。

    passed = 事实在**整段回答**中出现（关键状态保留率的口径）；
    local_passed = 事实出现在该问题自己的编号段（分段合规，供明细参考）；
    misplaced = 只在本段外出现的事实（答对了，但答错了位置）。
    """

    question: str
    passed: bool
    local_passed: bool
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    misplaced: tuple[str, ...]


@dataclass(frozen=True)
class AnswerScore:
    """一次 checkpoint 回答的全部判定；structured=False 表示编号解析失败。"""

    scores: tuple[CheckpointScore, ...]
    structured: bool

    @property
    def passed(self) -> int:
        return sum(1 for score in self.scores if score.passed)

    @property
    def total(self) -> int:
        return len(self.scores)


def split_sections(answer: str, count: int) -> tuple[list[str], bool]:
    """按 `1.` / `1、` / `1)` 等编号切段，返回长度恒为 count 的列表。

    找不到任何编号：整段答案作为每个问题的兜底文本，structured=False。
    只找到部分编号：缺失段为空串（该问题自然不通过），structured=False。
    """
    matches = list(_SECTION_MARKER.finditer(answer))
    if not matches:
        fallback = normalize(answer)
        return [fallback] * count, False
    first_by_number: dict[int, re.Match[str]] = {}
    for match in matches:
        number = int(match.group(1))
        first_by_number.setdefault(number, match)
    ordered = sorted(first_by_number.values(), key=lambda match: match.start())
    sections: list[str] = []
    for number in range(1, count + 1):
        match = first_by_number.get(number)
        if match is None:
            sections.append("")
            continue
        position = ordered.index(match)
        end = ordered[position + 1].start() if position + 1 < len(ordered) else len(answer)
        sections.append(normalize(answer[match.end() : end]))
    structured = all(number in first_by_number for number in range(1, count + 1))
    return sections, structured


def _match(
    text: str, facts: tuple[tuple[str, ...], ...]
) -> tuple[list[str], list[str]]:
    matched: list[str] = []
    missing: list[str] = []
    for alternatives in facts:
        label = alternatives[0]
        if any(normalize(alternative) in text for alternative in alternatives):
            matched.append(label)
        else:
            missing.append(label)
    return matched, missing


def score_checkpoint(
    text: str, checkpoint: Checkpoint, *, whole: str | None = None
) -> CheckpointScore:
    """按事实组判定；`text` 是本题的编号段，`whole` 是整段回答（保留率口径）。

    模型常把格式/约束写在另一个编号段：事实只要在整段回答里出现就算"还记得"，
    但 `misplaced` 会把这个位置问题记下来，供人工与明细复核。
    """
    local_text = normalize(text)
    whole_text = normalize(whole) if whole is not None else local_text
    local_matched, local_missing = _match(local_text, checkpoint.facts)
    matched, missing = _match(whole_text, checkpoint.facts)
    missing_set = set(missing)
    misplaced = tuple(label for label in local_missing if label not in missing_set)
    return CheckpointScore(
        question=checkpoint.question,
        passed=not missing,
        local_passed=not local_missing,
        matched=tuple(matched),
        missing=tuple(missing),
        misplaced=misplaced,
    )


def score_answer(answer: str, checkpoints: tuple[Checkpoint, ...]) -> AnswerScore:
    """一次回答 → 每个 checkpoint 一个判定（编号段与问题按顺序对应）。"""
    sections, structured = split_sections(answer, len(checkpoints))
    whole = normalize(answer)
    return AnswerScore(
        scores=tuple(
            score_checkpoint(section, checkpoint, whole=whole)
            for section, checkpoint in zip(sections, checkpoints)
        ),
        structured=structured,
    )
