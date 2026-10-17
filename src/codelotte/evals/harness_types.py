"""Harness 缝的公共类型（票据 16）。

一个 harness 是"被测 agent"的统一接口：codelotte 自己、mini-swe-agent、裸单轮 API
和三种控制 agent 都实现同一份 `run(task, …) -> HarnessExecution`。外层
`execute_harness` 负责所有 harness 共用的工作区准备、验收与防篡改检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from codelotte.evals.tasks import Task


@dataclass(frozen=True)
class HarnessExecution:
    """一次 harness 运行的原始结果（验收由外层统一做）。

    `compactions` / `probe_*` 只有压缩回归的 codelotte harness 会填；控制 agent
    与对照组保持 0。`session_path` 是 codelotte 的 JSONL 会话，或对照组/控制组的
    轨迹文件——报表统一叫"轨迹"。
    """

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    periods: tuple[tuple[str, int], ...] = ()
    session_path: str | None = None
    error: str | None = None
    compactions: int = 0
    probe_input_tokens: int = 0
    probe_output_tokens: int = 0
    probe_cost: float = 0.0
    harness_version: str | None = None
    note: str | None = None


class Harness(Protocol):
    """被测 agent / 控制 agent 的统一接口。"""

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str:
        """`agent`（真实 harness）或 `control`（评测器自检）。"""
        ...

    @property
    def isolation(self) -> str:
        """`docker` / `local` / `none`。"""
        ...

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        """在已准备好的工作区里跑一次；不负责验收，也不负责清理工作区。"""
        ...
