"""压缩回归套件 v0（票据 13）：任务定义、强制压缩运行、checkpoint 评分与报表。

这是实验设施，不是生产路径：任务文件来自仓库，运行在临时工作区，结果落
`evals/runs/<run-id>/`。通用评测 runner 是票据 15；这里只做压缩质量这一条曲线。
"""

from codelotte.evals.tasks import (
    Checkpoint,
    FileExpectation,
    Task,
    TaskFileError,
    Verifier,
    load_task,
    load_tasks,
)

__all__ = [
    "Checkpoint",
    "FileExpectation",
    "Task",
    "TaskFileError",
    "Verifier",
    "load_task",
    "load_tasks",
]
