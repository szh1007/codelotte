"""评测设施：任务定义（票据 15 通用格式）、压缩回归（票据 13）与通用测评（票据 15）。

任务文件来自仓库，运行在临时工作区，结果落 `evals/runs/<run-id>/`。这是实验设施，
不是生产路径；生产入口仍是 `codelotte` 的 TUI / `-p`。
"""

from codelotte.evals.tasks import (
    Checkpoint,
    FileExpectation,
    Snapshot,
    Task,
    TaskFileError,
    Verifier,
    load_task,
    load_tasks,
)

__all__ = [
    "Checkpoint",
    "FileExpectation",
    "Snapshot",
    "Task",
    "TaskFileError",
    "Verifier",
    "load_task",
    "load_tasks",
]
