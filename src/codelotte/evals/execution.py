"""单任务执行核心（票据 15 从压缩回归运行器抽出）：真实 loop + 工具 + 验收。

压缩回归（票据 13）与通用测评（票据 15）只在"压缩策略"和"压缩后是否探针"
上不同；其余（工作区准备、预算、错误记录、成本/时段累计、验收）共用这里。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from codelotte.compaction import CompactionLimits, CompactionPolicy
from codelotte.cost import Catalog
from codelotte.evals.tasks import Task
from codelotte.evals.workspace import (
    capture_unchanged_baseline,
    prepare_workspace,
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
    """一次任务执行的原始结果；压缩/通用报表各自从中取字段。"""

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
) -> TaskExecution:
    """跑一条任务的一次案例。

    `compaction_policy=None` 用生产默认策略；压缩回归传入 forced_policy(k)。
    `on_compaction` 只在需要压缩后探针（票据 13）时传入，通用测评 不传。
    """
    started = time.monotonic()
    # 必须在 chdir 之前把路径钉成绝对路径：否则相对 --out 会在工作区里长出
    # sessions/（既污染被测环境，又让报表里的顶层 sessions/ 为空）。
    workspace = workspace.resolve()
    session_root = session_root.resolve()
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
    prepared = False
    unchanged_baseline: dict[str, str | None] | None = None
    old_cwd = Path.cwd()
    executor: Executor | None = None
    try:
        prepare_workspace(
            task,
            workspace,
            repo_root=repo_root,
            snapshot_ref=snapshot_ref,
        )
        prepared = True
        unchanged_baseline = capture_unchanged_baseline(task, workspace)
        os.chdir(workspace)
        store = SessionStore.start(workspace, base_dir=session_root)
        session_path = str(store.path)
        executor = executor_factory()
        loop = AgentLoop(
            client=client,
            tools=default_tools(executor),
            store=store,
            model=model,
            catalog=catalog,
            permissions=allow_builtin_tools(),
            env=executor.env,
            context_window=context_window,
            compaction_limits=compaction_limits,
            guardrail_limits=guardrail_limits,
            compaction_policy=compaction_policy,
        )
        async with asyncio.timeout(task.timeout_seconds):
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
                    if on_compaction is not None:
                        probe = await on_compaction(loop, compactions)
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
        os.chdir(old_cwd)

    if prepared:
        try:
            completed, detail = verify(
                task, workspace, unchanged_baseline=unchanged_baseline
            )
        except Exception as exc:  # 验收器自身异常（编码/权限等）也要落成 case error
            logger.exception("验收异常：%s", task.id)
            completed, detail = False, f"验收异常：{type(exc).__name__}: {exc}"
    else:
        completed, detail = False, "工作区准备失败"
    if error is not None:
        detail = f"{detail}；运行错误：{error}"
    return TaskExecution(
        completed=completed,
        verifier_detail=detail,
        compactions=compactions,
        model_calls=model_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        probe_input_tokens=probe_input_tokens,
        probe_output_tokens=probe_output_tokens,
        cost=cost,
        probe_cost=probe_cost,
        duration_seconds=time.monotonic() - started,
        session_path=session_path,
        workspace=str(workspace),
        periods=tuple(sorted(periods.items())),
        error=error,
    )
