"""单任务执行核心（票据 15 抽出；票据 16 增加 harness 缝）：准备 → 跑 agent → 验收。

压缩回归（票据 13）、通用测评（票据 15）、对照组与控制 agent（票据 16）共用同一条
管线：工作区准备、预算、错误记录、成本/时段累计、验收、保护文件检查。不同 harness
只负责"在被准备好的工作区里跑一次"，验收与防篡改检查不归它们管。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from codelotte import __version__
from codelotte.compaction import CompactionLimits, CompactionPolicy
from codelotte.cost import Catalog
from codelotte.evals.harness_types import Harness, HarnessExecution
from codelotte.evals.judge import (
    JudgeContext,
    JudgeError,
    build_submission,
    file_sha256,
    judge_reliability,
    load_calibration,
    run_judge_submission,
)
from codelotte.evals.tasks import Task
from codelotte.evals.workspace import (
    capture_unchanged_baseline,
    prepare_workspace,
    tampered_paths,
    verify,
)
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import AgentLoop, CompactionEvent, CostRecorded, StreamingClient
from codelotte.permissions import allow_builtin_tools
from codelotte.sandbox import Executor
from codelotte.session.store import SessionStore
from codelotte.tools import default_tools

logger = logging.getLogger(__name__)


class ModelCallBudgetExceeded(RuntimeError):
    """任务超过 max_model_calls（防回归实验意外烧钱/死循环）。"""


@dataclass(frozen=True)
class ProbeUsage:
    """一次压缩后探针的 token 与成本（由调用方决定探针做什么）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


CompactionObserver = Callable[[AgentLoop, int], Awaitable[ProbeUsage | None]]


@dataclass(frozen=True)
class TaskExecution:
    """一次任务执行的原始结果；压缩/通用/对照报表各自从中取字段。"""

    completed: bool
    verifier_detail: str
    compactions: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    probe_input_tokens: int
    probe_output_tokens: int
    cost: float
    probe_cost: float
    duration_seconds: float
    session_path: str | None
    workspace: str
    periods: tuple[tuple[str, int], ...]
    error: str | None
    flagged: bool = False
    flag_reason: str | None = None
    harness_version: str | None = None
    note: str | None = None
    # 票据 17：judge 的成本/分数/理由与 κ 可靠性（未声明 judge 或未运行时全为 0/None）
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


@dataclass(frozen=True)
class CodelotteHarness:
    """codelotte 自己的 agent loop（真实被测 harness）。"""

    client: StreamingClient
    model: str
    catalog: Catalog
    executor_factory: Callable[[], Executor]
    context_window: int
    compaction_policy: CompactionPolicy | None = None
    compaction_limits: CompactionLimits | None = None
    guardrail_limits: GuardrailLimits | None = None
    on_compaction: CompactionObserver | None = None
    isolation: str = "unknown"
    name: str = "codelotte"
    kind: str = "agent"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        """跑一次真实 loop；异常落成 error，不掀翻整轮实验。"""
        compactions = 0
        model_calls = 0
        input_tokens = 0
        output_tokens = 0
        probe_input_tokens = 0
        probe_output_tokens = 0
        cost = 0.0
        probe_cost = 0.0
        periods: dict[str, int] = {}
        session_path: str | None = None
        error: str | None = None
        executor: Executor | None = None
        try:
            # 评测工作区路径长，用短案例名做会话目录，避免 Windows 260 字符上限
            store = SessionStore.start(
                workspace, base_dir=session_root, directory_name=case_name
            )
            session_path = str(store.path)
            executor = self.executor_factory()
            loop = AgentLoop(
                client=self.client,
                tools=default_tools(executor),
                store=store,
                model=self.model,
                catalog=self.catalog,
                permissions=allow_builtin_tools(),
                env=executor.env,
                context_window=self.context_window,
                compaction_limits=self.compaction_limits,
                guardrail_limits=self.guardrail_limits,
                compaction_policy=self.compaction_policy,
            )
            async for event in loop.run(task.instruction):
                if isinstance(event, CostRecorded):
                    model_calls += 1
                    input_tokens += event.record.input_tokens
                    output_tokens += event.record.output_tokens
                    cost += event.record.cost or 0.0
                    period = event.record.period or "unknown"
                    periods[period] = periods.get(period, 0) + 1
                    # 软上限：usage 在调用完成后才到，最多越过一格才中止（防跑飞，不做精确配额）
                    if model_calls > task.max_model_calls:
                        raise ModelCallBudgetExceeded(
                            f"超过 max_model_calls={task.max_model_calls}"
                        )
                elif isinstance(event, CompactionEvent):
                    compactions += 1
                    if self.on_compaction is not None:
                        probe = await self.on_compaction(loop, compactions)
                        if probe is not None:
                            probe_input_tokens += probe.input_tokens
                            probe_output_tokens += probe.output_tokens
                            probe_cost += probe.cost
        except Exception as exc:  # 单条案例隔离：任何异常落成 case error，不能掀翻整轮实验
            logger.exception("案例失败：%s", task.id)
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if executor is not None:
                await executor.close()
        return HarnessExecution(
            compactions=compactions,
            model_calls=model_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            probe_input_tokens=probe_input_tokens,
            probe_output_tokens=probe_output_tokens,
            cost=cost,
            probe_cost=probe_cost,
            periods=tuple(sorted(periods.items())),
            session_path=session_path,
            error=error,
            harness_version=__version__,
        )


async def execute_harness(
    task: Task,
    harness: Harness,
    *,
    workspace: Path,
    session_root: Path,
    repo_root: Path | None,
    snapshot_ref: str | None,
    judge_context: JudgeContext | None = None,
) -> TaskExecution:
    """所有 harness 共用的执行管线：准备 → 跑 → 确定性验收 → judge → 保护文件检查。"""
    started = time.monotonic()
    # 必须在 chdir 之前把路径钉成绝对路径：否则相对 --out 会在工作区里长出
    # sessions/（既污染被测环境，又让报表里的顶层 sessions/ 为空）。
    workspace = workspace.resolve()
    session_root = session_root.resolve()
    prepared = False
    unchanged_baseline: dict[str, str | None] | None = None
    execution = HarnessExecution()
    outer_error: str | None = None
    old_cwd = Path.cwd()
    before_files: set[Path] = set()
    try:
        prepare_workspace(
            task,
            workspace,
            repo_root=repo_root,
            snapshot_ref=snapshot_ref,
        )
        prepared = True
        unchanged_baseline = capture_unchanged_baseline(task, workspace)
        session_root.mkdir(parents=True, exist_ok=True)
        before_files = {path for path in session_root.rglob("*") if path.is_file()}
        os.chdir(workspace)
        async with asyncio.timeout(task.timeout_seconds):
            execution = await harness.run(
                task,
                workspace=workspace,
                session_root=session_root,
                case_name=workspace.name,
            )
    except Exception as exc:  # harness 自身没接住的异常也落成 case error
        logger.exception("案例失败：%s", task.id)
        outer_error = f"{type(exc).__name__}: {exc}"
    finally:
        os.chdir(old_cwd)

    error = execution.error or outer_error
    session_path = execution.session_path
    if session_path is None and prepared:
        # harness 被外层超时打断时来不及返回 session_path；从本轮新增文件里找轨迹，
        # 保证失败案例仍能定位（codelotte .jsonl / mini 轨迹 .json / 日志）。
        new_files = [
            path
            for path in session_root.rglob("*")
            if path.is_file()
            and path not in before_files
            and not any(part.endswith("-mini-home") for part in path.parts)
            and path.suffix in {".jsonl", ".json", ".log"}
        ]
        if new_files:
            try:
                newest = max(new_files, key=lambda path: path.stat().st_mtime)
            except OSError as exc:
                logger.warning(
                    "轨迹文件 mtime 读不动，退回首个候选：%s: %s",
                    type(exc).__name__,
                    exc,
                )
                newest = new_files[0]
            session_path = str(newest)
    judge_calls = 0
    judge_cost = 0.0
    judge_input_tokens = 0
    judge_output_tokens = 0
    judge_used = False
    judge_passed: bool | None = None
    judge_overall: float | None = None
    judge_scores: tuple[tuple[str, float], ...] = ()
    judge_reasons: tuple[tuple[str, str], ...] = ()
    judge_error: str | None = None
    judge_kappa: float | None = None
    judge_samples: int | None = None
    judge_reliable: bool | None = None
    judge_warning: str | None = None
    total_calls = execution.model_calls
    total_cost = execution.cost
    periods = dict(execution.periods)
    if prepared:
        try:
            completed, detail = verify(
                task, workspace, unchanged_baseline=unchanged_baseline
            )
        except Exception as exc:  # 验收器自身异常（编码/权限等）也要落成 case error
            logger.exception("验收异常：%s", task.id)
            completed, detail = False, f"验收异常：{type(exc).__name__}: {exc}"
        # 确定性优先：只有确定性检查通过（或本来就没有确定性检查）且 agent 没报错，
        # 才让 judge 做最终判定；确定性失败时绝不调用 judge。
        if (
            completed
            and error is None
            and task.verifier.judge is not None
        ):
            judge = task.verifier.judge
            judge_used = True
            calibration = None
            if judge.calibration is not None:
                calibration_path = (repo_root or Path.cwd()) / judge.calibration
                try:
                    calibration = load_calibration(calibration_path)
                except JudgeError as exc:
                    judge_warning = str(exc)
            labels_sha256 = None
            if judge.samples is not None:
                labels_sha256 = file_sha256(
                    (repo_root or Path.cwd()) / judge.samples
                )
            reliable, warning = judge_reliability(
                judge,
                calibration,
                task_id=task.id,
                instruction=task.instruction,
                model=judge_context.model if judge_context is not None else None,
                labels_sha256=labels_sha256,
            )
            judge_reliable = reliable
            if judge_warning is None:
                judge_warning = warning
            if calibration is not None:
                judge_kappa = calibration.kappa
                judge_samples = calibration.samples
            if judge_context is None:
                judge_error = "任务声明了 judge，但本次运行没有配置 judge 模型"
                completed = False
                detail = f"{detail}；{judge_error}"
            else:
                submission = build_submission(
                    workspace, max_chars=judge.max_submission_chars
                )
                judge_run = await run_judge_submission(
                    judge_context,
                    instruction=task.instruction,
                    judge=judge,
                    submission=submission,
                    deterministic_detail=detail,
                )
                judge_calls = judge_run.calls
                judge_cost = judge_run.cost
                judge_input_tokens = judge_run.input_tokens
                judge_output_tokens = judge_run.output_tokens
                total_calls += judge_run.calls
                total_cost += judge_run.cost
                if judge_run.period is not None:
                    periods[judge_run.period] = periods.get(judge_run.period, 0) + 1
                judge_passed = judge_run.passed
                judge_overall = judge_run.overall
                judge_scores = judge_run.scores
                judge_reasons = judge_run.reasons
                judge_error = judge_run.error
                if judge_run.error is not None:
                    completed = False
                    detail = f"{detail}；judge 失败：{judge_run.error}"
                else:
                    completed = bool(judge_run.passed)
                    outcome = "通过" if completed else "未通过"
                    detail = (
                        f"{detail}；judge overall={judge_run.overall:.2f}"
                        f"（阈值 {judge.pass_threshold:.2f}，{outcome}）"
                    )
                if judge_warning:
                    detail = f"{detail}；⚠ {judge_warning}"
        tampered = tampered_paths(task, workspace, unchanged_baseline)
    else:
        completed, detail = False, "工作区准备失败"
        tampered = []
    if error is not None:
        detail = f"{detail}；运行错误：{error}"
    return TaskExecution(
        completed=completed,
        verifier_detail=detail,
        compactions=execution.compactions,
        model_calls=total_calls,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        probe_input_tokens=execution.probe_input_tokens,
        probe_output_tokens=execution.probe_output_tokens,
        cost=total_cost,
        probe_cost=execution.probe_cost,
        duration_seconds=time.monotonic() - started,
        session_path=session_path,
        workspace=str(workspace),
        periods=tuple(sorted(periods.items())),
        error=error,
        flagged=bool(tampered),
        flag_reason=("保护文件被改动：" + "、".join(tampered)) if tampered else None,
        harness_version=execution.harness_version,
        note=execution.note,
        judge_calls=judge_calls,
        judge_cost=judge_cost,
        judge_input_tokens=judge_input_tokens,
        judge_output_tokens=judge_output_tokens,
        judge_used=judge_used,
        judge_passed=judge_passed,
        judge_overall=judge_overall,
        judge_scores=judge_scores,
        judge_reasons=judge_reasons,
        judge_error=judge_error,
        judge_kappa=judge_kappa,
        judge_samples=judge_samples,
        judge_reliable=judge_reliable,
        judge_warning=judge_warning,
    )


async def execute_task(
    task: Task,
    *,
    workspace: Path,
    session_root: Path,
    repo_root: Path | None,
    snapshot_ref: str | None,
    model: str,
    catalog: Catalog,
    client: StreamingClient,
    executor_factory: Callable[[], Executor],
    context_window: int,
    compaction_policy: CompactionPolicy | None = None,
    compaction_limits: CompactionLimits | None = None,
    guardrail_limits: GuardrailLimits | None = None,
    on_compaction: CompactionObserver | None = None,
    judge_context: JudgeContext | None = None,
) -> TaskExecution:
    """跑一条 codelotte 任务的一次案例（压缩回归与通用测评的兼容入口）。

    `compaction_policy=None` 用生产默认策略；压缩回归传入 forced_policy(k)。
    `on_compaction` 只在需要压缩后探针（票据 13）时传入，通用测评 不传。
    `judge_context` 只在任务声明了 `[verifier.judge]` 时才会被使用。
    """
    harness = CodelotteHarness(
        client=client,
        model=model,
        catalog=catalog,
        executor_factory=executor_factory,
        context_window=context_window,
        compaction_policy=compaction_policy,
        compaction_limits=compaction_limits,
        guardrail_limits=guardrail_limits,
        on_compaction=on_compaction,
    )
    return await execute_harness(
        task,
        harness,
        workspace=workspace,
        session_root=session_root,
        repo_root=repo_root,
        snapshot_ref=snapshot_ref,
        judge_context=judge_context,
    )
