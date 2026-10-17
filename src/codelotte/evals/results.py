"""通用测评的单案例结果（runner 与 report 共用，避免循环导入）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCaseResult:
    """一条任务的一次重复（通用测评 的报表行）。"""

    task_id: str
    bucket: str
    repetition: int
    passed: bool
    verifier_detail: str
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    duration_seconds: float
    periods: tuple[tuple[str, int], ...]
    session_path: str | None
    workspace: str
    error: str | None = None
    harness: str = "codelotte"
    flagged: bool = False
    flag_reason: str | None = None
    harness_version: str | None = None
    note: str | None = None
