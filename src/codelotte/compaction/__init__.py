"""压缩 v1（票据 12）：双触发、结构化摘要、约束重注入与压缩后上下文装配。"""

from codelotte.compaction.summarize import (
    COMPACTION_CONSTRAINTS,
    SUMMARY_INSTRUCTION,
    SUMMARY_SECTIONS,
    build_compaction_messages,
    build_summary_messages,
)
from codelotte.compaction.trigger import (
    HARD_THRESHOLD,
    SOFT_THRESHOLD,
    CompactionDecision,
    CompactionLimits,
    CompactionMode,
    context_tokens_from_entries,
    estimate_tokens,
    is_git_commit_command,
    minimum_keep_index,
    plan_compaction,
    task_boundaries,
)

__all__ = [
    "COMPACTION_CONSTRAINTS",
    "HARD_THRESHOLD",
    "SOFT_THRESHOLD",
    "SUMMARY_INSTRUCTION",
    "SUMMARY_SECTIONS",
    "CompactionDecision",
    "CompactionLimits",
    "CompactionMode",
    "build_compaction_messages",
    "build_summary_messages",
    "context_tokens_from_entries",
    "estimate_tokens",
    "is_git_commit_command",
    "minimum_keep_index",
    "plan_compaction",
    "task_boundaries",
]
