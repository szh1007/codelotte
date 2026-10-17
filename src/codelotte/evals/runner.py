"""通用测评（票据 15）：任务 × 重复次数，pass^k、成本、耗时与完整轨迹。

与票据 13 的压缩回归分开：
- `eval compaction` 强制压缩 k 次，测 checkpoint 保留率；
- `eval run` 按生产默认策略跑任务，重复 N 次，回答"这个 harness 现在能不能过"。

pass^k 口径：一条任务的全部 k 次重复都通过才算 pass^k；任何一次失败或运行错误
都记 0。运行错误不掀翻整轮，原因写进案例与报表。
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from codelotte import __version__
from codelotte.compaction import CompactionLimits
from codelotte.cost import Catalog
from codelotte.evals.eval_report import write_eval_report
from codelotte.evals.execution import execute_task
from codelotte.evals.meta import EvalRunMeta, now_iso, prepare_run
from codelotte.evals.report_utils import periods_text
from codelotte.evals.results import EvalCaseResult
from codelotte.evals.tasks import Task
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import StreamingClient
from codelotte.sandbox import Executor

ClientFactory = Callable[[], StreamingClient]
ExecutorFactory = Callable[[], Executor]


async def run_eval_case(
    task: Task,
    *,
    repetition: int,
    workspace: Path,
    session_root: Path,
    repo_root: Path,
    snapshot_ref: str | None,
    model: str,
    catalog: Catalog,
    client: StreamingClient,
    executor_factory: ExecutorFactory,
    context_window: int,
    compaction_limits: CompactionLimits | None,
    guardrail_limits: GuardrailLimits | None,
) -> EvalCaseResult:
    """跑一条任务的一次重复；验收通过且没有运行错误才算 pass。"""
    execution = await execute_task(
        task,
        workspace=workspace,
        session_root=session_root,
        repo_root=repo_root,
        snapshot_ref=snapshot_ref,
        model=model,
        catalog=catalog,
        client=client,
        executor_factory=executor_factory,
        context_window=context_window,
        compaction_policy=None,  # 生产默认策略；通用测评 不强制压缩
        compaction_limits=compaction_limits,
        guardrail_limits=guardrail_limits,
        on_compaction=None,
    )
    return EvalCaseResult(
        task_id=task.id,
        bucket=task.bucket,
        repetition=repetition,
        passed=execution.completed and execution.error is None,
        verifier_detail=execution.verifier_detail,
        model_calls=execution.model_calls,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        cost=execution.cost,
        duration_seconds=execution.duration_seconds,
        periods=execution.periods,
        session_path=execution.session_path,
        workspace=execution.workspace,
        error=execution.error,
    )


async def run_eval_suite(
    tasks: Sequence[Task],
    *,
    repetitions: int,
    run_id: str,
    runs_root: Path,
    repo_root: Path,
    model: str,
    reasoning_effort: str,
    catalog: Catalog,
    context_window: int,
    client_factory: ClientFactory,
    executor_factory: ExecutorFactory,
    compaction_limits: CompactionLimits | None,
    guardrail_limits: GuardrailLimits | None,
    seed: int,
    command: str,
    progress: Callable[[str], None] | None = None,
) -> tuple[EvalRunMeta, list[EvalCaseResult]]:
    """跑完整一轮通用测评并落报表；返回元数据与全部案例。"""
    random.seed(seed)
    started_at = now_iso()
    context = prepare_run(tasks, runs_root=runs_root, repo_root=repo_root, run_id=run_id)
    cases: list[EvalCaseResult] = []
    total = len(tasks) * repetitions
    done = 0
    for task in tasks:
        for repetition in range(1, repetitions + 1):
            done += 1
            case_name = f"{task.id}-r{repetition}"
            if progress is not None:
                progress(f"[{done}/{total}] {case_name} …")
            result = await run_eval_case(
                task,
                repetition=repetition,
                workspace=context.workspace_root / case_name,
                session_root=context.session_root,
                repo_root=context.repo_root,
                snapshot_ref=context.snapshot_refs.get(task.id),
                model=model,
                catalog=catalog,
                client=client_factory(),
                executor_factory=executor_factory,
                context_window=context_window,
                compaction_limits=compaction_limits,
                guardrail_limits=guardrail_limits,
            )
            cases.append(result)
            if progress is not None:
                progress(_progress_line(result))
    meta = EvalRunMeta(
        run_id=context.run_dir.name,
        started_at=started_at,
        finished_at=now_iso(),
        git_ref=context.git_ref,
        git_dirty=context.git_dirty,
        git_diff_sha=context.git_diff_sha,
        python=sys.version.split()[0],
        codelotte_version=__version__,
        uv_lock_sha=context.uv_lock_sha,
        model=model,
        reasoning_effort=reasoning_effort,
        context_window=context_window,
        repetitions=repetitions,
        seed=seed,
        tasks=context.task_metas,
        command=command,
        currency=catalog.currency,
    )
    write_eval_report(context.run_dir, meta, cases)
    return meta, cases


def _progress_line(result: EvalCaseResult) -> str:
    status = "pass" if result.passed else "fail"
    return (
        f"    → {status} calls={result.model_calls} "
        f"cost=¥{result.cost:.6f} {result.duration_seconds:.1f}s "
        f"periods={periods_text(result.periods)}"
    )
