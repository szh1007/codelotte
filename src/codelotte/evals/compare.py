"""多 harness 对照与控制 agent 自检（票据 16）。

`run_comparison` 把同一个任务集依次跑过多个 harness（codelotte / mini-swe-agent /
裸单轮 API，或三种控制 agent），每组落一份独立报表，再在父目录写一份任务级并列
对比。控制组额外做"预期 vs 实际"的硬检查，失败时 CLI 返回非零。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from codelotte.cost import format_money
from codelotte.evals.eval_report import TaskSummary, summarize_eval
from codelotte.evals.judge import JudgeContext
from codelotte.evals.meta import EvalRunMeta
from codelotte.evals.report_utils import dirty_text, rate, relative, short
from codelotte.evals.results import EvalCaseResult
from codelotte.evals.runner import HarnessFactory, run_harness_suite
from codelotte.evals.tasks import Task

HARNESS_LABELS = {
    "codelotte": "codelotte",
    "mini-swe-agent": "mini-swe-agent",
    "raw": "裸单轮 API",
    "oracle": "oracle",
    "no-op": "no-op",
    "cheating": "cheating",
}


@dataclass(frozen=True)
class HarnessRun:
    """一组 harness 的完整结果（组报表 + 案例）。"""

    name: str
    kind: str
    isolation: str
    meta: EvalRunMeta
    cases: tuple[EvalCaseResult, ...]

    def summaries(self) -> list[TaskSummary]:
        return summarize_eval(self.cases, repetitions=self.meta.repetitions)


@dataclass(frozen=True)
class ControlCheck:
    """一条控制 agent 自检结论。"""

    harness: str
    expectation: str
    actual: str
    passed: bool


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "harness"


def _label(name: str) -> str:
    return HARNESS_LABELS.get(name, name)


def evaluate_controls(runs: Sequence[HarnessRun]) -> list[ControlCheck]:
    """按票据验收句检查三组控制 agent：oracle 100%、no-op 0%、cheating 0% 且被标记。"""
    by_name = {run.name: run for run in runs}
    checks: list[ControlCheck] = []

    def add(name: str, expectation: str, actual: str, passed: bool) -> None:
        checks.append(
            ControlCheck(
                harness=name,
                expectation=expectation,
                actual=actual,
                passed=passed,
            )
        )

    oracle = by_name.get("oracle")
    if oracle is None:
        add("oracle", "全部案例通过（100%）", "缺失", False)
    else:
        attempts = len(oracle.cases)
        passed = sum(1 for case in oracle.cases if case.passed)
        add(
            "oracle",
            "全部案例通过（100%）",
            f"{passed}/{attempts}",
            attempts > 0 and passed == attempts,
        )

    noop = by_name.get("no-op")
    if noop is None:
        add("no-op", "全部案例不通过（0%）", "缺失", False)
    else:
        attempts = len(noop.cases)
        passed = sum(1 for case in noop.cases if case.passed)
        flagged = sum(1 for case in noop.cases if case.flagged)
        add(
            "no-op",
            "全部案例不通过（0%）",
            f"{passed}/{attempts}",
            attempts > 0 and passed == 0,
        )
        add(
            "no-op",
            "不产生作弊标记",
            f"{flagged}/{attempts}",
            flagged == 0,
        )

    cheating = by_name.get("cheating")
    if cheating is None:
        add("cheating", "全部案例不通过（0%）且全部被标记", "缺失", False)
    else:
        attempts = len(cheating.cases)
        passed = sum(1 for case in cheating.cases if case.passed)
        flagged = sum(1 for case in cheating.cases if case.flagged)
        add(
            "cheating",
            "全部案例不通过（0%）且全部被标记",
            f"{passed}/{attempts} 通过，{flagged}/{attempts} 标记",
            attempts > 0 and passed == 0 and flagged == attempts,
        )
    return checks


async def run_comparison(
    tasks: Sequence[Task],
    *,
    harnesses: Sequence[tuple[str, HarnessFactory]],
    repetitions: int,
    run_dir: Path,
    repo_root: Path,
    seed: int,
    command: str,
    model: str,
    reasoning_effort: str,
    context_window: int,
    currency: str = "CNY",
    judge_context: JudgeContext | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[HarnessRun], list[ControlCheck] | None]:
    """依次跑多组 harness，父目录落任务级并列对比；控制组返回自检结论。"""
    if not harnesses:
        raise ValueError("至少要有一组 harness")
    run_dir.mkdir(parents=True, exist_ok=True)
    runs: list[HarnessRun] = []
    for name, factory in harnesses:
        if progress is not None:
            progress(f"== {_label(name)} ==")
        harness_dir = run_dir / "harnesses" / _slug(name)
        meta, cases = await run_harness_suite(
            tasks,
            harness_factory=factory,
            repetitions=repetitions,
            run_id=name,
            run_dir=harness_dir,
            exclude=run_dir,
            repo_root=repo_root,
            seed=seed,
            command=command,
            currency=currency,
            model=model,
            reasoning_effort=reasoning_effort,
            context_window=context_window,
            judge_context=judge_context,
            progress=progress,
        )
        runs.append(
            HarnessRun(
                name=name,
                kind=meta.harness_kind,
                isolation=meta.isolation,
                meta=meta,
                cases=tuple(cases),
            )
        )
    kinds = {run.kind for run in runs}
    if len(kinds) > 1:
        raise ValueError("控制 agent 与真实 harness 不能混在同一轮对照里")
    mode = "controls" if kinds == {"control"} else "compare"
    checks = evaluate_controls(runs) if mode == "controls" else None
    write_comparison_report(
        run_dir, runs, command=command, mode=mode, checks=checks
    )
    return runs, checks


def _overall_table(runs: Sequence[HarnessRun], currency: str) -> list[str]:
    repetitions = runs[0].meta.repetitions if runs else 0
    lines = [
        f"| 组 | 类型 | 尝试 | 通过 | 成功率 | pass^{repetitions} 任务 | "
        "模型调用 | 总成本 | 平均耗时/案例 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        summaries = run.summaries()
        attempts = sum(summary.attempts for summary in summaries)
        passed = sum(summary.passed for summary in summaries)
        pass_tasks = sum(1 for summary in summaries if summary.pass_pow_k)
        calls = sum(summary.model_calls for summary in summaries)
        cost = sum(summary.cost for summary in summaries)
        duration = sum(summary.duration_seconds for summary in summaries)
        mean = duration / attempts if attempts else 0.0
        cost_text = format_money(cost, currency) if calls else "—"
        if run.kind == "control":
            kind = "控制 agent"
        elif run.name == "raw":
            kind = "基线（无工具）"
        else:
            kind = "真实 harness"
        lines.append(
            f"| {_label(run.name)} | {kind} | {attempts} | {passed} | "
            f"{rate(passed, attempts)} | {pass_tasks}/{len(summaries)} | "
            f"{calls} | {cost_text} | {mean:.1f}s |"
        )
    return lines


def _cell(
    summary: TaskSummary | None, repetitions: int, currency: str
) -> str:
    if summary is None:
        return "—"
    mark = "✅" if summary.pass_pow_k else "❌"
    mean = summary.duration_seconds / summary.attempts if summary.attempts else 0.0
    cost_text = (
        format_money(summary.cost, currency) if summary.model_calls else "—"
    )
    return (
        f"{mark} {summary.passed}/{summary.attempts} · pass^{repetitions} · "
        f"{cost_text} · {mean:.1f}s"
    )


def _task_table(runs: Sequence[HarnessRun], currency: str) -> list[str]:
    if not runs:
        return []
    repetitions = runs[0].meta.repetitions
    task_ids: list[str] = [task.id for task in runs[0].meta.tasks]
    seen = set(task_ids)
    for run in runs:
        for case in run.cases:
            if case.task_id not in seen:
                seen.add(case.task_id)
                task_ids.append(case.task_id)
    buckets: dict[str, str] = {}
    for run in runs:
        for case in run.cases:
            buckets.setdefault(case.task_id, case.bucket)
    headers = ["任务", "桶", *[_label(run.name) for run in runs]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "---|" * len(headers),
    ]
    summaries = {
        run.name: {summary.task_id: summary for summary in run.summaries()}
        for run in runs
    }
    for task_id in task_ids:
        cells = [
            _cell(summaries[run.name].get(task_id), repetitions, currency)
            for run in runs
        ]
        lines.append(
            f"| {task_id} | {buckets.get(task_id, '—')} | " + " | ".join(cells) + " |"
        )
    return lines


def _failure_section(runs: Sequence[HarnessRun], run_dir: Path) -> list[str]:
    lines = ["## 失败定位", ""]
    any_failure = False
    for run in runs:
        failures = [case for case in run.cases if not case.passed]
        report_link = relative(
            str(run_dir / "harnesses" / _slug(run.name) / "report.md"), run_dir
        )
        if not failures:
            lines.append(f"- **{_label(run.name)}**：无失败；逐案例见 `{report_link}`。")
            continue
        any_failure = True
        lines.append(
            f"- **{_label(run.name)}**：{len(failures)}/{len(run.cases)} 失败；"
            f"逐案例见 `{report_link}`。"
        )
        for case in failures:
            trace = relative(case.session_path, run_dir)
            flag = "（作弊标记）" if case.flagged else ""
            lines.append(
                f"  - `{case.task_id}` r{case.repetition}{flag}："
                f"{short(case.verifier_detail, 160)}（轨迹 `{trace}`）"
            )
    if not any_failure:
        lines.append("")
        lines.append("各组均无失败。")
    lines.append("")
    return lines


def _meta_table(runs: Sequence[HarnessRun], run_dir: Path, command: str) -> list[str]:
    meta = runs[0].meta
    dirty = dirty_text(meta.git_dirty, meta.git_diff_sha)
    lines = [
        "| 项 | 值 |",
        "|---|---|",
        f"| run id | `{run_dir.name}` |",
        f"| 开始 / 结束 | {meta.started_at} → {max(run.meta.finished_at for run in runs)} |",
        f"| git ref | `{meta.git_ref}` |",
        f"| 工作树有改动 | {dirty} |",
        f"| 模型 / 思考档位 | `{meta.model}` / `{meta.reasoning_effort or '—'}` |",
        f"| 上下文窗口 | {meta.context_window or '—'} |",
        f"| 每个任务重复次数 | {meta.repetitions} |",
        f"| 随机种子 | {meta.seed} |",
        f"| Python / codelotte | {meta.python} / {meta.codelotte_version} |",
        f"| uv.lock SHA-256 | `{meta.uv_lock_sha or 'missing'}` |",
        f"| 命令 | `{command}` |",
        "",
        "| 任务 | 桶 | 语义指纹 | 仓库快照 |",
        "|---|---|---|---|",
    ]
    for task in meta.tasks:
        snapshot = f"`{task.snapshot_ref}`" if task.snapshot_ref else "—"
        lines.append(f"| {task.id} | {task.bucket} | `{task.sha256}` | {snapshot} |")
    return lines


def _checks_section(checks: Sequence[ControlCheck]) -> list[str]:
    lines = [
        "## 自检结论",
        "",
        "| 控制 agent | 预期 | 实际 | 结论 |",
        "|---|---|---|---|",
    ]
    for check in checks:
        mark = "✅" if check.passed else "❌"
        lines.append(
            f"| {_label(check.harness)} | {check.expectation} | "
            f"{check.actual} | {mark} |"
        )
    overall = all(check.passed for check in checks) if checks else False
    lines.extend(
        [
            "",
            (
                "**总体：✅ 评测系统自检通过**（oracle 全过、no-op 全败、cheating 全败且被标记）"
                if overall
                else "**总体：❌ 评测系统自检未通过**——先修评测器，再相信任何真实跑分。"
            ),
            "",
        ]
    )
    return lines


def _limits_section(mode: str) -> list[str]:
    lines = ["## 口径与限制", ""]
    if mode == "controls":
        lines.extend(
            [
                "- 三组使用同一任务集、同一重复次数；控制 agent 不调用模型，"
                "成本/耗时只反映文件操作与验收，不参与真实模型的横向比较。",
                "- 成功率 = 通过案例 / 尝试案例，运行错误也算失败。",
                "- oracle 直接落任务参考解（`[control.oracle.files]`）或从文件期望推导；"
                "no-op 什么都不做；cheating 写假成功内容并篡改所有 `unchanged` 保护文件。",
                "- 控制组的意义是校验评测器本身：oracle 应 100%、no-op 应 0%、"
                "cheating 应 0% 且全部被标记；任何一条不符，说明评分链路有 bug。",
                "- 任务里的「执行纪律」（必须用哪些工具）不在验收范围内，这里只看最终状态；"
                "这对控制 agent 自检没有影响，但读真实对照时要记住同一条口径。",
            ]
        )
        lines.append("")
        return lines
    lines.extend(
        [
            "- 同一轮里所有组使用同一任务集、同一重复次数、同一模型与思考档位"
            "（mini 通过 `model_kwargs.reasoning_effort` 传入；其余请求参数由各 harness 自组装）；",
            "  成功率 = 通过案例 / 尝试案例，运行错误也算失败。",
            "- 成本按每次调用的实际 usage 与**本项目**峰谷价目表估算；"
            "codelotte 来自事件流，mini-swe-agent 来自本地录制代理，裸单轮 API 来自流式 usage。",
            "- 裸单轮 API 只有一次 user 消息、没有 tools：它是「模型自己」的下界。",
            "- mini-swe-agent 只有 bash 工具，在本地临时工作区执行；"
            "它的成本/调用次数来自代理，不依赖 litellm 是否认识 DeepSeek 模型。",
            "- 思考档位已对齐，但 `max_tokens`、提示词模板等仍由各 harness 自己决定；"
            "这不是同策略 A/B，而是同一模型下两套 scaffolding 的最终状态对比。",
            "- 任务里的「执行纪律」（必须用哪些工具）不在验收范围内，验收只看最终状态；"
            "因此 mini-swe-agent 可能用 bash 完成要求 read/write 的任务，读表时不要把它当成同一策略。",
            "- codelotte 的隔离方式看各组 `report.md` 的 meta（Docker / local）；"
            "对照组默认跟随 `--no-sandbox` 设置，做耗时对比时请让两组使用同一种隔离。",
            "- 任务声明了 `[verifier.judge]` 时，judge 成本计入该组总成本；"
            "分数/理由/κ 见每组明细报表的“LLM judge”段。",
        ]
    )
    lines.append("")
    return lines


def render_comparison_markdown(
    runs: Sequence[HarnessRun],
    run_dir: Path,
    *,
    command: str,
    mode: str,
    checks: Sequence[ControlCheck] | None = None,
) -> str:
    if mode == "controls" and checks is None:
        checks = evaluate_controls(runs)
    title = "控制 agent 自检" if mode == "controls" else "对照组"
    currency = runs[0].meta.currency if runs else "CNY"
    repetitions = runs[0].meta.repetitions if runs else 0
    task_count = len(runs[0].meta.tasks) if runs else 0
    lines = [
        f"# 评测报表（{title}）",
        "",
        f"> {len(runs)} 组 × {task_count} 条任务 × {repetitions} 次重复。"
        "各组明细在 `harnesses/<组名>/report.md`，本页是任务级并列对比。",
        "",
    ]
    if checks is not None:
        lines.extend(_checks_section(checks))
    lines.extend(
        [
            "## 总体对比",
            "",
            *_overall_table(runs, currency),
            "",
            "## 任务级并列对比",
            "",
            *_task_table(runs, currency),
            "",
            "单元格读法：通过标记 · 通过/尝试 · pass^N · 总成本 · 平均耗时/案例；"
            "`—` 表示该组没有这条任务。",
            "",
            *_failure_section(runs, run_dir),
            "## 复现锁定",
            "",
            *_meta_table(runs, run_dir, command),
            "",
            *_limits_section(mode),
            "## 复现",
            "",
            "```bash",
            command,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_comparison_report(
    run_dir: Path,
    runs: Sequence[HarnessRun],
    *,
    command: str,
    mode: str,
    checks: Sequence[ControlCheck] | None = None,
) -> Path:
    """写父目录的 report.md / report.json（各组自己的报表已由 runner 写好）。"""
    if mode == "controls" and checks is None:
        checks = evaluate_controls(runs)
    run_dir.mkdir(parents=True, exist_ok=True)
    common: dict[str, object] = (
        asdict(runs[0].meta) if runs else {"run_id": run_dir.name}
    )
    common.update(
        {
            "run_id": run_dir.name,
            "command": command,
            "finished_at": max(
                (run.meta.finished_at for run in runs), default=common.get("finished_at", "")
            ),
            # 父报表代表的是一轮对照/自检，不是第一组 harness 自己
            "harness": mode,
            "harness_kind": "comparison",
            "isolation": "mixed",
        }
    )
    payload = {
        "mode": mode,
        "meta": common,
        "harnesses": [
            {
                "name": run.name,
                "kind": run.kind,
                "isolation": run.isolation,
                "meta": asdict(run.meta),
                "summaries": [asdict(summary) for summary in run.summaries()],
                "cases": [asdict(case) for case in run.cases],
            }
            for run in runs
        ],
        "checks": [asdict(check) for check in checks] if checks is not None else None,
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report_path = run_dir / "report.md"
    report_path.write_text(
        render_comparison_markdown(
            runs, run_dir, command=command, mode=mode, checks=checks
        ),
        encoding="utf-8",
        newline="\n",
    )
    return report_path
