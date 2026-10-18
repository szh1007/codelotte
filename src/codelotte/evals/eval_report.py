"""通用测评报表（票据 15）：pass^k、每任务成本/耗时、计费时段与失败定位。

与压缩回归报表分开：这里不按 k（压缩次数）分组，而按"任务 × 重复次数"聚合。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from codelotte.cost import format_money
from codelotte.evals.meta import EvalRunMeta
from codelotte.evals.report_utils import (
    dirty_text,
    periods_text as _periods_text,
    rate as _rate,
    relative as _relative,
    short as _short,
)
from codelotte.evals.results import EvalCaseResult


@dataclass(frozen=True)
class TaskSummary:
    """一条任务的聚合行。"""

    task_id: str
    bucket: str
    attempts: int
    passed: int
    pass_pow_k: bool
    model_calls: int
    cost: float
    duration_seconds: float
    periods: tuple[tuple[str, int], ...]
    judge_calls: int = 0
    judge_cost: float = 0.0
    judge_used: bool = False
    judge_unreliable: int = 0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.attempts if self.attempts else 0.0


def _merge_periods(
    cases: Sequence[EvalCaseResult],
) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = defaultdict(int)
    for case in cases:
        for period, count in case.periods:
            totals[period] += count
    return tuple(sorted(totals.items()))


def summarize_eval(
    cases: Sequence[EvalCaseResult], *, repetitions: int
) -> list[TaskSummary]:
    """按任务聚合；任务顺序按首次出现（即任务文件顺序），pass^k 要求跑满 repetitions。"""
    grouped: dict[str, list[EvalCaseResult]] = defaultdict(list)
    for case in cases:
        grouped[case.task_id].append(case)
    summaries: list[TaskSummary] = []
    for task_id, group in grouped.items():
        passed = sum(1 for case in group if case.passed)
        summaries.append(
            TaskSummary(
                task_id=task_id,
                bucket=group[0].bucket,
                attempts=len(group),
                passed=passed,
                pass_pow_k=len(group) == repetitions and passed == len(group),
                model_calls=sum(case.model_calls for case in group),
                cost=sum(case.cost for case in group),
                duration_seconds=sum(case.duration_seconds for case in group),
                periods=_merge_periods(group),
                judge_calls=sum(case.judge_calls for case in group),
                judge_cost=sum(case.judge_cost for case in group),
                judge_used=any(case.judge_used for case in group),
                judge_unreliable=sum(
                    1
                    for case in group
                    if case.judge_used and case.judge_reliable is False
                ),
            )
        )
    return summaries


def _case_detail(case: EvalCaseResult) -> str:
    detail = case.verifier_detail
    if case.error:
        detail = f"{detail}；运行错误：{case.error}"
    if case.flagged:
        detail = f"{detail}；作弊标记：{case.flag_reason or '保护文件被改动'}"
    return detail


def _meta_table(meta: EvalRunMeta) -> list[str]:
    dirty = dirty_text(meta.git_dirty, meta.git_diff_sha)
    lines = [
        "| 项 | 值 |",
        "|---|---|",
        f"| run id | `{meta.run_id}` |",
        f"| 开始 / 结束 | {meta.started_at} → {meta.finished_at} |",
        f"| git ref | `{meta.git_ref}` |",
        f"| 工作树有改动 | {dirty} |",
        f"| harness / 类型 | `{meta.harness}` / {meta.harness_kind} |",
        f"| harness 版本 / 隔离 | {meta.harness_version or '未知'} / {meta.isolation} |",
        f"| 模型 / 思考档位 | `{meta.model}` / `{meta.reasoning_effort}` |",
        f"| 上下文窗口 | {meta.context_window} |",
        f"| 每个任务重复次数 | {meta.repetitions} |",
        f"| 随机种子 | {meta.seed} |",
        f"| Python / codelotte | {meta.python} / {meta.codelotte_version} |",
        f"| uv.lock SHA-256 | `{meta.uv_lock_sha or 'missing'}` |",
        f"| 命令 | `{meta.command}` |",
    ]
    return lines


def _task_meta_table(meta: EvalRunMeta) -> list[str]:
    lines = [
        "| 任务 | 桶 | 语义指纹 | 仓库快照 |",
        "|---|---|---|---|",
    ]
    for task in meta.tasks:
        snapshot = f"`{task.snapshot_ref}`" if task.snapshot_ref else "—"
        lines.append(
            f"| {task.id} | {task.bucket} | `{task.sha256}` | {snapshot} |"
        )
    return lines


def _judge_summary(summary: TaskSummary, currency: str) -> str:
    if not summary.judge_used:
        return "—"
    text = f"{summary.judge_calls} 次 / {format_money(summary.judge_cost, currency)}"
    if summary.judge_unreliable:
        text += " ⚠"
    return text


def _summary_table(
    summaries: Sequence[TaskSummary], repetitions: int, currency: str
) -> list[str]:
    lines = [
        f"| 任务 | 桶 | 尝试 | 通过 | 成功率 | pass^{repetitions} | "
        "模型调用 | 总成本 | judge | 平均耗时 | 计费时段 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for summary in summaries:
        mean_duration = (
            summary.duration_seconds / summary.attempts if summary.attempts else 0.0
        )
        mark = "✅" if summary.pass_pow_k else "❌"
        lines.append(
            f"| {summary.task_id} | {summary.bucket} | {summary.attempts} | "
            f"{summary.passed} | {_rate(summary.passed, summary.attempts)} | {mark} | "
            f"{summary.model_calls} | {format_money(summary.cost, currency)} | "
            f"{_judge_summary(summary, currency)} | "
            f"{mean_duration:.1f}s | {_periods_text(summary.periods)} |"
        )
    return lines


def _judge_case_cell(case: EvalCaseResult) -> str:
    if not case.judge_used:
        return "—"
    if case.judge_error is not None:
        text = "❌ 失败"
    else:
        mark = "✅" if case.judge_passed else "❌"
        text = f"{case.judge_overall:.2f} {mark}" if case.judge_overall is not None else mark
    if case.judge_reliable is False:
        text += " ⚠"
    return text


def _case_table(cases: Sequence[EvalCaseResult], run_dir: Path, currency: str) -> list[str]:
    lines = [
        "| 任务 | 重复 | 通过 | 标记 | 验收 / 错误 | judge | 模型调用 | 成本 | 耗时 | 计费时段 | 轨迹 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        mark = "✅" if case.passed else "❌"
        flagged = "⚠" if case.flagged else "—"
        session = _relative(case.session_path, run_dir)
        lines.append(
            f"| {case.task_id} | r{case.repetition} | {mark} | {flagged} | "
            f"{_short(_case_detail(case))} | {_judge_case_cell(case)} | "
            f"{case.model_calls} | {format_money(case.cost, currency)} | "
            f"{case.duration_seconds:.1f}s | {_periods_text(case.periods)} | "
            f"`{session}` |"
        )
    return lines


def _judge_section(cases: Sequence[EvalCaseResult]) -> list[str]:
    used = [case for case in cases if case.judge_used]
    lines = ["## LLM judge", ""]
    if not used:
        lines.append(
            "无（没有任务声明 `[verifier.judge]`，或确定性检查先失败；确定性验收优先）。"
        )
        lines.append("")
        return lines
    for case in used:
        if case.judge_error is not None:
            lines.append(
                f"- `{case.task_id}` r{case.repetition}：judge 失败：{case.judge_error}"
            )
        else:
            mark = "通过" if case.judge_passed else "未通过"
            kappa = (
                f"κ={case.judge_kappa:.2f}（{case.judge_samples} 样本）"
                if case.judge_kappa is not None
                else "κ 缺失"
            )
            reliable = "✅ 可靠" if case.judge_reliable else "⚠ 不可靠"
            overall = (
                f"{case.judge_overall:.2f}" if case.judge_overall is not None else "—"
            )
            lines.append(
                f"- `{case.task_id}` r{case.repetition}：overall {overall}（{mark}）；"
                f"{kappa}；{reliable}"
            )
        if case.judge_warning:
            lines.append(f"  - ⚠ {case.judge_warning}")
        for dimension, score in case.judge_scores:
            reason = dict(case.judge_reasons).get(dimension, "")
            lines.append(f"  - {dimension} {score:.2f}：{reason}")
    lines.append("")
    return lines


def _failure_section(cases: Sequence[EvalCaseResult], run_dir: Path) -> list[str]:
    failures = [case for case in cases if not case.passed]
    lines = ["## 失败案例", ""]
    if not failures:
        lines.append("无。")
    else:
        for case in failures:
            session = _relative(case.session_path, run_dir)
            lines.append(
                f"- `{case.task_id}` r{case.repetition}：{_short(_case_detail(case))}"
                f"（会话 `{session}`）"
            )
    lines.append("")
    return lines


def render_eval_markdown(
    meta: EvalRunMeta, cases: Sequence[EvalCaseResult], run_dir: Path
) -> str:
    summaries = summarize_eval(cases, repetitions=meta.repetitions)
    passed = sum(summary.passed for summary in summaries)
    attempts = sum(summary.attempts for summary in summaries)
    pass_tasks = sum(1 for summary in summaries if summary.pass_pow_k)
    total_cost = sum(summary.cost for summary in summaries)
    total_duration = sum(summary.duration_seconds for summary in summaries)
    periods = _merge_periods(cases)
    lines = [
        "# 评测报表（通用测评）",
        "",
        f"> 一轮跑数：{len(meta.tasks)} 条任务 × {meta.repetitions} 次重复 = "
        f"{len(cases)} 条案例。数字与原始轨迹同目录，可用文末命令复现。",
        "",
        "## 结论速览",
        "",
        f"- 任务：{len(summaries)} · 案例：{len(cases)} · "
        f"通过：{_rate(passed, attempts)}",
        f"- pass^{meta.repetitions}：{pass_tasks}/{len(summaries)} 条任务全部重复通过",
        f"- 总成本：{format_money(total_cost, meta.currency)} · "
        f"总耗时：{total_duration:.1f}s",
        f"- 计费时段：{_periods_text(periods)}",
        "",
        *_summary_table(summaries, meta.repetitions, meta.currency),
        "",
        "读法：",
        "",
        "- **成功率** = 通过案例 / 尝试案例；运行错误也算失败，不剔除。",
        f"- **pass^{meta.repetitions}** = 该任务的全部 {meta.repetitions} 次重复都通过；"
        "少跑一次或错一次都记 ❌。",
        "- 成本来自每次模型调用的 usage 记录；时段是调用当时的实际峰谷判定。",
        "",
        "## 复现锁定",
        "",
        *_meta_table(meta),
        "",
        "任务指纹与仓库快照：",
        "",
        *_task_meta_table(meta),
        "",
        "## 逐案例结果",
        "",
        *_case_table(cases, run_dir, meta.currency),
        "",
        *_judge_section(cases),
        *_failure_section(cases, run_dir),
        "## 口径",
        "",
        "- 任务由 TOML 定义：`id` / `bucket` / `instruction` / `setup`（初始文件或仓库快照）/ "
        "`verifier` / 预算；任务文件是可信输入。",
        "- 验收阶梯：命令式检查（command / python / 文件比对）先跑；只有任务显式声明 "
        "`[verifier.judge]` 且确定性检查通过时才调用 judge，确定性失败不会调用 judge。",
        "- judge 的分数/理由/κ 在本报表的“LLM judge”段；judge 成本计入总成本。"
        "κ 低于任务阈值、样本 <20、校准缺失或标注者为草稿都会标 ⚠，"
        "但不会静默丢弃分数。",
        "- 仓库快照在开跑前解析成 commit SHA 并写进上表；同一轮所有重复使用同一个快照。",
        "- 原始轨迹在 `sessions/`，最终工作区在 `workspaces/`；"
        "失败案例的会话路径见上表与失败案例段。",
        "- 通用测评使用生产压缩策略（不强制压缩）；压缩回归仍用 "
        "`codelotte eval compaction`。",
        "",
        "## 复现",
        "",
        "```bash",
        meta.command,
        "```",
        "",
    ]
    return "\n".join(lines)


def write_eval_report(
    run_dir: Path, meta: EvalRunMeta, cases: Sequence[EvalCaseResult]
) -> Path:
    """写 report.json / report.md；原始轨迹已在 sessions/。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    summaries = summarize_eval(cases, repetitions=meta.repetitions)
    payload = {
        "meta": asdict(meta),
        "summaries": [asdict(summary) for summary in summaries],
        "cases": [asdict(case) for case in cases],
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report_path = run_dir / "report.md"
    report_path.write_text(
        render_eval_markdown(meta, cases, run_dir), encoding="utf-8", newline="\n"
    )
    return report_path
