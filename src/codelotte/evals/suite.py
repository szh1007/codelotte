"""实验编排与可复现元数据（票据 13）。

一轮跑数 = 任务 × k 集合 × 重复次数。开始前锁定 git ref、依赖版本、模型参数与
任务指纹；结束后把每条案例的轨迹、checkpoint、验收结果写进同一个 run 目录。
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from codelotte import __version__
from codelotte.compaction import CompactionLimits, SummaryTemplate
from codelotte.cost import Catalog
from codelotte.evals.meta import (
    RunMeta,
    TaskMeta,
    create_run_dir,
    make_run_id,
    now_iso,
    prepare_run,
    task_fingerprint,
)
from codelotte.evals.regression import CaseResult, CompactionStrategy, run_case
from codelotte.evals.report import write_report
from codelotte.evals.tasks import Task
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import StreamingClient
from codelotte.sandbox import Executor

__all__ = [
    "RunMeta",
    "TaskMeta",
    "create_run_dir",
    "make_run_id",
    "run_suite",
    "task_fingerprint",
]

ClientFactory = Callable[[], StreamingClient]
ExecutorFactory = Callable[[], Executor]


async def run_suite(
    tasks: Sequence[Task],
    *,
    k_values: Sequence[int],
    repetitions: int,
    combos: Sequence[tuple[str, str]] = (("minimal", "seven"),),
    run_id: str,
    runs_root: Path,
    repo_root: Path,
    model: str,
    reasoning_effort: str,
    catalog: Catalog,
    context_window: int,
    client_factory: ClientFactory,
    probe_client_factory: ClientFactory,
    executor_factory: ExecutorFactory,
    compaction_limits: CompactionLimits | None,
    guardrail_limits: GuardrailLimits | None,
    seed: int,
    command: str,
    progress: Callable[[str], None] | None = None,
) -> tuple[RunMeta, list[CaseResult]]:
    """跑完整一轮并落报表；返回元数据与全部案例（进度回调不参与数据）。

    随机种子在这里统一设置（provider 重试抖动会用到随机数）；任务顺序固定为
    任务文件顺序 × k 升序 × 重复序号，保证同一份输入得到同一批请求序列。
    """
    random.seed(seed)
    started_at = now_iso()
    if not combos:
        raise ValueError("压缩回归至少需要一个 strategy:template 组合")
    context = prepare_run(tasks, runs_root=runs_root, repo_root=repo_root, run_id=run_id)
    cases: list[CaseResult] = []
    total = len(combos) * len(tasks) * len(k_values) * repetitions
    done = 0
    multi = len(combos) > 1
    for strategy, template in combos:
        if strategy not in ("minimal", "wide"):
            raise ValueError(f"未知压缩策略：{strategy!r}")
        if template not in ("seven", "compact"):
            raise ValueError(f"未知摘要模板：{template!r}")
        strategy_value = cast(CompactionStrategy, strategy)
        template_value = cast(SummaryTemplate, template)
        for task in tasks:
            for k in sorted(k_values):
                for repetition in range(1, repetitions + 1):
                    done += 1
                    suffix = f"-{strategy}-{template}" if multi else ""
                    case_name = f"{task.id}-k{k}-r{repetition}{suffix}"
                    if progress is not None:
                        progress(
                            f"[{done}/{total}] {task.id} k={k} "
                            f"{strategy}/{template} r{repetition} …"
                        )
                    result = await run_case(
                        task,
                        k=k,
                        repetition=repetition,
                        workspace=context.workspace_root / case_name,
                        session_root=context.session_root,
                        model=model,
                        catalog=catalog,
                        client=client_factory(),
                        probe_client=probe_client_factory(),
                        executor_factory=executor_factory,
                        context_window=context_window,
                        compaction_limits=compaction_limits,
                        guardrail_limits=guardrail_limits,
                        repo_root=context.repo_root,
                        snapshot_ref=context.snapshot_refs.get(task.id),
                        strategy=strategy_value,
                        template=template_value,
                    )
                    cases.append(result)
                    if progress is not None:
                        progress(_progress_line(result))
    meta = RunMeta(
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
        soft=(compaction_limits or CompactionLimits()).soft,
        hard=(compaction_limits or CompactionLimits()).hard,
        k_values=tuple(sorted(k_values)),
        repetitions=repetitions,
        seed=seed,
        tasks=context.task_metas,
        command=command,
        currency=catalog.currency,
        combos=tuple(combos),
    )
    write_report(context.run_dir, meta, cases)
    return meta, cases


def _progress_line(result: CaseResult) -> str:
    retention = (
        f"{result.retention_passed}/{result.retention_total}"
        if result.retention_total
        else "n/a"
    )
    status = "ok" if result.valid else "invalid"
    return (
        f"    → {status} compactions={result.compactions}/{result.k} "
        f"completed={'yes' if result.completed else 'no'} "
        f"retention={retention} calls={result.model_calls} "
        f"cost=¥{result.cost + result.probe_cost:.6f} "
        f"{result.duration_seconds:.1f}s"
    )
