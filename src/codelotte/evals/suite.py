"""实验编排与可复现元数据（票据 13）。

一轮跑数 = 3 条任务 × k 集合 × 重复次数。开始前锁定 git ref、依赖版本、模型参数与
任务指纹；结束后把每条案例的轨迹、checkpoint、验收结果写进同一个 run 目录。
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from codelotte import __version__
from codelotte.compaction import CompactionLimits
from codelotte.cost import Catalog
from codelotte.evals.meta import (
    RunMeta,
    TaskMeta,
    create_run_dir,
    current_git_ref,
    make_run_id,
    now_iso,
    task_fingerprint,
    uv_lock_sha,
    worktree_fingerprint,
)
from codelotte.evals.regression import CaseResult, run_case
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
    # 所有落盘路径先钉成绝对路径：run_case 会 chdir 进工作区
    runs_root = runs_root.resolve()
    repo_root = repo_root.resolve()
    run_dir = create_run_dir(runs_root, run_id)
    workspace_root = run_dir / "workspaces"
    session_root = run_dir / "sessions"
    workspace_root.mkdir()
    session_root.mkdir()
    # 复现凭证在开跑前锁定（跑数期间工作区/会话目录会增长，不能事后取）
    git_ref = current_git_ref(repo_root)
    dirty, diff_sha = worktree_fingerprint(repo_root, exclude=run_dir)
    lock_sha = uv_lock_sha(repo_root)
    task_metas = tuple(
        TaskMeta(id=task.id, bucket=task.bucket, sha256=task_fingerprint(task))
        for task in tasks
    )
    cases: list[CaseResult] = []
    total = len(tasks) * len(k_values) * repetitions
    done = 0
    for task in tasks:
        for k in sorted(k_values):
            for repetition in range(1, repetitions + 1):
                done += 1
                case_name = f"{task.id}-k{k}-r{repetition}"
                if progress is not None:
                    progress(f"[{done}/{total}] {case_name} …")
                result = await run_case(
                    task,
                    k=k,
                    repetition=repetition,
                    workspace=workspace_root / case_name,
                    session_root=session_root,
                    model=model,
                    catalog=catalog,
                    client=client_factory(),
                    probe_client=probe_client_factory(),
                    executor_factory=executor_factory,
                    context_window=context_window,
                    compaction_limits=compaction_limits,
                    guardrail_limits=guardrail_limits,
                )
                cases.append(result)
                if progress is not None:
                    progress(_progress_line(result))
    meta = RunMeta(
        run_id=run_dir.name,
        started_at=started_at,
        finished_at=now_iso(),
        git_ref=git_ref,
        git_dirty=dirty,
        git_diff_sha=diff_sha,
        python=sys.version.split()[0],
        codelotte_version=__version__,
        uv_lock_sha=lock_sha,
        model=model,
        reasoning_effort=reasoning_effort,
        context_window=context_window,
        soft=(compaction_limits or CompactionLimits()).soft,
        hard=(compaction_limits or CompactionLimits()).hard,
        k_values=tuple(sorted(k_values)),
        repetitions=repetitions,
        seed=seed,
        tasks=task_metas,
        command=command,
        currency=catalog.currency,
    )
    write_report(run_dir, meta, cases)
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
