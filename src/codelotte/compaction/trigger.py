"""压缩触发判定（票据 12）：纯函数，只读会话记录，不碰网络/文件。

双触发（SPEC §F）：
- 软触发：利用率 ≥ 60%，在最近的任务边界压缩（用户消息 ∪ 成功 git commit 点），
  避免把"做到一半"的操作链截断；
- 硬触发：利用率 ≥ 85%，压到最小保留集（最近一轮），不等边界。

利用率 = 上一次请求的实际 input tokens / 用户级生效窗口（spec.context_window）。
窗口被用户下调后，同一份上下文可能从 80% 变成 120%——硬触发天然覆盖超 100%。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # 只为类型标注：纯判定模块不依赖配置加载
    from codelotte.config import Settings

SOFT_THRESHOLD = 0.60
HARD_THRESHOLD = 0.85

CompactionMode = Literal["soft", "hard"]


@dataclass(frozen=True)
class CompactionLimits:
    """压缩双阈值（settings.json 的 compaction* 键；默认为 0.60 / 0.85）。"""

    soft: float = SOFT_THRESHOLD
    hard: float = HARD_THRESHOLD

    @classmethod
    def from_settings(cls, settings: Settings) -> CompactionLimits:
        """settings.json 的可选覆盖 + 本类默认值（唯一默认值来源）。"""
        defaults = cls()
        return cls(
            soft=(
                settings.compaction_soft_threshold
                if settings.compaction_soft_threshold is not None
                else defaults.soft
            ),
            hard=(
                settings.compaction_hard_threshold
                if settings.compaction_hard_threshold is not None
                else defaults.hard
            ),
        )

_SEGMENT_SEPARATOR = re.compile(r"[;&|\n]+")


@dataclass(frozen=True)
class CompactionDecision:
    """一次压缩的决定：模式、保留边界（firstKeptEntryId）与触发时的利用率。"""

    mode: CompactionMode
    cut_index: int
    first_kept_entry_id: str
    utilization: float


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """本地估算器（SPEC §E 口径：字符 / 4）。只用于展示压缩后大小与最小集警告，
    触发本身以 API 返回的 usage 为准。"""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += len(content)
        for call in message.get("tool_calls") or []:
            function = call.get("function") if isinstance(call, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str):
                total += len(arguments)
    if total <= 0:
        return 0
    return max(1, total // 4)


def is_git_commit_command(command: str) -> bool:
    """命令是否是 `git commit`（按 shell 分隔符分段、只看每段开头的 git）。

    启发式：`git commit` / `git -C x commit` / `cd repo && git commit` 命中；
    `git log --grep=commit`、`git commit-tree`、`echo git commit` 不命中。
    足够用于任务边界识别，不追求 shell 全语法。
    """
    for segment in _SEGMENT_SEPARATOR.split(command):
        tokens = segment.strip().split()
        if not tokens:
            continue
        if (tokens[0] == "git" or tokens[0].endswith("/git")) and "commit" in tokens[1:]:
            return True
    return False


def _tool_call_owners(entries: list[dict[str, Any]]) -> dict[str, int]:
    """toolCallId → 声明它的 assistant message 索引（工具链的安全切点）。"""
    owners: dict[str, int] = {}
    for index, entry in enumerate(entries):
        if entry.get("type") != "message" or entry.get("role") != "assistant":
            continue
        for call in entry.get("toolCalls") or []:
            call_id = call.get("id") if isinstance(call, dict) else None
            if isinstance(call_id, str):
                owners[call_id] = index
    return owners


def task_boundaries(entries: list[dict[str, Any]]) -> list[int]:
    """任务边界（升序）：用户消息位置 ∪ 成功 git commit 所属 assistant 消息位置。

    git commit 的切点取声明这次调用的 assistant message——只保留 tool_result 会让协议
    缺失 tool_call 的声明者，恢复后的请求非法。
    """
    boundaries = {
        index
        for index, entry in enumerate(entries)
        if entry.get("type") == "message" and entry.get("role") == "user"
    }
    calls = {
        str(entry.get("toolCallId")): entry
        for entry in entries
        if entry.get("type") == "tool_call"
    }
    owners = _tool_call_owners(entries)
    for entry in entries:
        if entry.get("type") != "tool_result" or not entry.get("ok"):
            continue
        call = calls.get(str(entry.get("toolCallId")))
        if call is None or call.get("name") != "bash":
            continue
        arguments = call.get("arguments")
        command = arguments.get("command") if isinstance(arguments, dict) else None
        owner = owners.get(str(entry.get("toolCallId")))
        if isinstance(command, str) and owner is not None and is_git_commit_command(command):
            boundaries.add(owner)
    return sorted(boundaries)


def minimum_keep_index(entries: list[dict[str, Any]]) -> int | None:
    """最小保留集的起点：run 的最后一个 turn（最后一条 assistant）或刚输入的用户消息。

    术语：一个 run（`AgentLoop.run`，用户一句话到最终回答）可以包含多个 turn
    （一次 assistant 回复 + 它声明的工具链）。这里只保留**最后一个 turn**，不是整个 run——
    单 run 长任务里更早的 turn 仍要能被摘要掉。

    摘要 + 硬约束 + 这个 turn = 不可再压的下限。最后一条已是 compaction 时没有新 turn 可保留，
    返回 None（避免在同一份上下文上反复压缩）。
    """
    if not entries:
        return None
    last_index = len(entries) - 1
    last = entries[last_index]
    if last.get("type") == "compaction":
        return None
    if last.get("type") == "message" and last.get("role") == "user":
        return last_index
    for index in range(last_index, -1, -1):
        entry = entries[index]
        if entry.get("type") == "message" and entry.get("role") == "assistant":
            return index
    for index in range(last_index, -1, -1):
        entry = entries[index]
        if entry.get("type") == "message" and entry.get("role") == "user":
            return index
    return None


def _last_compaction_index(entries: list[dict[str, Any]]) -> int:
    for index in range(len(entries) - 1, -1, -1):
        if entries[index].get("type") == "compaction":
            return index
    return -1


def plan_compaction(
    entries: list[dict[str, Any]],
    *,
    input_tokens: int,
    context_window: int,
    soft: float = SOFT_THRESHOLD,
    hard: float = HARD_THRESHOLD,
) -> CompactionDecision | None:
    """按使用率决定是否压缩，以及切在哪条记录上。

    - 软触发：最新任务边界（只考虑上一次压缩之后的边界，且不能切掉最小保留集）；
    - 硬触发：最小保留集（不等边界）。
    没有可切的位置（例如刚压缩完、没有新一轮）时返回 None。
    """
    if context_window <= 0 or input_tokens < 0:
        return None
    utilization = input_tokens / context_window
    if utilization < soft:
        return None

    last_compaction = _last_compaction_index(entries)
    keep = minimum_keep_index(entries)
    if keep is None or keep <= last_compaction:
        return None

    mode: CompactionMode
    if utilization >= hard:
        cut_index = keep
        mode = "hard"
    else:
        candidates = [
            boundary
            for boundary in task_boundaries(entries)
            if last_compaction < boundary <= keep
        ]
        if not candidates:
            return None
        cut_index = max(candidates)
        mode = "soft"

    entry_id = entries[cut_index].get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return None
    return CompactionDecision(
        mode=mode,
        cut_index=cut_index,
        first_kept_entry_id=entry_id,
        utilization=utilization,
    )


def context_tokens_from_entries(entries: list[dict[str, Any]]) -> int:
    """恢复会话时的当前上下文大小：最后一次 usage，或其后的 compaction 估算值。

    压缩调用本身的 usage 记录在 compaction entry 之前；后者必须覆盖它，否则
    `--continue` 会用"摘要请求的输入大小"再触发一次压缩。
    """
    tokens = 0
    for entry in entries:
        if entry.get("type") == "usage":
            value = entry.get("inputTokens")
            if isinstance(value, int) and not isinstance(value, bool):
                tokens = value
        elif entry.get("type") == "compaction":
            value = entry.get("estimatedAfterTokens")
            if isinstance(value, int) and not isinstance(value, bool):
                tokens = value
    return tokens
