"""对照组与控制 agent（票据 16）。

- `RawHarness`：裸单轮 API，无工具循环——测"模型自己"能拿到什么；
- `OracleHarness`：按任务参考解落文件，应 100% 通过；
- `NoOpHarness`：什么都不做，应 0% 通过；
- `CheatingHarness`：写假成功内容并篡改保护文件，应 0% 通过且被标记。

mini-swe-agent 的适配在 `mini_baseline.py`（需要外部安装，单独隔离依赖）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codelotte import __version__
from codelotte.cost import Catalog, price_call
from codelotte.evals.harness_types import HarnessExecution
from codelotte.evals.tasks import Task
from codelotte.loop import StreamingClient
from codelotte.providers.base import StreamEnd, StreamUsage, TextDelta, UsageEvent

logger = logging.getLogger(__name__)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8"))


def _write_trace(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


@dataclass(frozen=True)
class RawHarness:
    """裸单轮 API：一条 user 消息，不提供 tools，也不回填工具结果。"""

    client: StreamingClient
    model: str
    catalog: Catalog
    name: str = "raw"
    kind: str = "agent"
    isolation: str = "none"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        del workspace  # 裸 API 没有工具，碰不到工作区
        messages = [{"role": "user", "content": task.instruction}]
        text_parts: list[str] = []
        usage: StreamUsage | None = None
        stop_reason: str | None = None
        error: str | None = None
        try:
            async for event in self.client.stream_chat(messages, tools=None):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                elif isinstance(event, UsageEvent):
                    usage = event.usage
                elif isinstance(event, StreamEnd):
                    stop_reason = event.reason
        except Exception as exc:  # 单次对照失败不掀翻整轮
            error = f"{type(exc).__name__}: {exc}"

        at = datetime.now(timezone.utc)
        priced = (
            price_call(self.catalog, self.model, usage, at=at)
            if usage is not None
            else None
        )
        trace_path = session_root / f"{case_name}-raw.jsonl"
        lines = [
            {
                "type": "baseline_request",
                "harness": self.name,
                "model": self.model,
                "tools": None,
                "messages": messages,
            },
            {
                "type": "assistant",
                "content": "".join(text_parts),
                "stop_reason": stop_reason,
            },
        ]
        if usage is not None:
            lines.append(
                {
                    "type": "usage",
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_hit_tokens": usage.cache_hit_tokens,
                    "cache_miss_tokens": usage.cache_miss_tokens,
                    "cost": priced.cost if priced is not None else None,
                    "period": priced.period if priced is not None else None,
                    "at": at.isoformat(),
                }
            )
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            "\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        note = None if usage is not None else "响应没有 usage：token/成本记 0"
        return HarnessExecution(
            model_calls=1,  # 请求已经发出（失败也算一次尝试，成本无法确认时记 0）
            input_tokens=usage.input_tokens if usage is not None else 0,
            output_tokens=usage.output_tokens if usage is not None else 0,
            cost=(priced.cost or 0.0) if priced is not None else 0.0,
            periods=((priced.period, 1),) if priced is not None else (),
            session_path=str(trace_path),
            error=error,
            harness_version=__version__,
            note=note,
        )


@dataclass(frozen=True)
class OracleHarness:
    """总能做对的控制 agent：参考解优先，缺省时从文件验收期望推导。"""

    name: str = "oracle"
    kind: str = "control"
    isolation: str = "none"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        writes: list[str] = []
        for relative, content in task.oracle_files.items():
            _write_text(workspace / relative, content)
            writes.append(relative)
        covered = set(task.oracle_files)
        for expectation in task.verifier.files:
            if expectation.path in covered:
                continue
            if expectation.equals is not None:
                _write_text(workspace / expectation.path, expectation.equals)
                writes.append(expectation.path)
            elif expectation.contains is not None:
                target = workspace / expectation.path
                if target.is_file():
                    try:
                        existing = target.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError) as exc:
                        logger.warning(
                            "oracle 读不动 %s（%s: %s），改为直接写入验收子串",
                            expectation.path,
                            type(exc).__name__,
                            exc,
                        )
                        existing = ""
                    if expectation.contains in existing:
                        continue
                _write_text(target, expectation.contains)
                writes.append(expectation.path)
        trace_path = session_root / f"{case_name}-oracle.json"
        _write_trace(
            trace_path,
            {
                "harness": self.name,
                "kind": self.kind,
                "writes": writes,
                "oracle_files": sorted(task.oracle_files),
            },
        )
        return HarnessExecution(
            session_path=str(trace_path),
            harness_version="builtin",
        )


@dataclass(frozen=True)
class NoOpHarness:
    """什么都不做：用来看"不做任务"会不会被误判为通过。"""

    name: str = "no-op"
    kind: str = "control"
    isolation: str = "none"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        del task, workspace
        trace_path = session_root / f"{case_name}-noop.json"
        _write_trace(
            trace_path,
            {"harness": self.name, "kind": self.kind, "actions": []},
        )
        return HarnessExecution(
            session_path=str(trace_path),
            harness_version="builtin",
        )


@dataclass(frozen=True)
class CheatingHarness:
    """试图作弊的控制 agent：写假成功内容，并篡改所有保护文件。

    验收会失败；`tampered_paths` 会把这些保护文件列出来，报表据此标记"作弊"。
    """

    name: str = "cheating"
    kind: str = "control"
    isolation: str = "none"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        writes: list[str] = []
        tampered: list[str] = []
        for expectation in task.verifier.files:
            if expectation.unchanged:
                target = workspace / expectation.path
                try:
                    previous = target.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    previous = ""
                _write_text(target, previous + "CHEATED\n")
                tampered.append(expectation.path)
            else:
                # 故意不写正确内容：只留下"我成功了"的假标记
                _write_text(workspace / expectation.path, "CHEATED\n")
                writes.append(expectation.path)
        trace_path = session_root / f"{case_name}-cheating.json"
        _write_trace(
            trace_path,
            {
                "harness": self.name,
                "kind": self.kind,
                "writes": writes,
                "tampered": tampered,
            },
        )
        return HarnessExecution(
            session_path=str(trace_path),
            harness_version="builtin",
            note="尝试作弊：篡改保护文件",
        )
