"""通用测评（票据 15）与多 harness 执行（票据 16）。

- `eval compaction` 强制压缩 k 次，测 checkpoint 保留率；
- `eval run` 按生产默认策略跑任务，重复 N 次，回答"这个 harness 现在能不能过"；
- `eval compare` / `eval controls` 用同一个 `run_harness_suite` 跑不同 harness
  （codelotte / raw / mini-swe-agent / 控制 agent）。

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
from codelotte.evals.execution import CodelotteHarness, execute_harness
from codelotte.evals.harness_types import Harness
from codelotte.evals.meta import (
    EvalRunMeta,
    now_iso,
    prepare_run,
    prepare_run_dir,
)
from codelotte.evals.report_utils import periods_text
from codelotte.evals.results import EvalCaseResult
from codelotte.evals.tasks import Task
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import StreamingClient
from codelotte.sandbox import Executor

ClientFactory = Callable[[], StreamingClient]
ExecutorFactory = Callable[[], Executor]
HarnessFactory = Callable[[], Harness]


async def run_harness_case(
    task: Task,
    harness: Harness,
    *,
    repetition: int,
    workspace: Path,
    session_root: Path,
    repo_root: Path,
    snapshot_ref: str | None,
) -> EvalCaseResult:
    """跑一条任务的一次重复；验收通过且没有运行错误才算 pass。"""
    execution = await execute_harness(
        task,
        harness,
        workspace=workspace,
        session_root=session_root,
        repo_root=repo_root,
        snapshot_ref=snapshot_ref,
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
        harness=harness.name,
        flagged=execution.flagged,
        flag_reason=execution.flag_reason,
        harness_version=execution.harness_version,
        note=execution.note,
    )


async def run_harness_suite(
    tasks: Sequence[Task],
    *,
    harness_factory: HarnessFactory,
    repetitions: int,
    run_id: str,
    repo_root: Path,
    seed: int,
    command: str,
    runs_root: Path | None = None,
    run_dir: Path | None = None,
    exclude: Path | None = None,
    currency: str = "CNY",
    model: str | None = None,
    reasoning_effort: str = "",
    context_window: int = 0,
    progress: Callable[[str], None] | None = None,
) -> tuple[EvalRunMeta, list[EvalCaseResult]]:
    """跑完整一轮某个 harness 的测评并落报表。

    `run_dir` 给出时用它（对照跑数的组子目录）；否则在 `runs_root` 下新建
    `<run_id>`。`exclude` 是工作树指纹要排除的目录，对照跑数传父 run 目录。
    """
    if repetitions < 1:
        raise ValueError(f"repetitions 要 ≥1（给了 {repetitions}）")
    if run_dir is None and runs_root is None:
        raise ValueError("run_harness_suite 需要 runs_root 或 run_dir")
    random.seed(seed)
    started_at = now_iso()
    profile = harness_factory()
    if run_dir is not None:
        context = prepare_run_dir(
            tasks, run_dir=run_dir, repo_root=repo_root, exclude=exclude
        )
    else:
        assert runs_root is not None
        context = prepare_run(
            tasks, runs_root=runs_root, repo_root=repo_root, run_id=run_id
        )
    cases: list[EvalCaseResult] = []
    total = len(tasks) * repetitions
    done = 0
    for task in tasks:
        for repetition in range(1, repetitions + 1):
            done += 1
            case_name = f"{task.id}-r{repetition}"
            if progress is not None:
                progress(f"[{done}/{total}] {case_name} …")
            result = await run_harness_case(
                task,
                harness_factory(),
                repetition=repetition,
                workspace=context.workspace_root / case_name,
                session_root=context.session_root,
                repo_root=context.repo_root,
                snapshot_ref=context.snapshot_refs.get(task.id),
            )
            cases.append(result)
            if progress is not None:
                progress(_progress_line(result))
    harness_version = next(
        (case.harness_version for case in cases if case.harness_version), None
    )
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
        model=model or profile.name,
        reasoning_effort=reasoning_effort,
        context_window=context_window,
        repetitions=repetitions,
        seed=seed,
        tasks=context.task_metas,
        command=command,
        currency=currency,
        harness=profile.name,
        harness_kind=profile.kind,
        harness_version=harness_version,
        isolation=profile.isolation,
    )
    write_eval_report(context.run_dir, meta, cases)
    return meta, cases


def _progress_line(result: EvalCaseResult) -> str:
    status = "pass" if result.passed else "fail"
    flag = " flag" if result.flagged else ""
    return (
        f"    → {status}{flag} calls={result.model_calls} "
        f"cost=¥{result.cost:.6f} {result.duration_seconds:.1f}s "
        f"periods={periods_text(result.periods)}"
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
    isolation: str = "unknown",
) -> tuple[EvalRunMeta, list[EvalCaseResult]]:
    """跑完整一轮 codelotte 通用测评并落报表；返回元数据与全部案例。"""

    def factory() -> CodelotteHarness:
        return CodelotteHarness(
            client=client_factory(),
            model=model,
            catalog=catalog,
            executor_factory=executor_factory,
            context_window=context_window,
            compaction_limits=compaction_limits,
            guardrail_limits=guardrail_limits,
            isolation=isolation,
        )

    return await run_harness_suite(
        tasks,
        harness_factory=factory,
        repetitions=repetitions,
        run_id=run_id,
        runs_root=runs_root,
        repo_root=repo_root,
        seed=seed,
        command=command,
        currency=catalog.currency,
        model=model,
        reasoning_effort=reasoning_effort,
        context_window=context_window,
        progress=progress,
    )
