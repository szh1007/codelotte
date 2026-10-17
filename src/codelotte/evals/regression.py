"""强制压缩的回归运行器（票据 13 v0，执行核心见 execution.py）。

一条任务 = 一个临时工作区 + 一次真实 `AgentLoop.run`。回归套件不改变生产触发逻辑，
而是通过 `CompactionPolicy` 注入"每次请求前都压、直到 k 次"的策略：k 次压缩发生在
k 个不同的 turn 之后，压缩链与真实任务边界无关，变量只剩"压了几次"。

checkpoint 是带外探针：压缩事件发生后，用**压缩后的上下文** + 问题集再请求一次模型，
答案只用于评分，不写回会话（不污染被测轨迹）。评分是确定性的事实比对（见 checkpoints.py）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codelotte.compaction import (
    CompactionDecision,
    CompactionLimits,
    CompactionPolicy,
    default_compaction_policy,
)
from codelotte.cost import Catalog, price_call
from codelotte.evals.checkpoints import CheckpointScore, score_answer
from codelotte.evals.execution import ProbeUsage, execute_task
from codelotte.evals.tasks import Checkpoint, Task
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import AgentLoop, StreamingClient
from codelotte.providers.base import StreamUsage, TextDelta, UsageEvent
from codelotte.sandbox import Executor

_CHECKPOINT_HEADER = (
    "现在暂停任务。只根据你当前掌握的上下文回答下面 {count} 个问题，"
    "不要调用工具，也不要继续执行任务。"
)
_CHECKPOINT_FOOTER = "请用 1. / 2. / 3. 这样的编号逐条回答，每条尽量简短。"

logger = logging.getLogger(__name__)


def forced_policy(times: int) -> CompactionPolicy:
    """强制压缩策略：只要已落盘的 compaction 少于 times，就按硬触发压一次。

    利用率钉在 100% 只是为了复用 `plan_compaction` 的边界选择（最小保留集）；
    报告里 mode=hard 是事实，不代表真实上下文真的到了硬阈值。
    没有新的 turn 可压时 `plan_compaction` 返回 None——所以 k 次压缩需要至少 k 个 turn。
    """

    def policy(
        entries: list[dict[str, Any]],
        *,
        input_tokens: int,
        context_window: int,
        limits: CompactionLimits,
    ) -> CompactionDecision | None:
        done = sum(1 for entry in entries if entry.get("type") == "compaction")
        if done >= times:
            return None
        return default_compaction_policy(
            entries,
            input_tokens=context_window,
            context_window=context_window,
            limits=limits,
        )

    return policy


def checkpoint_prompt(checkpoints: tuple[Checkpoint, ...]) -> str:
    """把任务的问题集拼成一次探针请求（顺序与评分编号一一对应）。"""
    lines = [_CHECKPOINT_HEADER.format(count=len(checkpoints))]
    lines.extend(
        f"{index}. {checkpoint.question}"
        for index, checkpoint in enumerate(checkpoints, start=1)
    )
    lines.append(_CHECKPOINT_FOOTER)
    return "\n".join(lines)


async def _ask(
    client: StreamingClient, messages: list[dict[str, Any]]
) -> tuple[str, StreamUsage | None]:
    """一次无工具探针请求：只收集文本与 usage（探针不进会话）。"""
    parts: list[str] = []
    usage: StreamUsage | None = None
    async for event in client.stream_chat(messages, tools=None):
        if isinstance(event, TextDelta):
            parts.append(event.text)
        elif isinstance(event, UsageEvent):
            usage = event.usage
    return "".join(parts), usage


@dataclass(frozen=True)
class CheckpointObservation:
    """一次压缩后的 checkpoint 探针结果（compaction 从 1 开始编号）。"""

    compaction: int
    answer: str
    structured: bool
    scores: tuple[CheckpointScore, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    error: str | None = None

    @property
    def passed(self) -> int:
        return sum(1 for score in self.scores if score.passed)

    @property
    def total(self) -> int:
        return len(self.scores)


@dataclass(frozen=True)
class CaseResult:
    """一条任务在某个 k 下的一次运行结果（也是压缩报表的一行）。"""

    task_id: str
    bucket: str
    k: int
    repetition: int
    completed: bool
    verifier_detail: str
    compactions: int
    checkpoints: tuple[CheckpointObservation, ...]
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
    error: str | None = None
    periods: tuple[tuple[str, int], ...] = ()

    @property
    def valid(self) -> bool:
        """有效 = 没崩且确实压到了请求的次数（否则该点不能用来画衰减曲线）。"""
        return self.error is None and self.compactions == self.k

    @property
    def retention_passed(self) -> int:
        return sum(observation.passed for observation in self.checkpoints)

    @property
    def retention_total(self) -> int:
        return sum(observation.total for observation in self.checkpoints)


def _parse_usage(usage: StreamUsage | None) -> tuple[int, int]:
    if usage is None:
        return 0, 0
    return usage.input_tokens, usage.output_tokens


def _price_probe(catalog: Catalog, model: str, usage: StreamUsage | None) -> float:
    if usage is None:
        return 0.0
    priced = price_call(catalog, model, usage, at=datetime.now(timezone.utc))
    return priced.cost or 0.0


async def run_case(
    task: Task,
    *,
    k: int,
    repetition: int,
    workspace: Path,
    session_root: Path,
    model: str,
    catalog: Catalog,
    client: StreamingClient,
    probe_client: StreamingClient,
    executor_factory: Callable[[], Executor],
    context_window: int,
    compaction_limits: CompactionLimits | None = None,
    guardrail_limits: GuardrailLimits | None = None,
    repo_root: Path | None = None,
    snapshot_ref: str | None = None,
) -> CaseResult:
    """跑一条任务的一次案例：真实 loop + 强制压缩 + 压缩后 checkpoint + 确定性验收。"""
    observations: list[CheckpointObservation] = []

    async def observe(loop: AgentLoop, compaction: int) -> ProbeUsage:
        observation = await _observe_checkpoints(
            task,
            loop,
            probe_client,
            catalog,
            model,
            compaction,
        )
        observations.append(observation)
        return ProbeUsage(
            input_tokens=observation.input_tokens,
            output_tokens=observation.output_tokens,
            cost=observation.cost,
        )

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
        compaction_policy=forced_policy(k),
        compaction_limits=compaction_limits,
        guardrail_limits=guardrail_limits,
        on_compaction=observe,
    )
    return CaseResult(
        task_id=task.id,
        bucket=task.bucket,
        k=k,
        repetition=repetition,
        completed=execution.completed,
        verifier_detail=execution.verifier_detail,
        compactions=execution.compactions,
        checkpoints=tuple(observations),
        model_calls=execution.model_calls,
        input_tokens=execution.input_tokens,
        output_tokens=execution.output_tokens,
        probe_input_tokens=execution.probe_input_tokens,
        probe_output_tokens=execution.probe_output_tokens,
        cost=execution.cost,
        probe_cost=execution.probe_cost,
        duration_seconds=execution.duration_seconds,
        session_path=execution.session_path,
        workspace=execution.workspace,
        error=execution.error,
        periods=execution.periods,
    )


async def _observe_checkpoints(
    task: Task,
    loop: AgentLoop,
    probe_client: StreamingClient,
    catalog: Catalog,
    model: str,
    compaction: int,
) -> CheckpointObservation:
    """压缩后立即探针；探针失败只记错误，不中断被测任务。"""
    messages = [
        *loop.messages,
        {"role": "user", "content": checkpoint_prompt(task.checkpoints)},
    ]
    try:
        answer, usage = await _ask(probe_client, messages)
    except Exception as exc:  # 探针失败只影响这一条观察，不中断被测任务
        logger.warning(
            "checkpoint 探针失败：%s compaction=%s",
            task.id,
            compaction,
            exc_info=True,
        )
        return CheckpointObservation(
            compaction=compaction,
            answer="",
            structured=False,
            scores=(),
            error=f"{type(exc).__name__}: {exc}",
        )
    scored = score_answer(answer, task.checkpoints)
    input_tokens, output_tokens = _parse_usage(usage)
    return CheckpointObservation(
        compaction=compaction,
        answer=answer,
        structured=scored.structured,
        scores=scored.scores,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=_price_probe(catalog, model, usage),
    )
