"""强制压缩的回归运行器（票据 13 v0）。

一条任务 = 一个临时工作区 + 一次真实 `AgentLoop.run`。回归套件不改变生产触发逻辑，
而是通过 `CompactionPolicy` 注入"每次请求前都压、直到 k 次"的策略：k 次压缩发生在
k 个不同的 turn 之后，压缩链与真实任务边界无关，变量只剩"压了几次"。

checkpoint 是带外探针：压缩事件发生后，用**压缩后的上下文** + 问题集再请求一次模型，
答案只用于评分，不写回会话（不污染被测轨迹）。评分是确定性的事实比对（见 checkpoints.py）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
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
from codelotte.evals.tasks import Checkpoint, FileExpectation, Task
from codelotte.guardrails import GuardrailLimits
from codelotte.loop import AgentLoop, CompactionEvent, CostRecorded, StreamingClient
from codelotte.permissions import allow_builtin_tools
from codelotte.providers.base import StreamUsage, TextDelta, UsageEvent
from codelotte.sandbox import Executor
from codelotte.session.store import SessionStore
from codelotte.tools import default_tools

_CHECKPOINT_HEADER = (
    "现在暂停任务。只根据你当前掌握的上下文回答下面 {count} 个问题，"
    "不要调用工具，也不要继续执行任务。"
)
_CHECKPOINT_FOOTER = "请用 1. / 2. / 3. 这样的编号逐条回答，每条尽量简短。"

logger = logging.getLogger(__name__)


class ModelCallBudgetExceeded(RuntimeError):
    """任务超过 max_model_calls（防回归实验意外烧钱/死循环）。"""


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


def prepare_workspace(task: Task, workspace: Path) -> Path:
    """按任务定义写出初始文件（强制 LF：实验文件跨平台逐字节一致）。"""
    workspace.mkdir(parents=True, exist_ok=True)
    for relative, content in task.setup.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return workspace


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def _verify_files(
    expectations: tuple[FileExpectation, ...], task: Task, workspace: Path
) -> list[str]:
    problems: list[str] = []
    for expectation in expectations:
        target = workspace / expectation.path
        if not target.is_file():
            problems.append(f"缺少文件 {expectation.path}")
            continue
        actual = _normalize_text(target.read_text(encoding="utf-8"))
        if expectation.equals is not None:
            expected = _normalize_text(expectation.equals)
            if actual != expected:
                problems.append(
                    f"{expectation.path} 内容不符：期望 {expected!r}，实际 {actual!r}"
                )
        elif expectation.contains is not None:
            if _normalize_text(expectation.contains) not in actual:
                problems.append(
                    f"{expectation.path} 不包含 {_normalize_text(expectation.contains)!r}"
                )
        elif expectation.unchanged:
            expected = _normalize_text(task.setup.get(expectation.path, ""))
            if actual != expected:
                problems.append(f"{expectation.path} 被修改了（任务要求保持不变）")
    return problems


def _verify_python(code: str, workspace: Path, timeout: float = 60.0) -> str | None:
    env = {**os.environ, "PYTHONUTF8": "1"}
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"python 验收无法执行：{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        tail = output[-600:] if len(output) > 600 else output
        return f"python 验收失败（退出码 {result.returncode}）：{tail}"
    return None


def verify(task: Task, workspace: Path) -> tuple[bool, str]:
    """确定性验收：文件期望 + 可选 Python 检查，全部通过才算完成。"""
    problems = _verify_files(task.verifier.files, task, workspace)
    if task.verifier.python is not None:
        python_problem = _verify_python(task.verifier.python, workspace)
        if python_problem is not None:
            problems.append(python_problem)
    if problems:
        return False, "；".join(problems)
    return True, "验收通过"


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
    """一条任务在某个 k 下的一次运行结果（也是报表的一行）。"""

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
) -> CaseResult:
    """跑一条任务的一次案例：真实 loop + 强制压缩 + 压缩后 checkpoint + 确定性验收。"""
    started = time.monotonic()
    # 必须在 chdir 之前把路径钉成绝对路径：否则相对 --out 会在工作区里长出
    # sessions/（既污染被测环境，又让报表里的顶层 sessions/ 为空）。
    workspace = prepare_workspace(task, workspace.resolve())
    session_root = session_root.resolve()
    checkpoint_results: list[CheckpointObservation] = []
    compactions = 0
    model_calls = 0
    input_tokens = 0
    output_tokens = 0
    probe_input_tokens = 0
    probe_output_tokens = 0
    cost = 0.0
    probe_cost = 0.0
    session_path: str | None = None
    error: str | None = None
    old_cwd = Path.cwd()
    executor = executor_factory()
    try:
        os.chdir(workspace)
        store = SessionStore.start(workspace, base_dir=session_root)
        session_path = str(store.path)
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
            compaction_policy=forced_policy(k),
        )
        async with asyncio.timeout(task.timeout_seconds):
            async for event in loop.run(task.instruction):
                if isinstance(event, CostRecorded):
                    model_calls += 1
                    input_tokens += event.record.input_tokens
                    output_tokens += event.record.output_tokens
                    cost += event.record.cost or 0.0
                    # 软上限：usage 在调用完成后才到，最多越过一格才中止（防跑飞，不做精确配额）
                    if model_calls > task.max_model_calls:
                        raise ModelCallBudgetExceeded(
                            f"超过 max_model_calls={task.max_model_calls}"
                        )
                elif isinstance(event, CompactionEvent):
                    compactions += 1
                    observation = await _observe_checkpoints(
                        task,
                        loop,
                        probe_client,
                        catalog,
                        model,
                        compactions,
                    )
                    checkpoint_results.append(observation)
                    probe_input_tokens += observation.input_tokens
                    probe_output_tokens += observation.output_tokens
                    probe_cost += observation.cost
    except Exception as exc:  # 单条案例失败不能掀翻整轮实验；原因写进报表并进日志
        logger.exception("案例失败：%s k=%s rep=%s", task.id, k, repetition)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        await executor.close()
        os.chdir(old_cwd)

    completed, detail = verify(task, workspace)
    if error is not None:
        detail = f"{detail}；运行错误：{error}"
    return CaseResult(
        task_id=task.id,
        bucket=task.bucket,
        k=k,
        repetition=repetition,
        completed=completed,
        verifier_detail=detail,
        compactions=compactions,
        checkpoints=tuple(checkpoint_results),
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
        error=error,
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
