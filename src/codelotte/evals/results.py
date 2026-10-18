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
    judge_calls: int = 0
    judge_cost: float = 0.0
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0
    # judge 路径被激活（含“声明了但缺 judge 模型”的失败）；实际调用数看 judge_calls
    judge_used: bool = False
    judge_passed: bool | None = None
    judge_overall: float | None = None
    judge_scores: tuple[tuple[str, float], ...] = ()
    judge_reasons: tuple[tuple[str, str], ...] = ()
    judge_error: str | None = None
    judge_kappa: float | None = None
    judge_samples: int | None = None
    judge_reliable: bool | None = None
    judge_warning: str | None = None
