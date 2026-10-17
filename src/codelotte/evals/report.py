"""压缩回归报表（票据 13）：聚合、Markdown 报告与人工标注表。

口径（同时写进 evals/compaction.md）：
- 完成率 = 验收通过 / 尝试次数（失败的 run 不剔除——失败也是结果）；
- 有效案例 = 没有运行错误且实际压缩次数 == k（k=0 的对照组天然有效）；
- 状态保留率 = checkpoint 问题通过数 / 问题总数（包含无效案例，报表里单独标出）；
- 成本 = 被测任务 + checkpoint 探针（探针也是真金白银）。
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from codelotte.cost import format_money
from codelotte.evals.meta import RunMeta
from codelotte.evals.regression import CaseResult
from codelotte.evals.report_utils import (
    dirty_text,
    rate as _rate,
    relative as _relative,
    short as _short,
)


@dataclass(frozen=True)
class GroupSummary:
    """一个 k 的聚合行。"""

    k: int
    attempted: int
    completed: int
    valid: int
    valid_completed: int
    retention_passed: int
    retention_total: int
    valid_retention_passed: int
    valid_retention_total: int
    total_compactions: int
    model_calls: int
    cost: float

    @property
    def invalid(self) -> int:
        return self.attempted - self.valid


def summarize(cases: Sequence[CaseResult]) -> list[GroupSummary]:
    """按 k 聚合；k 升序，缺的 k 不补行（报表只呈现真实跑过的点）。"""
    grouped: dict[int, list[CaseResult]] = defaultdict(list)
    for case in cases:
        grouped[case.k].append(case)
    summaries: list[GroupSummary] = []
    for k in sorted(grouped):
        group = grouped[k]
        valid = [case for case in group if case.valid]
        summaries.append(
            GroupSummary(
                k=k,
                attempted=len(group),
                completed=sum(1 for case in group if case.completed),
                valid=len(valid),
                valid_completed=sum(1 for case in valid if case.completed),
                retention_passed=sum(case.retention_passed for case in group),
                retention_total=sum(case.retention_total for case in group),
                valid_retention_passed=sum(case.retention_passed for case in valid),
                valid_retention_total=sum(case.retention_total for case in valid),
                total_compactions=sum(case.compactions for case in group),
                model_calls=sum(case.model_calls for case in group),
                cost=sum(case.cost + case.probe_cost for case in group),
            )
        )
    return summaries


def _k_label(k: int) -> str:
    return "k=0（对照组）" if k == 0 else f"k={k}"


def _summary_table(summaries: Sequence[GroupSummary], currency: str) -> list[str]:
    lines = [
        "| k | 尝试 | 完成率 | 有效案例 | 有效完成率 | 状态保留率（全部） | "
        "状态保留率（有效） | 平均压缩次数 | 模型调用 | 成本 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for group in summaries:
        mean = group.total_compactions / group.attempted if group.attempted else 0.0
        lines.append(
            f"| {_k_label(group.k)} | {group.attempted} | "
            f"{_rate(group.completed, group.attempted)} | "
            f"{_rate(group.valid, group.attempted)} | "
            f"{_rate(group.valid_completed, group.valid)} | "
            f"{_rate(group.retention_passed, group.retention_total)} | "
            f"{_rate(group.valid_retention_passed, group.valid_retention_total)} | "
            f"{mean:.1f} | {group.model_calls} | "
            f"{format_money(group.cost, currency)} |"
        )
    return lines


def _meta_table(meta: RunMeta) -> list[str]:
    dirty = dirty_text(meta.git_dirty, meta.git_diff_sha)
    k_values = ", ".join(str(k) for k in meta.k_values)
    lines = [
        "| 项 | 值 |",
        "|---|---|",
        f"| run id | `{meta.run_id}` |",
        f"| 开始 / 结束 | {meta.started_at} → {meta.finished_at} |",
        f"| git ref | `{meta.git_ref}` |",
        f"| 工作树有改动 | {dirty} |",
        f"| 模型 / 思考档位 | `{meta.model}` / `{meta.reasoning_effort}` |",
        f"| 上下文窗口 | {meta.context_window} |",
        f"| 压缩阈值 soft / hard | {meta.soft:.2f} / {meta.hard:.2f} |",
        f"| k 集合 / 重复次数 | {k_values} / {meta.repetitions} |",
        f"| 随机种子 | {meta.seed} |",
        f"| Python / codelotte | {meta.python} / {meta.codelotte_version} |",
        f"| uv.lock SHA-256 | `{meta.uv_lock_sha or 'missing'}` |",
        f"| 命令 | `{meta.command}` |",
    ]
    for task in meta.tasks:
        snapshot = f"；快照 `{task.snapshot_ref}`" if task.snapshot_ref else ""
        lines.append(
            f"| 任务 {task.id}（{task.bucket} 桶） | `{task.sha256}`{snapshot} |"
        )
    return lines


def _case_table(cases: Sequence[CaseResult], run_dir: Path) -> list[str]:
    lines = [
        "| 任务 | k | 有效 | 压缩次数 | 完成 | 状态保留 | 验收 / 错误 | 会话 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in cases:
        valid = "✅" if case.valid else "❌"
        completed = "✅" if case.completed else "❌"
        retention = (
            _rate(case.retention_passed, case.retention_total)
            if case.retention_total
            else "—"
        )
        detail = _short(case.verifier_detail)
        session = _relative(case.session_path, run_dir) if case.session_path else "—"
        lines.append(
            f"| {case.task_id} | {case.k} | {valid} | "
            f"{case.compactions}/{case.k} | {completed} | {retention} | "
            f"{detail} | `{session}` |"
        )
    return lines


def _checkpoint_details(cases: Sequence[CaseResult]) -> list[str]:
    lines = ["## Checkpoint 明细", ""]
    for case in cases:
        if not case.checkpoints:
            continue
        lines.append(f"### {case.task_id} · k={case.k} · rep={case.repetition}")
        lines.append("")
        for observation in case.checkpoints:
            if observation.error is not None:
                lines.append(
                    f"- 压缩 #{observation.compaction}：探针失败（{observation.error}）"
                )
                continue
            structured = "结构化" if observation.structured else "未按编号（兜底整段）"
            lines.append(
                f"- 压缩 #{observation.compaction}（{structured}）："
                f"{observation.passed}/{observation.total} 通过"
            )
            for score in observation.scores:
                mark = "✅" if score.passed else "❌"
                detail = (
                    f"命中 {', '.join(score.matched)}"
                    if score.passed
                    else f"缺失 {', '.join(score.missing)}"
                )
                if score.misplaced:
                    detail += f"（跨段：{', '.join(score.misplaced)}）"
                lines.append(f"  - {mark} {score.question} — {detail}")
            if observation.answer.strip():
                lines.append("")
                for answer_line in observation.answer.strip().splitlines():
                    lines.append(f"  > {answer_line}")
                lines.append("")
        lines.append("")
    return lines


def render_markdown(meta: RunMeta, cases: Sequence[CaseResult], run_dir: Path) -> str:
    summaries = summarize(cases)
    lines = [
        "# 压缩回归报表 v0",
        "",
        f"> 一轮跑数：{len(cases)} 条案例（{len(meta.tasks)} 条任务 × "
        f"{len(meta.k_values)} 个 k × {meta.repetitions} 次重复）。"
        "数字与原始轨迹同目录，可用文末命令复现。",
        "",
        "## 结论速览",
        "",
        *_summary_table(summaries, meta.currency),
        "",
        "读法：",
        "",
        "- **完成率**：验收通过 / 尝试次数。任务失败是数据，不剔除。",
        "- **有效案例**：运行无错误，且实际压缩次数恰好等于 k；"
        "k=0 是对照组（不压缩），天然有效。",
        "- **状态保留率**：压缩后 checkpoint 问题的通过率（事实在整段回答中出现即算记得；"
        "只写错编号段的跨段命中记入 `misplaced`，不扣保留率）；无效案例也计入“全部”一列。",
        "- 成本包含被测任务与 checkpoint 探针（探针不写回会话，但确实调用模型）。",
        "",
        "## 复现锁定",
        "",
        *_meta_table(meta),
        "",
        "## 逐任务结果",
        "",
        *_case_table(cases, run_dir),
        "",
        *_checkpoint_details(cases),
        "## 人工标注",
        "",
        f"- 标注表：`{(run_dir / 'annotations.csv').name}`（问题、自动判定、完整答案）。",
        "- 规则：在 `human_pass` 列填 `1`（通过）/ `0`（不通过）/ 留空（未标注）。",
        "- 优先复核 `auto_pass=0`、`misplaced` 非空与 `structured=False` 的行；"
        "确定性评分是主口径，人工分在 CSV 里单列。",
        "- v0 基线的人工分由作者在跑数后填写；未填写不影响确定性报表。",
        "",
        "## 方法与口径",
        "",
        "- **强制压缩**：注入 `CompactionPolicy`，在每次请求前若已落盘的 compaction 少于 k，"
        "就按硬触发压到最小保留集；k 次压缩需要至少 k 个 turn，达不到的案例标为无效。",
        "- **checkpoint**：每次压缩后用压缩后的上下文追加一次无工具提问，"
        "答案只用于评分，不写回会话，不污染被测轨迹。",
        "- **确定性评分**：每个问题预定义若干事实组，每组给可接受的替代表述；"
        "事实在整段回答中出现即算保留；只出现在别的编号段时记 `misplaced`，不扣保留率。"
        "编号段解析失败时整段兜底并标记。",
        "- **局限**：关键词比对是代理指标，不等于语义等价；k=0 之外没有消融实验；"
        "v0 每个点只重复一次，随机性只能靠重复次数扩大。",
        "",
        "## 复现",
        "",
        "```bash",
        meta.command,
        "```",
        "",
        "原始轨迹：`sessions/`；最终工作区：`workspaces/`；逐条 checkpoint："
        "`checkpoints.jsonl`；机器可读报表：`report.json`。",
        "",
    ]
    return "\n".join(lines)


def write_report(run_dir: Path, meta: RunMeta, cases: Sequence[CaseResult]) -> Path:
    """写 report.json / report.md / annotations.csv / checkpoints.jsonl。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": asdict(meta),
        "cases": [asdict(case) for case in cases],
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with (run_dir / "annotations.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(
            [
                "run_id",
                "task_id",
                "bucket",
                "k",
                "repetition",
                "compaction",
                "question",
                "auto_pass",
                "structured",
                "misplaced",
                "human_pass",
                "error",
                "answer",
            ]
        )
        for case in cases:
            for observation in case.checkpoints:
                if not observation.scores:
                    writer.writerow(
                        [
                            meta.run_id,
                            case.task_id,
                            case.bucket,
                            case.k,
                            case.repetition,
                            observation.compaction,
                            "",
                            "",
                            "False",
                            "",
                            "",
                            observation.error or "",
                            observation.answer,
                        ]
                    )
                    continue
                for score in observation.scores:
                    writer.writerow(
                        [
                            meta.run_id,
                            case.task_id,
                            case.bucket,
                            case.k,
                            case.repetition,
                            observation.compaction,
                            score.question,
                            "1" if score.passed else "0",
                            "True" if observation.structured else "False",
                            ";".join(score.misplaced),
                            "",
                            observation.error or "",
                            observation.answer,
                        ]
                    )

    with (run_dir / "checkpoints.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as fh:
        for case in cases:
            for observation in case.checkpoints:
                record = {
                    "run_id": meta.run_id,
                    "task_id": case.task_id,
                    "bucket": case.bucket,
                    "k": case.k,
                    "repetition": case.repetition,
                    **asdict(observation),
                }
                fh.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )

    report_path = run_dir / "report.md"
    report_path.write_text(
        render_markdown(meta, cases, run_dir), encoding="utf-8", newline="\n"
    )
    return report_path
