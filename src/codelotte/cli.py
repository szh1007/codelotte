"""codelotte 命令行入口：无参数进 TUI，`-p` 一次性执行，`--continue`/`--resume`/`--fork` 接会话。

恢复三兄弟（互斥）：`--continue` 回到最近活动的分支；`--resume` 列出/选择历史会话与分支；
`--fork N` 从最近会话活动分支的倒数第 N 条消息处分岔（同一文件内成树，原分支不受影响）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codelotte import __version__
from codelotte.changelog import changelog_notice
from codelotte.compaction import CompactionLimits
from codelotte.config import (
    ConfigError,
    Settings,
    load_settings,
    record_changelog_version,
)
from codelotte.cost import Catalog, format_money, load_catalog
from codelotte.evals.attribution import (
    DEFAULT_MIN_ACCURACY,
    FAILURE_CLASSES,
    FAILURE_LABELS,
    MIN_CORPUS_SAMPLES,
    Attribution,
    AttributionError,
    build_attribution_report,
    classify_failure,
    collect_failure_distribution,
    evaluate_corpus,
    load_attribution_samples,
)
from codelotte.evals.compare import run_comparison
from codelotte.evals.defense import (
    DefenseError,
    analyze_defense,
    audit_false_positives,
    collect_injection_results,
    collect_loop_pressure_results,
    defense_summary,
    scenario_plan,
    write_defense_report,
)
from codelotte.evals.cost_report import analyze_run, write_cost_report
from codelotte.evals.execution import CodelotteHarness
from codelotte.evals.judge import (
    MIN_CALIBRATION_SAMPLES,
    JudgeContext,
    JudgeError,
    calibrate,
    judge_reliability,
    load_calibration,
    load_samples,
    write_calibration,
)
from codelotte.evals.harnesses import (
    CheatingHarness,
    NoOpHarness,
    OracleHarness,
    RawHarness,
)
from codelotte.evals.meta import (
    create_run_dir,
    current_git_ref,
    find_repo_root,
    make_run_id,
    resolve_task_snapshots,
)
from codelotte.evals.mini_baseline import (
    MiniSweAgentHarness,
    resolve_mini_command,
)
from codelotte.evals.promote import (
    RegressionTaskError,
    build_regression_task,
    next_regression_id,
    write_regression_task,
)
from codelotte.evals.runner import run_eval_suite
from codelotte.evals.suite import run_suite
from codelotte.evals.tasks import Task, TaskFileError, load_task, load_tasks
from codelotte.export import render_session_html, render_session_markdown
from codelotte.guardrails import GuardrailLimits
from codelotte.models import ModelSpec, resolve
from codelotte.permissions import (
    ALLOW,
    ASK,
    DENY,
    RULES_FILE,
    TRUST_FILE,
    Rule,
    append_rules,
    build_permission_layer,
    is_trusted,
    parse_rule,
    trust_project,
)
from codelotte.loop import AgentLoop
from codelotte.providers.base import ProviderError
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.run import print_session_invoice, run_once
from codelotte.sandbox import DockerExecutor, Executor, LocalExecutor
from codelotte.session.store import (
    SessionError,
    fork_at,
    fork_session,
    latest_session_path,
    list_resumable,
    load_branch,
    open_at,
    open_session,
)
from codelotte.tools import default_tools

# --no-sandbox 的启动警告（-p 打 stderr；TUI 进启动提示）：风险必须显式可见
SANDBOX_OFF_WARNING = (
    "警告：--no-sandbox 已开启——命令将直接在宿主机执行，宿主文件与密钥对 agent 可见；"
    "权限层是唯一防线。本次会话的工具执行会在记录中标记 env=local。"
)


def _reconfigure(stream: object) -> None:
    """尽力把输出流切为 UTF-8 + errors=replace。

    终端/管道/CI 输出一致，避免 Windows 管道默认 GBK 乱码，编码外字符也不崩溃。
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codelotte",
        description="minimal-core, extensible terminal coding agent",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"codelotte {__version__}",
    )
    parser.add_argument(
        "-p",
        "--prompt",
        metavar="PROMPT",
        help='非交互模式：执行一次提示词，流式打印回答后退出（提示词以 "-" 开头时用 `--prompt=...` 形式）',
    )

    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument(
        "-c",
        "--continue",
        dest="continue_",
        action="store_true",
        help="恢复本项目最近一次会话的活动分支，接着聊（--continue）",
    )
    recovery.add_argument(
        "--resume",
        nargs="?",
        const="",
        metavar="序号",
        help="不带序号：列出可恢复的会话/分支（含 fork 标注）；带序号（见列表）：恢复指定分支",
    )
    parser.add_argument(
        "--fork",
        metavar="N",
        type=int,
        help="从会话活动分支的倒数第 N 条消息处创建新分支（N=1 即最后一条），后续对话写在新分支上；"
        "默认对最近会话，可与 --resume <序号> 组合指定别的分支",
    )

    sandbox_group = parser.add_argument_group("沙箱（票据 10）")
    sandbox_group.add_argument(
        "--no-sandbox",
        dest="no_sandbox",
        action="store_true",
        help="逃生门：命令直接在宿主机执行（默认在 Docker 容器里）。启动时打印风险警告，"
        "本次会话的执行记录标记 env=local",
    )

    permission_group = parser.add_argument_group("权限规则（票据 09）")
    permission_group.add_argument(
        "--allow",
        action="append",
        metavar="规则",
        help="放行规则（可重复）：`bash(git diff *)` 或裸 `read`；通配规则不会自动放行破坏性命令",
    )
    permission_group.add_argument(
        "--ask", action="append", metavar="规则", help="必须审批的规则（可重复）"
    )
    permission_group.add_argument(
        "--deny", action="append", metavar="规则", help="拒绝的规则（可重复）"
    )

    subcommands = parser.add_subparsers(dest="command", metavar="命令")
    trust_parser = subcommands.add_parser(
        "trust",
        help="信任本项目目录的权限规则（.codelotte/permissions.json，一次确认）",
    )
    trust_parser.set_defaults(command="trust")
    for verb, verdict, help_text in (
        ("allow", ALLOW, "永久放行一组规则（写入用户级权限文件）"),
        ("ask", ASK, "永久改为每次询问"),
        ("deny", DENY, "永久拒绝"),
    ):
        writer = subcommands.add_parser(verb, help=help_text)
        writer.add_argument(
            "rules", nargs="+", metavar="规则", help="如 `bash(git diff*)` 或裸 `read`"
        )
        writer.add_argument(
            "--project",
            action="store_true",
            help="写进本项目的 .codelotte/permissions.json（需 codelotte trust 确认后生效）",
        )
        writer.set_defaults(command=verb, verdict=verdict)

    export_parser = subcommands.add_parser(
        "export", help="把一次会话导出为自包含 HTML 或 Markdown（票据 08）"
    )
    formats = export_parser.add_mutually_exclusive_group()
    formats.add_argument(
        "--html",
        nargs="?",
        const="",
        metavar="序号",
        help="导出为单文件自包含 HTML（浏览器打开）；不带序号：最近会话的活动分支，"
        "带序号（与 --resume 同一份列表）：指定分支",
    )
    formats.add_argument(
        "--md",
        nargs="?",
        const="",
        metavar="序号",
        help="导出为 Markdown（终端/编辑器直接读）；序号用法同 --html",
    )
    export_parser.add_argument(
        "-o", "--output", metavar="路径", help="输出文件（默认 ./<会话文件名>.html）"
    )

    eval_parser = subcommands.add_parser(
        "eval",
        help="评测与回归实验（票据 13/15/18/20/21）：一条命令跑出完整报表",
    )
    eval_sub = eval_parser.add_subparsers(dest="eval_command", metavar="实验")
    compaction_parser = eval_sub.add_parser(
        "compaction",
        help="专用测评 - 压缩回归 v0：强制压缩 k 次，测完成率与 checkpoint 状态保留率",
    )
    compaction_parser.add_argument(
        "--k",
        default="0,1,3,5",
        metavar="列表",
        help="强制压缩次数（逗号分隔；0 是不压缩的对照组，默认 0,1,3,5）",
    )
    compaction_parser.add_argument(
        "--strategy",
        action="append",
        choices=("minimal", "wide"),
        metavar="策略",
        help="切点策略（可重复）：minimal=最近一个 turn，wide=最近两个 turn；默认 minimal",
    )
    compaction_parser.add_argument(
        "--template",
        action="append",
        choices=("seven", "compact"),
        metavar="模板",
        help="摘要模板（可重复）：seven=七项，compact=目标/已完成/约束三节；默认 seven",
    )
    compaction_parser.add_argument(
        "--combo",
        action="append",
        metavar="策略:模板",
        help="精确指定组合（可重复，如 minimal:compact）；与 --strategy/--template 互斥",
    )
    compaction_parser.add_argument(
        "--tasks", metavar="目录", help="任务目录（默认仓库根下的 evals/tasks）"
    )
    compaction_parser.add_argument(
        "--out", metavar="目录", help="跑数根目录（默认仓库根下的 evals/runs）"
    )
    compaction_parser.add_argument(
        "--repeat", type=int, default=1, metavar="N", help="每个任务 × k 重复次数（默认 1）"
    )
    compaction_parser.add_argument(
        "--seed", type=int, default=0, metavar="N", help="随机种子（默认 0）"
    )
    compaction_parser.add_argument(
        "--task",
        action="append",
        metavar="ID",
        help="只跑指定任务 id（可重复；默认全部）",
    )
    compaction_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验任务文件并打印跑数计划，不调用模型、不建 run 目录",
    )
    compaction_parser.add_argument(
        "--no-sandbox",
        dest="no_sandbox",
        action="store_true",
        help="任务命令直接在宿主机执行（默认 Docker；实验任务仍是临时工作区）",
    )

    run_parser = eval_sub.add_parser(
        "run",
        help="通用测评：任务 × 重复次数，输出 pass^k、每任务成本与耗时",
    )
    run_parser.add_argument(
        "--tasks", metavar="目录", help="任务目录（默认仓库根下的 evals/tasks）"
    )
    run_parser.add_argument(
        "--out", metavar="目录", help="跑数根目录（默认仓库根下的 evals/runs）"
    )
    run_parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        metavar="N",
        help="每个任务重复次数（默认 3；pass^N 要求全部通过）",
    )
    run_parser.add_argument(
        "--seed", type=int, default=0, metavar="N", help="随机种子（默认 0）"
    )
    run_parser.add_argument(
        "--task",
        action="append",
        metavar="ID",
        help="只跑指定任务 id（可重复；默认全部）",
    )
    run_parser.add_argument(
        "--bucket",
        action="append",
        choices=("A", "B", "C"),
        metavar="A/B/C",
        help="只跑指定桶（可重复；默认全部）",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验任务文件/快照 ref 并打印计划，不调用模型、不建 run 目录",
    )
    run_parser.add_argument(
        "--no-sandbox",
        dest="no_sandbox",
        action="store_true",
        help="任务命令直接在宿主机执行（默认 Docker；实验任务仍是临时工作区）",
    )

    compare_parser = eval_sub.add_parser(
        "compare",
        help="对照组：同一任务集跑 codelotte / mini-swe-agent / 裸单轮 API，任务级并列对比",
    )
    compare_parser.add_argument(
        "--harness",
        action="append",
        choices=("codelotte", "mini-swe-agent", "raw"),
        metavar="组",
        help="只跑指定 harness（可重复；默认三组全跑：codelotte、mini-swe-agent、raw）",
    )
    compare_parser.add_argument(
        "--tasks", metavar="目录", help="任务目录（默认仓库根下的 evals/tasks）"
    )
    compare_parser.add_argument(
        "--out", metavar="目录", help="跑数根目录（默认仓库根下的 evals/runs）"
    )
    compare_parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="每个任务重复次数（默认 1；三组使用同一值）",
    )
    compare_parser.add_argument(
        "--seed", type=int, default=0, metavar="N", help="随机种子（默认 0）"
    )
    compare_parser.add_argument(
        "--task",
        action="append",
        metavar="ID",
        help="只跑指定任务 id（可重复；默认全部）",
    )
    compare_parser.add_argument(
        "--bucket",
        action="append",
        choices=("A", "B", "C"),
        metavar="A/B/C",
        help="只跑指定桶（可重复；默认全部）",
    )
    compare_parser.add_argument(
        "--mini-python",
        metavar="解释器",
        help="装了 mini-swe-agent 的 Python 解释器（默认从 PATH 上的 mini 推同环境解释器）",
    )
    compare_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验任务、快照与 harness 可用性并打印计划，不调用模型、不建 run 目录",
    )
    compare_parser.add_argument(
        "--no-sandbox",
        dest="no_sandbox",
        action="store_true",
        help="任务命令直接在宿主机执行（默认 Docker；与 mini-swe-agent 的本地环境对齐）",
    )

    controls_parser = eval_sub.add_parser(
        "controls",
        help="控制 agent 自检：oracle 应 100%%、no-op 应 0%%、cheating 应 0%% 且被标记",
    )
    controls_parser.add_argument(
        "--tasks", metavar="目录", help="任务目录（默认仓库根下的 evals/tasks）"
    )
    controls_parser.add_argument(
        "--out", metavar="目录", help="跑数根目录（默认仓库根下的 evals/runs）"
    )
    controls_parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="每个任务重复次数（默认 1；控制 agent 是确定性的）",
    )
    controls_parser.add_argument(
        "--seed", type=int, default=0, metavar="N", help="随机种子（默认 0）"
    )
    controls_parser.add_argument(
        "--task",
        action="append",
        metavar="ID",
        help="只跑指定任务 id（可重复；默认全部）",
    )
    controls_parser.add_argument(
        "--bucket",
        action="append",
        choices=("A", "B", "C"),
        metavar="A/B/C",
        help="只跑指定桶（可重复；默认全部）",
    )
    controls_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验任务/快照并打印自检计划，不写 run 目录",
    )

    judge_parser = eval_sub.add_parser(
        "judge",
        help="LLM judge 校准：≥20 条人工标注样本，算 Cohen's κ 并写校准文件",
    )
    judge_parser.add_argument(
        "--tasks",
        metavar="目录",
        help="judge 任务目录（默认仓库根下的 evals/judge-tasks）",
    )
    judge_parser.add_argument(
        "--task",
        action="append",
        metavar="ID",
        help="只校准指定任务 id（可重复；默认全部声明了 judge 的任务）",
    )
    judge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验样本数量/路径并打印计划，不调用模型、不写校准文件",
    )

    attribute_parser = eval_sub.add_parser(
        "attribute",
        help="失败归因准确率：用人工标注样本跑五类分类器，写混淆矩阵报告",
    )
    attribute_parser.add_argument(
        "--samples",
        metavar="文件",
        help="标注样本 JSONL（默认仓库根下的 evals/attribution/labels.jsonl）",
    )
    attribute_parser.add_argument(
        "--out",
        metavar="目录",
        help="报告输出目录（默认样本文件所在目录）",
    )
    attribute_parser.add_argument(
        "--min-accuracy",
        type=float,
        default=DEFAULT_MIN_ACCURACY,
        metavar="比例",
        help=f"达标阈值 0–1（默认 {DEFAULT_MIN_ACCURACY}）",
    )
    attribute_parser.add_argument(
        "--run",
        action="append",
        metavar="目录",
        help="跑数目录或 runs 根目录（可重复；给了才汇总真实失败分布）",
    )
    attribute_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验样本类别/数量并打印计划，不跑分类、不写报告",
    )

    regression_parser = eval_sub.add_parser(
        "regression",
        help="失败案例 → 回归任务：生成可被 eval run 直接读取的 TOML",
    )
    regression_parser.add_argument(
        "--run",
        required=True,
        metavar="目录",
        help="跑数目录（含 report.json）",
    )
    regression_parser.add_argument(
        "--task",
        required=True,
        metavar="ID",
        help="失败案例的任务 id",
    )
    regression_parser.add_argument(
        "--repetition",
        type=int,
        default=1,
        metavar="N",
        help="失败案例的重复序号（默认 1）",
    )
    regression_parser.add_argument(
        "--tasks",
        metavar="目录",
        help="原任务定义目录（默认搜索 evals/tasks 与 evals/judge-tasks）",
    )
    regression_parser.add_argument(
        "--out",
        metavar="文件",
        help="输出 TOML（默认 evals/regressions/<新 id>.toml）",
    )
    regression_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将生成的任务摘要，不写文件",
    )

    cost_parser = eval_sub.add_parser(
        "cost",
        help="成本曲线（E2）：从会话 usage 重算缓存与 off-peak 的实际/反事实成本",
    )
    cost_parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="目录",
        help="跑数目录（可重复；目录里要有 report.json）",
    )
    cost_parser.add_argument(
        "--out",
        metavar="目录",
        help="报告输出目录（默认仓库根下的 evals/cost）",
    )
    cost_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验 run/report.json 并打印调用数，不写报告",
    )

    defense_parser = eval_sub.add_parser(
        "defense",
        help="防御有效性（E5）：死循环剧本拦截、注入任务拦截与正常任务误报审计",
    )
    defense_parser.add_argument(
        "--run",
        action="append",
        metavar="目录",
        help="跑数目录或 runs 根目录（可重复；默认仓库根下的 evals/runs）",
    )
    defense_parser.add_argument(
        "--out",
        metavar="目录",
        help="报告输出目录（默认仓库根下的 evals/defense）",
    )
    defense_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印剧本与 run 计数，不执行剧本、不写报告",
    )
    return parser


def _short(text: str, limit: int = 40) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def _clock(iso: str, *, date: bool = True) -> str:
    """ISO 时间戳 → 本地时间显示（解析不了就原样返回：列表不该被一条坏记录弄崩）。"""
    try:
        moment = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    return moment.strftime("%Y-%m-%d %H:%M" if date else "%H:%M")


def _warn_skipped(skipped: list[str]) -> None:
    """损坏的会话不进列表，但要让用户知道它们被跳过了（不静默吞）。"""
    for note in skipped:
        print(f"警告：跳过损坏的会话——{note}", file=sys.stderr)


def _fail(exc: Exception) -> int:
    """领域异常 → "错误：…"+退出码（三个入口共用一处）。

    2 = 用法/配置错（改改再来：配置缺失、序号越界等）；1 = 运行期错（网络、无会话可恢复、
    管道提前关闭、目录不可写等）。
    """
    print(f"错误：{exc}", file=sys.stderr)
    return 2 if isinstance(exc, (ConfigError, SessionError)) else 1


def _list_sessions() -> int:
    """--resume（无序号）：列出本项目可恢复的会话/分支。只读查询，不需要密钥。"""
    items, skipped = list_resumable(Path.cwd())
    _warn_skipped(skipped)
    if not items:
        print("本项目还没有可恢复的会话。")
        return 0
    print(f"可恢复的会话/分支（{len(items)} 个）：")
    for index, item in enumerate(items, 1):
        marker = (
            f"  ⎇ 分支（fork 于 {_clock(item.fork_at, date=False)}）"
            if item.fork_at
            else ""
        )
        print(
            f"  {index}. {_clock(item.timestamp)}  {item.path.name}  "
            f"{item.messages} 条消息{marker}  「{_short(item.title)}」"
        )
    print("`--resume <序号>` 恢复到指定分支；`--continue` 回到最近活动的一条。")
    return 0


def _run_export(args: argparse.Namespace) -> int:
    """export 子命令：会话记录 → 单文件 HTML / Markdown。只读查询，不需要密钥。"""
    if args.html is None and args.md is None:
        print(
            "错误：export 需要 --html 或 --md（用法：codelotte export --html [序号]）",
            file=sys.stderr,
        )
        return 2
    to_html = args.html is not None
    selector = args.html if to_html else args.md
    assert selector is not None  # 上一段已拦"两个都没给"，这里只为类型收窄
    suffix = "html" if to_html else "md"
    flag = "--html" if to_html else "--md"
    cwd = Path.cwd()
    try:
        if selector == "":
            path = latest_session_path(cwd)
            if path is None:
                print(
                    f"错误：没有可导出的会话：{cwd} 下没有历史会话记录", file=sys.stderr
                )
                return 2  # 与"没有第 N 个"同码：查无此物（审查修正：两条选择路径退出码统一）
            leaf_id: str | None = None
        else:
            try:
                index = int(selector)
            except ValueError:
                print(
                    f"错误：{flag} 的序号要是一个数字（给了 {selector!r}）",
                    file=sys.stderr,
                )
                return 2
            items, skipped = list_resumable(cwd)
            _warn_skipped(skipped)
            if not 1 <= index <= len(items):
                raise SessionError(
                    f"没有第 {index} 个可恢复的会话（共 {len(items)} 个）"
                )
            item = items[index - 1]
            path, leaf_id = item.path, item.leaf_id
        try:
            entries = load_branch(path, leaf_id)
        except (
            json.JSONDecodeError
        ) as exc:  # 坏文件给可读错误，不裸 traceback（审查修正）
            print(
                f"错误：会话文件有坏行，读不动（{path.name}）：{exc}", file=sys.stderr
            )
            return 1
        renderer = render_session_html if to_html else render_session_markdown
        rendered = renderer(entries, load_catalog(), session_name=path.name)
        output = Path(args.output) if args.output else Path(f"{path.stem}.{suffix}")
        with output.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(rendered)
    except (ConfigError, SessionError, OSError) as exc:
        return _fail(exc)
    print(f"已导出：{output}（{len(entries)} 条记录）")
    return 0


def _parse_cli_rules(
    allow: Sequence[str], ask: Sequence[str], deny: Sequence[str]
) -> list[Rule]:
    """--allow/--ask/--deny 的规则文本 → Rule（畸形即用法错，由 main 统一转成退出码 2）。"""
    rules: list[Rule] = []
    for verdict, flag, texts in (
        (ALLOW, "--allow", allow),
        (ASK, "--ask", ask),
        (DENY, "--deny", deny),
    ):
        for text in texts:
            try:
                rules.append(parse_rule(text, verdict, "cli"))
            except ValueError as exc:
                raise SessionError(f"{flag} 的参数不对：{exc}") from exc
    return rules


def _client_from_spec(spec: ModelSpec) -> OpenAICompletionsClient:
    """按最终模型参数建客户端（-p/TUI 与压缩回归实验共用同一构造）。"""
    return OpenAICompletionsClient(
        base_url=spec.base_url,
        api_key=spec.api_key,
        model=spec.id,
        max_tokens=spec.max_output_tokens,  # 单次输出上限（用户可下调，随包默认封顶）
        reasoning_effort=spec.reasoning_effort,  # 思考开关与强度（none 关闭；展示总是跟随）
    )


def _build_agent(
    *,
    resume: bool = False,
    resume_index: int | None = None,
    fork_from_end: int | None = None,
    rules: Sequence[Rule] = (),
    settings: Settings | None = None,
    no_sandbox: bool = False,
) -> tuple[AgentLoop, ModelSpec, Executor]:
    """装配一次真实运行的循环——无头与 TUI 共用这一处。

    执行器按 --no-sandbox 选择：默认 DockerExecutor（每会话一个长驻容器），
    显式逃生门才退回 LocalExecutor；调用方负责在会话结束时 close 执行器。

    先读配置、后建会话文件：配置缺失（如没密钥）不得留下"只有会话头的空文件"，
    否则 --continue 按 mtime 会挑中它，把真实历史跳过。

    运行参数（端点/密钥/模型）只从用户级 models.json 读（models.resolve）；
    随包目录只出计费事实与展示/上限默认值。返回循环、最终采用的模型参数（TUI 用展示名/窗口）
    与执行器（生命周期由调用方收尾）。

    resume_index 给出时恢复指定分支；fork_from_end 可与其组合（在选中的分支上再分岔）。
    """
    resolved = (
        settings if settings is not None else load_settings()
    )  # 未传入时读真实用户级配置
    catalog = (
        load_catalog()
    )  # 价目/峰谷/节假日 + 展示名/上限默认值；坏目录在这里以 ConfigError 报出
    spec = resolve(
        resolved, catalog
    )  # 用户级 models.json 的唯一来源 + 随包默认值/上限校验
    permissions = build_permission_layer(
        Path.cwd(), cli_rules=rules
    )  # 票据 09：CLI 规则 + 项目/用户规则文件（未信任的项目规则被忽略，notices 里有说明）
    client = _client_from_spec(spec)
    executor: Executor = LocalExecutor() if no_sandbox else DockerExecutor()
    # 死循环三层防御阈值（票据 11）：settings.json 覆盖 + guardrails 的默认值
    guardrail_limits = GuardrailLimits.from_settings(resolved)
    # 压缩双阈值（票据 12）：settings.json 覆盖 + compaction 的默认值
    compaction_limits = CompactionLimits.from_settings(resolved)
    cwd = Path.cwd()
    if resume_index is not None:
        items, skipped = list_resumable(cwd)
        _warn_skipped(skipped)
        if not 1 <= resume_index <= len(items):
            raise SessionError(
                f"没有第 {resume_index} 个可恢复的会话（共 {len(items)} 个）"
            )
        item = items[resume_index - 1]
        if fork_from_end is not None:
            store, messages = fork_at(
                item.path, leaf_id=item.leaf_id, from_end=fork_from_end
            )
        else:
            store, messages = open_at(item.path, leaf_id=item.leaf_id)
    elif fork_from_end is not None:
        store, messages = fork_session(cwd, from_end=fork_from_end)
    else:
        store, messages = open_session(cwd, resume=resume)
    loop = AgentLoop(
        client=client,
        tools=default_tools(executor, command_timeout=resolved.command_timeout),
        store=store,
        model=spec.id,
        env=executor.env,  # 未知工具的兜底；bash 自己带执行器 env（见 Tool.exec_env）
        messages=messages,
        catalog=catalog,
        permissions=permissions,
        guardrail_limits=guardrail_limits,
        compaction_limits=compaction_limits,
        context_window=spec.context_window,  # 与 TUI 状态栏同源（票据 12 预置决策）
    )
    return loop, spec, executor


def _run_prompt(
    prompt: str,
    *,
    resume: bool = False,
    resume_index: int | None = None,
    fork_from_end: int | None = None,
    rules: Sequence[Rule] = (),
    settings: Settings | None = None,
    no_sandbox: bool = False,
) -> int:
    """一次性执行。思考由模型条目的 reasoning_effort 决定：none 关闭（无思考内容、无展示），
    其余档位开启——开启时思考内容总是既落盘又展示（走 stderr），没有单独的展示开关。"""
    try:
        loop, _spec, executor = _build_agent(
            resume=resume,
            resume_index=resume_index,
            fork_from_end=fork_from_end,
            rules=rules,
            settings=settings,
            no_sandbox=no_sandbox,
        )
        for (
            note
        ) in loop.permissions.notices:  # 权限层加载提示（含未信任项目规则被忽略）
            print(f"提示：{note}", file=sys.stderr)
        try:
            return asyncio.run(run_once(loop, prompt))
        finally:
            asyncio.run(executor.close())  # 容器生命周期跟随会话：跑完就清
    except KeyboardInterrupt:
        print("已中断（会话已保存，可 --continue 恢复）", file=sys.stderr)
        return 130
    except (ProviderError, ConfigError, SessionError, OSError) as exc:
        # OSError 覆盖：管道提前关闭（`codelotte ... | head`）、无会话可恢复、目录不可写等
        return _fail(exc)


def _run_tui(
    *,
    resume: bool,
    resume_index: int | None = None,
    fork_from_end: int | None = None,
    rules: Sequence[Rule] = (),
    notices: Sequence[str] = (),
    settings: Settings | None = None,
    no_sandbox: bool = False,
) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            "错误：交互界面需要真实终端（当前 stdin/stdout 不是 tty）。"
            "一次性任务请用 -p；恢复会话可加 --continue/--resume。",
            file=sys.stderr,
        )
        return 2
    try:
        from codelotte.tui import TuiApp  # 延迟导入：无头模式不必加载 Textual

        loop, spec, executor = _build_agent(
            resume=resume,
            resume_index=resume_index,
            fork_from_end=fork_from_end,
            rules=rules,
            settings=settings,
            no_sandbox=no_sandbox,
        )
        history = load_branch(loop.session_path, loop.leaf_id)  # 只回放活动分支
        try:
            TuiApp(
                agent=loop,
                model=spec.name,  # 展示名（随包目录给的名字，用户级可覆盖）
                reasoning_effort=spec.reasoning_effort,  # 启动横幅：思考档位
                cwd=str(Path.cwd()),  # 启动横幅：当前工作目录
                sandbox=executor.env,  # 启动横幅：docker / local
                context_window=spec.context_window,  # 状态栏上下文占用百分比的分母
                startup_notices=notices,  # 启动提示（如更新内容）
                history=history,
            ).run()
        finally:
            asyncio.run(executor.close())  # 容器生命周期跟随会话：退出就清
        print_session_invoice(loop)  # 会话结束汇总：与 -p 同一口径（票据 07）
        return 0
    except (ConfigError, SessionError, OSError) as exc:
        return _fail(exc)


def _run_perm_write(args: argparse.Namespace) -> int:
    """allow/ask/deny 子命令：把规则永久写进权限文件（默认用户级；--project 写项目级）。

    写的是 JSON 文件（`{"allow": [...], "ask": [...], "deny": [...]}`）：读-改-写、
    不重复追加、保留文件里已有的其他键；文件损坏时报错退出，绝不覆盖毁掉手写内容。
    """
    cwd = Path.cwd()
    home = Path.home()
    path = (cwd / RULES_FILE) if args.project else (home / RULES_FILE)
    verdict: str = args.verdict
    try:
        for text in args.rules:
            parse_rule(text, verdict, "cli")  # 先全部校验：坏规则一条都不写
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    for text in args.rules:
        print(f"将向 {path} 追加：{verdict} {text}")
    try:
        added, existing = append_rules(path, verdict, args.rules)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    for text in existing:
        print(f"已存在，跳过：{verdict} {text}")
    print(f"完成：新增 {len(added)} 条（{path}）")
    if args.project and added and not is_trusted(cwd, home / TRUST_FILE):
        print("提示：项目级规则需要 `codelotte trust` 确认一次后才生效。")
    return 0


def _run_trust() -> int:
    """trust 子命令：显示本项目的权限规则并做一次信任确认（写用户级信任表）。"""
    cwd = Path.cwd()
    home = Path.home()
    trust_file = home / TRUST_FILE
    project_path = cwd / RULES_FILE
    if not project_path.is_file():
        print(f"本项目没有权限规则文件（{project_path}），无需信任。")
        return 0
    if is_trusted(cwd, trust_file):
        print(f"已信任过：{cwd}（信任表：{trust_file}）")
        return 0
    print(f"将信任 {cwd} 的项目级权限规则（{project_path}）：\n")
    print(project_path.read_text(encoding="utf-8").rstrip())
    print()
    try:
        answer = input("信任并让它生效？[y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() in ("y", "yes"):
        trust_project(cwd, trust_file)
        print(f"已信任（记录在 {trust_file}）；项目级规则下次启动生效。")
        return 0
    print("未信任——项目级规则继续被忽略。")
    return 1


def _parse_k_values(text: str) -> tuple[int, ...]:
    """`--k 0,1,3,5` → 升序去重前的校验（空项/负数/重复都算用法错误）。"""
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise ConfigError("--k 里有空项（示例：--k 0,1,3,5）")
        try:
            value = int(part)
        except ValueError as exc:
            raise ConfigError(f"--k 的每一项都要是非负整数（给了 {part!r}）") from exc
        if value < 0:
            raise ConfigError(f"--k 的每一项都要是非负整数（给了 {value}）")
        values.append(value)
    if len(set(values)) != len(values):
        raise ConfigError(f"--k 不能有重复值（给了 {text!r}）")
    return tuple(sorted(values))


_COMPACTION_STRATEGIES = ("minimal", "wide")
_COMPACTION_TEMPLATES = ("seven", "compact")


def _compaction_combos(args: argparse.Namespace) -> tuple[tuple[str, str], ...]:
    """解析压缩回归的策略/模板组合（--combo 精确指定，或两个列表的笛卡尔积）。"""
    if args.combo:
        if args.strategy or args.template:
            raise ConfigError("--combo 不能和 --strategy/--template 同时使用")
        combos: list[tuple[str, str]] = []
        for raw in args.combo:
            strategy, separator, template = raw.partition(":")
            if not separator:
                raise ConfigError(f"--combo 要写成 策略:模板（给了 {raw!r}）")
            strategy = strategy.strip()
            template = template.strip()
            if strategy not in _COMPACTION_STRATEGIES:
                raise ConfigError(
                    f"--combo 的策略只能是 {_COMPACTION_STRATEGIES}（给了 {strategy!r}）"
                )
            if template not in _COMPACTION_TEMPLATES:
                raise ConfigError(
                    f"--combo 的模板只能是 {_COMPACTION_TEMPLATES}（给了 {template!r}）"
                )
            pair = (strategy, template)
            if pair not in combos:
                combos.append(pair)
        return tuple(combos)
    strategies = args.strategy or ["minimal"]
    templates = args.template or ["seven"]
    return tuple(dict.fromkeys(
        (strategy, template)
        for strategy in strategies
        for template in templates
    ))


def _ensure_docker_available() -> None:
    """默认沙箱的预检：Docker 不可用时一次说清楚，而不是 27 条案例各失败一次。"""
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(
            f"Docker 沙箱不可用：{exc}；可加 --no-sandbox（命令将直接在宿主机执行，风险自负）"
        ) from exc
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[-1] if lines else "docker version 失败"
        raise ConfigError(
            f"Docker 沙箱不可用：{detail}；可加 --no-sandbox（命令将直接在宿主机执行，风险自负）"
        )


def _eval_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    """评测命令共用的路径：仓库根、任务目录、跑数根目录。"""
    repo_root = find_repo_root(Path.cwd())
    tasks_dir = Path(args.tasks) if args.tasks else repo_root / "evals" / "tasks"
    out_dir = Path(args.out) if args.out else repo_root / "evals" / "runs"
    return repo_root, tasks_dir, out_dir


def _print_eval_task_plan(
    tasks: Sequence[Task], snapshot_refs: dict[str, str]
) -> None:
    """dry-run 共用的任务清单：任务、桶、超时/调用上限与快照 SHA。"""
    for task in tasks:
        snapshot = (
            f"，快照 {task.snapshot.ref} → {snapshot_refs[task.id]}"
            if task.snapshot is not None
            else ""
        )
        print(
            f"- {task.id}（{task.bucket} 桶，超时 {task.timeout_seconds:g}s，"
            f"最多 {task.max_model_calls} 次模型调用{snapshot}）"
        )


def _judge_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """judge 校准的路径：仓库根与 judge 任务目录（默认 evals/judge-tasks）。"""
    repo_root = find_repo_root(Path.cwd())
    tasks_dir = (
        Path(args.tasks) if args.tasks else repo_root / "evals" / "judge-tasks"
    )
    return repo_root, tasks_dir


def _select_eval_tasks(
    tasks: Sequence[Task],
    *,
    task_ids: Sequence[str] | None,
    buckets: Sequence[str] | None,
) -> list[Task]:
    """按 --task / --bucket 过滤；筛选后为空或 id 不存在都是用法错。"""
    selected = list(tasks)
    if task_ids:
        wanted = set(task_ids)
        available = {task.id for task in selected}
        missing = wanted - available
        if missing:
            raise TaskFileError(
                f"没有这些任务 id：{sorted(missing)}；可选：{sorted(available)}"
            )
        selected = [task for task in selected if task.id in wanted]
    if buckets:
        wanted_buckets = set(buckets)
        selected = [task for task in selected if task.bucket in wanted_buckets]
    if not selected:
        raise TaskFileError("筛选后没有任务；检查 --task / --bucket")
    return selected


@dataclass(frozen=True)
class _EvalRuntime:
    """两类评测命令共用的运行参数（模型配置、限额、执行器、run id、命令）。"""

    catalog: Catalog
    spec: ModelSpec
    compaction_limits: CompactionLimits
    guardrail_limits: GuardrailLimits
    executor_factory: Callable[[], Executor]
    isolation: str
    run_id: str
    command: str
    progress: Callable[[str], None]


def _eval_runtime(
    args: argparse.Namespace,
    *,
    settings: Settings,
    argv: Sequence[str],
    repo_root: Path,
) -> _EvalRuntime:
    catalog = load_catalog()
    spec = resolve(settings, catalog)
    compaction_limits = CompactionLimits.from_settings(settings)
    guardrail_limits = GuardrailLimits.from_settings(settings)
    if args.no_sandbox:
        print(SANDBOX_OFF_WARNING, file=sys.stderr)
        executor_factory: Callable[[], Executor] = LocalExecutor
        isolation = "local"
    else:
        _ensure_docker_available()
        executor_factory = DockerExecutor
        isolation = "docker"

    def progress(line: str) -> None:
        print(f"[eval] {line}", file=sys.stderr, flush=True)

    return _EvalRuntime(
        catalog=catalog,
        spec=spec,
        compaction_limits=compaction_limits,
        guardrail_limits=guardrail_limits,
        executor_factory=executor_factory,
        isolation=isolation,
        run_id=make_run_id(current_git_ref(repo_root)),
        command="codelotte " + shlex.join(list(argv)),
        progress=progress,
    )


def _run_eval_judge(
    args: argparse.Namespace, *, settings: Settings
) -> int:
    """用人工标注样本校准 LLM judge；写 calibration.json/.md 并报告 κ。"""
    try:
        repo_root, tasks_dir = _judge_paths(args)
        tasks = load_tasks(tasks_dir)
        if args.task:
            selected = _select_eval_tasks(
                tasks, task_ids=args.task, buckets=None
            )
        else:
            selected = [task for task in tasks if task.verifier.judge is not None]
        if not selected:
            raise TaskFileError(
                f"{tasks_dir} 里没有声明 [verifier.judge] 的任务；"
                "judge 任务应放在 evals/judge-tasks"
            )
        missing = [task.id for task in selected if task.verifier.judge is None]
        if missing:
            raise TaskFileError(f"这些任务没有声明 judge：{missing}")
        plans = []
        for task in selected:
            judge = task.verifier.judge
            assert judge is not None
            if judge.samples is None or judge.calibration is None:
                raise TaskFileError(
                    f"{task.id} 的 [verifier.judge] 缺少 samples 或 calibration 路径"
                )
            samples_path = (repo_root / judge.samples).resolve()
            calibration_path = (repo_root / judge.calibration).resolve()
            samples = load_samples(samples_path)
            if len(samples) < MIN_CALIBRATION_SAMPLES:
                raise JudgeError(
                    f"{task.id} 的校准样本只有 {len(samples)} 条，"
                    f"至少需要 {MIN_CALIBRATION_SAMPLES} 条"
                )
            plans.append((task, judge, samples, samples_path, calibration_path))
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            for task, judge, samples, samples_path, calibration_path in plans:
                print(
                    f"- {task.id}：{len(judge.dimensions)} 个维度，"
                    f"{len(samples)} 条样本（{samples_path}）→ {calibration_path}"
                )
            print("dry-run：样本数量/路径校验通过，未调用模型、未写校准文件。")
            return 0
        catalog = load_catalog()
        spec = resolve(settings, catalog)
        context = JudgeContext(
            client_factory=lambda: _client_from_spec(spec),
            model=spec.id,
            catalog=catalog,
        )

        def progress(line: str) -> None:
            print(f"[judge] {line}", file=sys.stderr, flush=True)

        all_reliable = True
        for task, judge, samples, samples_path, calibration_path in plans:
            print(f"[judge] == {task.id} ==", file=sys.stderr, flush=True)
            run = asyncio.run(
                calibrate(
                    context,
                    instruction=task.instruction,
                    judge=judge,
                    samples=samples,
                    progress=progress,
                )
            )
            write_calibration(
                calibration_path,
                task_id=task.id,
                instruction=task.instruction,
                judge=judge,
                run=run,
                labels_path=samples_path,
            )
            calibration = load_calibration(calibration_path)
            reliable, warning = judge_reliability(judge, calibration)
            all_reliable = all_reliable and reliable
            kappa = "—" if run.kappa is None else f"{run.kappa:.3f}"
            print(
                f"[judge] {task.id}：κ={kappa}，一致率={run.agreement:.1%}，"
                f"样本={run.samples}，成本=¥{run.cost:.6f}；"
                f"{'✅ 可靠' if reliable else '⚠ ' + (warning or '不可靠')}",
                file=sys.stderr,
            )
            print(calibration_path)
        return 0 if all_reliable else 1
    except (TaskFileError, ConfigError, JudgeError, ValueError, OSError) as exc:
        return _fail(exc)


def _judge_context(runtime: _EvalRuntime) -> JudgeContext:
    """评测运行共用的 judge 资源（与 agent 同模型，独立 client 实例）。"""
    return JudgeContext(
        client_factory=lambda: _client_from_spec(runtime.spec),
        model=runtime.spec.id,
        catalog=runtime.catalog,
    )


def _run_eval_attribute(args: argparse.Namespace) -> int:
    """用人工标注的失败轨迹跑分类器，写准确率/混淆矩阵报告。"""
    try:
        repo_root = find_repo_root(Path.cwd())
        samples_path = (
            Path(args.samples)
            if args.samples
            else repo_root / "evals" / "attribution" / "labels.jsonl"
        )
        if not 0 <= args.min_accuracy <= 1:
            raise AttributionError(
                f"--min-accuracy 要在 0–1 之间（给了 {args.min_accuracy}）"
            )
        samples = load_attribution_samples(samples_path)
        if len(samples) < MIN_CORPUS_SAMPLES:
            raise AttributionError(
                f"归因样本只有 {len(samples)} 条，至少需要 {MIN_CORPUS_SAMPLES} 条"
            )
        counts: dict[str, int] = {failure_class: 0 for failure_class in FAILURE_CLASSES}
        for sample in samples:
            counts[sample.human_class] += 1
        missing = [name for name, count in counts.items() if count == 0]
        if missing:
            raise AttributionError(
                f"归因样本缺少这些类别：{missing}（五类都要有样本）"
            )
        distribution = None
        if args.run:
            distribution = collect_failure_distribution(
                [Path(item) for item in args.run]
            )
        if args.dry_run:
            print(f"样本文件：{samples_path}")
            for failure_class in FAILURE_CLASSES:
                print(
                    f"- {FAILURE_LABELS[failure_class]}（{failure_class}）："
                    f"{counts[failure_class]} 条"
                )
            if distribution is not None:
                print(
                    f"失败分布来源：{len(distribution.runs)} 个 run，"
                    f"{distribution.codelotte_failures} 条 codelotte 失败"
                    f"（未归因 {distribution.unattributed}），"
                    f"非 codelotte {distribution.non_codelotte} 条"
                )
            print("dry-run：样本类别/数量校验通过，未跑分类、未写报告。")
            return 0
        run = evaluate_corpus(samples, base_dir=repo_root)
        out_dir = Path(args.out) if args.out else samples_path.parent
        report_path = build_attribution_report(
            out_dir,
            run,
            samples_path=samples_path,
            min_accuracy=args.min_accuracy,
            distribution=distribution,
        )
        draft = run.has_draft_labels
        passed = run.is_acceptable(args.min_accuracy)
        print(
            f"[attribute] 准确率 {run.correct}/{run.total}（{run.accuracy:.1%}），"
            f"宏观 F1 {run.macro_f1:.3f}，阈值 {args.min_accuracy:.0%}；"
            f"{'⚠ 草稿标注' if draft else '✅ 已复核'}"
        )
        if distribution is not None:
            print(
                f"[attribute] 失败分布：{distribution.codelotte_failures} 条 codelotte 失败"
                f"（未归因 {distribution.unattributed}），"
                f"非 codelotte {distribution.non_codelotte} 条"
            )
        print(report_path)
        return 0 if passed else 1
    except (AttributionError, ValueError, OSError) as exc:
        return _fail(exc)


def _find_source_task(
    task_id: str, directories: Sequence[Path]
) -> tuple[Path, Task, set[str]]:
    """在给定目录里按 id 找原任务；返回 (路径, 任务, 已有 id 集合)。"""
    index: dict[str, tuple[Path, Task]] = {}
    for directory in directories:
        if not directory.is_dir():
            raise RegressionTaskError(f"任务目录不存在：{directory}")
        for path in sorted(directory.glob("*.toml")):
            task = load_task(path)
            index.setdefault(task.id, (path, task))
    if task_id not in index:
        raise RegressionTaskError(
            f"找不到任务 {task_id!r} 的原始定义；可选：{sorted(index)}"
        )
    path, task = index[task_id]
    return path, task, set(index)


def _run_eval_regression(args: argparse.Namespace) -> int:
    """把一条失败案例转成可跑的回归任务（保留原 setup/verifier，只换 id）。"""
    try:
        if args.repetition < 1:
            raise RegressionTaskError(
                f"--repetition 要 ≥1（给了 {args.repetition}）"
            )
        repo_root = find_repo_root(Path.cwd())
        run_dir = Path(args.run)
        report_path = run_dir / "report.json"
        if not report_path.is_file():
            raise RegressionTaskError(f"跑数目录里没有 report.json：{run_dir}")
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RegressionTaskError(
                f"report.json 不是合法 JSON：{report_path}（{exc}）"
            ) from exc
        cases = payload.get("cases") if isinstance(payload, dict) else None
        if not isinstance(cases, list):
            raise RegressionTaskError(f"report.json 缺少 cases 数组：{report_path}")
        case = next(
            (
                item
                for item in cases
                if isinstance(item, dict)
                and item.get("task_id") == args.task
                and item.get("repetition") == args.repetition
            ),
            None,
        )
        if case is None:
            raise RegressionTaskError(
                f"报表里没有案例 {args.task} r{args.repetition}"
            )
        if case.get("passed") is True:
            raise RegressionTaskError(
                f"{args.task} r{args.repetition} 是通过的案例；回归任务只从失败生成"
            )

        directories = (
            [Path(args.tasks)]
            if args.tasks
            else [repo_root / "evals" / "tasks", repo_root / "evals" / "judge-tasks"]
        )
        source_path, source, existing_ids = _find_source_task(args.task, directories)
        meta = payload.get("meta")
        regressions_dir = repo_root / "evals" / "regressions"
        if regressions_dir.is_dir():
            for path in sorted(regressions_dir.glob("*.toml")):
                existing_ids.add(load_task(path).id)
        new_id = next_regression_id(source.id, existing_ids)
        out_path = (
            Path(args.out) if args.out else regressions_dir / f"{new_id}.toml"
        )

        attribution: Attribution | None = None
        if case.get("failure_class"):
            attribution = Attribution(
                failure_class=str(case["failure_class"]),
                confidence=str(case.get("failure_confidence") or "low"),
                evidence=str(case.get("failure_evidence") or ""),
                signals=tuple(case.get("failure_signals") or ()),
            )
        elif case.get("harness", "codelotte") == "codelotte":
            attribution = classify_failure(
                case.get("session_path"),
                error=case.get("error"),
                verifier_detail=str(case.get("verifier_detail") or ""),
                flagged=bool(case.get("flagged")),
            )
        detail = str(case.get("verifier_detail") or case.get("error") or "")
        run_id = (
            str(meta.get("run_id") or run_dir.name)
            if isinstance(meta, dict)
            else run_dir.name
        )
        text = build_regression_task(
            source_path,
            source_id=source.id,
            new_id=new_id,
            run_id=run_id,
            repetition=args.repetition,
            attribution=attribution,
            detail=detail,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        if attribution is None:
            attribution_text = "归因不可用（非 codelotte 轨迹）"
        else:
            attribution_text = (
                f"{FAILURE_LABELS.get(attribution.failure_class, attribution.failure_class)}"
                f"（{attribution.confidence}）：{attribution.evidence}"
            )
        if args.dry_run:
            print(f"[regression] 将生成 {new_id}")
            print(f"- 来源：run {run_id} / {source.id} r{args.repetition}")
            print(f"- 归因：{attribution_text}")
            print(f"- 输出：{out_path}")
            print("dry-run：未写文件。")
            return 0
        write_regression_task(out_path, text)
        load_task(out_path)  # 写盘后再校验：生成的文件必须能被 eval run 直接读取
        print(f"[regression] 来源 run {run_id} / {source.id} r{args.repetition}")
        print(f"[regression] 归因：{attribution_text}")
        print(out_path)
        return 0
    except (
        AttributionError,
        RegressionTaskError,
        TaskFileError,
        ValueError,
        OSError,
    ) as exc:
        return _fail(exc)


def _run_eval_cost(args: argparse.Namespace, *, argv: Sequence[str]) -> int:
    """E2 成本曲线：读 run 的会话 usage，重算缓存/off-peak 的实际与反事实成本。"""
    try:
        repo_root = find_repo_root(Path.cwd())
        run_dirs = [Path(raw) for raw in args.run]
        seen: set[Path] = set()
        for run_dir in run_dirs:
            if not (run_dir / "report.json").is_file():
                raise ConfigError(f"跑数目录里没有 report.json：{run_dir}")
            resolved = run_dir.resolve()
            if resolved in seen:
                raise ConfigError(f"重复的 run 目录：{run_dir}")
            seen.add(resolved)
        catalog = load_catalog()
        runs = [analyze_run(catalog, run_dir) for run_dir in run_dirs]
        if args.dry_run:
            for run in runs:
                print(
                    f"- {run.run_id}：{run.cases} 案例 / {run.calls} 调用，"
                    f"缺 usage 会话 {run.missing_cases} 条"
                )
            print("dry-run：run 校验通过，未写成本报告。")
            return 0
        out_dir = Path(args.out) if args.out else repo_root / "evals" / "cost"
        command = "codelotte " + shlex.join(list(argv))
        path = write_cost_report(out_dir, runs, catalog=catalog, command=command)
        for run in runs:
            rate = "—" if run.cache_hit_rate is None else f"{run.cache_hit_rate:.1%}"
            print(
                f"[cost] {run.run_id}：{run.calls} 调用，命中率 {rate}，"
                f"实际 {format_money(run.actual_cost, catalog.currency)}，"
                f"无缓存 {format_money(run.no_cache_cost, catalog.currency)}，"
                f"全峰价 {format_money(run.peak_cost, catalog.currency)}",
                file=sys.stderr,
            )
        print(path)
        return 0
    except (ConfigError, ValueError, OSError) as exc:
        return _fail(exc)


def _run_eval_defense(args: argparse.Namespace) -> int:
    """E5 防御有效性：离线剧本 + 真实跑数的注入拦截/误报审计。"""
    try:
        repo_root = find_repo_root(Path.cwd())
        run_dirs = (
            [Path(raw) for raw in args.run]
            if args.run
            else [repo_root / "evals" / "runs"]
        )
        for run_dir in run_dirs:
            if not run_dir.exists():
                raise DefenseError(f"跑数目录不存在：{run_dir}")
        if args.dry_run:
            print("死循环剧本：")
            for name, kind, expected in scenario_plan():
                goal = " + ".join(expected) if expected else "无拦截"
                print(f"- {name}（{kind}）：{goal}")
            pressure = collect_loop_pressure_results(run_dirs)
            injection = collect_injection_results(run_dirs)
            audit = audit_false_positives(run_dirs)
            print(
                f"跑数：死循环压力 {pressure.attempts} 条，"
                f"注入案例 {injection.attempts}；正常任务 {audit.normal_cases}"
            )
            print("dry-run：未执行剧本、未写报告。")
            return 0
        out_dir = (
            Path(args.out) if args.out else repo_root / "evals" / "defense"
        )
        report = analyze_defense(
            run_dirs=run_dirs, session_dir=out_dir / "sessions"
        )
        path = write_defense_report(out_dir, report)
        print(defense_summary(report))
        print(path)
        return 0 if report.passed else 1
    except (DefenseError, ValueError, OSError) as exc:
        return _fail(exc)


def _run_eval_compaction(
    args: argparse.Namespace, *, settings: Settings, argv: Sequence[str]
) -> int:
    """一条命令跑完整轮压缩回归并落报表；返回报表路径（stdout）与进度（stderr）。"""
    try:
        k_values = _parse_k_values(args.k)
        combos = _compaction_combos(args)
        if args.repeat < 1:
            raise ConfigError(f"--repeat 要 ≥1（给了 {args.repeat}）")
        repo_root, tasks_dir, out_dir = _eval_paths(args)
        tasks = _select_eval_tasks(
            load_tasks(tasks_dir), task_ids=args.task, buckets=None
        )
        missing_checkpoints = [task.id for task in tasks if not task.checkpoints]
        if missing_checkpoints:
            raise TaskFileError(
                "压缩回归需要 checkpoint 问题集，这些任务没有："
                f"{missing_checkpoints}；通用测评请用 `codelotte eval run`"
            )
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            for task in tasks:
                print(
                    f"- {task.id}（{task.bucket} 桶，{len(task.checkpoints)} 个 checkpoint，"
                    f"超时 {task.timeout_seconds:g}s，最多 {task.max_model_calls} 次模型调用）"
                )
            cases = len(tasks) * len(k_values) * len(combos) * args.repeat
            combo_text = ", ".join(f"{s}/{t}" for s, t in combos)
            print(
                f"计划：{len(tasks)} 任务 × {len(k_values)} 个 k × "
                f"{len(combos)} 个组合 × {args.repeat} 次重复 = {cases} 条案例；"
                f"k={','.join(str(k) for k in k_values)}；组合：{combo_text}"
            )
            print("dry-run：任务文件校验通过，未调用模型、未创建 run 目录。")
            return 0
        runtime = _eval_runtime(args, settings=settings, argv=argv, repo_root=repo_root)
        meta, cases = asyncio.run(
            run_suite(
                tasks,
                k_values=k_values,
                repetitions=args.repeat,
                combos=combos,
                run_id=runtime.run_id,
                runs_root=out_dir,
                repo_root=repo_root,
                model=runtime.spec.id,
                reasoning_effort=runtime.spec.reasoning_effort,
                catalog=runtime.catalog,
                context_window=runtime.spec.context_window,
                client_factory=lambda: _client_from_spec(runtime.spec),
                probe_client_factory=lambda: _client_from_spec(runtime.spec),
                executor_factory=runtime.executor_factory,
                compaction_limits=runtime.compaction_limits,
                guardrail_limits=runtime.guardrail_limits,
                seed=args.seed,
                command=runtime.command,
                progress=runtime.progress,
            )
        )
    except (TaskFileError, ConfigError, ValueError, OSError) as exc:
        return _fail(exc)
    report = out_dir / meta.run_id / "report.md"
    print(f"[eval] 完成：{len(cases)} 条案例；报表 {report}", file=sys.stderr)
    print(report)
    return 1 if any(case.error for case in cases) else 0


def _run_eval_run(
    args: argparse.Namespace, *, settings: Settings, argv: Sequence[str]
) -> int:
    """通用测评：任务 × 重复次数 → pass^k、每任务成本/耗时、原始轨迹。"""
    try:
        if args.repeat < 1:
            raise ConfigError(f"--repeat 要 ≥1（给了 {args.repeat}）")
        repo_root, tasks_dir, out_dir = _eval_paths(args)
        tasks = _select_eval_tasks(
            load_tasks(tasks_dir), task_ids=args.task, buckets=args.bucket
        )
        snapshot_refs = resolve_task_snapshots(tasks, repo_root)
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            _print_eval_task_plan(tasks, snapshot_refs)
            print(
                f"计划：{len(tasks)} 任务 × {args.repeat} 次重复"
                f" = {len(tasks) * args.repeat} 条案例；"
                f"pass^{args.repeat} 要求每个任务全部重复通过"
            )
            print("dry-run：任务文件与快照 ref 校验通过，未调用模型、未创建 run 目录。")
            return 0
        runtime = _eval_runtime(args, settings=settings, argv=argv, repo_root=repo_root)
        judge_context = _judge_context(runtime)
        meta, cases = asyncio.run(
            run_eval_suite(
                tasks,
                repetitions=args.repeat,
                run_id=runtime.run_id,
                runs_root=out_dir,
                repo_root=repo_root,
                model=runtime.spec.id,
                reasoning_effort=runtime.spec.reasoning_effort,
                catalog=runtime.catalog,
                context_window=runtime.spec.context_window,
                client_factory=lambda: _client_from_spec(runtime.spec),
                executor_factory=runtime.executor_factory,
                compaction_limits=runtime.compaction_limits,
                guardrail_limits=runtime.guardrail_limits,
                seed=args.seed,
                command=runtime.command,
                progress=runtime.progress,
                isolation=runtime.isolation,
                judge_context=judge_context,
            )
        )
    except (TaskFileError, ConfigError, ValueError, OSError) as exc:
        return _fail(exc)
    report = out_dir / meta.run_id / "report.md"
    print(f"[eval] 完成：{len(cases)} 条案例；报表 {report}", file=sys.stderr)
    print(report)
    return 1 if any(case.error for case in cases) else 0


def _run_eval_compare(
    args: argparse.Namespace, *, settings: Settings, argv: Sequence[str]
) -> int:
    """对照组：同一任务集跑 codelotte / mini-swe-agent / 裸单轮 API。"""
    try:
        if args.repeat < 1:
            raise ConfigError(f"--repeat 要 ≥1（给了 {args.repeat}）")
        names = list(dict.fromkeys(args.harness or ["codelotte", "mini-swe-agent", "raw"]))
        if "mini-swe-agent" not in names and args.mini_python:
            raise ConfigError("--mini-python 只在跑 mini-swe-agent 时有效")
        repo_root, tasks_dir, out_dir = _eval_paths(args)
        tasks = _select_eval_tasks(
            load_tasks(tasks_dir), task_ids=args.task, buckets=args.bucket
        )
        snapshot_refs = resolve_task_snapshots(tasks, repo_root)
        mini_command = (
            resolve_mini_command(mini_python=args.mini_python)
            if "mini-swe-agent" in names
            else None
        )
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            _print_eval_task_plan(tasks, snapshot_refs)
            for name in names:
                if name == "mini-swe-agent":
                    assert mini_command is not None
                    print(f"- 组 {name}：启动命令 {shlex.join(mini_command)}")
                elif name == "raw":
                    print("- 组 raw：单次 user 消息，无 tools")
                else:
                    print("- 组 codelotte：真实 loop + 工具 + 验收")
            print(
                f"计划：{len(names)} 组 × {len(tasks)} 任务 × {args.repeat} 次重复"
                f" = {len(names) * len(tasks) * args.repeat} 条案例"
            )
            print("dry-run：任务/快照/harness 校验通过，未调用模型、未创建 run 目录。")
            return 0
        runtime = _eval_runtime(args, settings=settings, argv=argv, repo_root=repo_root)
        run_dir = create_run_dir(out_dir, runtime.run_id + "-compare")
        judge_context = _judge_context(runtime)

        def codelotte_factory() -> CodelotteHarness:
            return CodelotteHarness(
                client=_client_from_spec(runtime.spec),
                model=runtime.spec.id,
                catalog=runtime.catalog,
                executor_factory=runtime.executor_factory,
                context_window=runtime.spec.context_window,
                compaction_limits=runtime.compaction_limits,
                guardrail_limits=runtime.guardrail_limits,
                isolation=runtime.isolation,
            )

        def raw_factory() -> RawHarness:
            return RawHarness(
                client=_client_from_spec(runtime.spec),
                model=runtime.spec.id,
                catalog=runtime.catalog,
            )

        def mini_factory() -> MiniSweAgentHarness:
            assert mini_command is not None
            return MiniSweAgentHarness(
                model=runtime.spec.id,
                base_url=runtime.spec.base_url,
                api_key=runtime.spec.api_key,
                catalog=runtime.catalog,
                command=mini_command,
                reasoning_effort=runtime.spec.reasoning_effort,
            )

        factories = {
            "codelotte": codelotte_factory,
            "raw": raw_factory,
            "mini-swe-agent": mini_factory,
        }
        runs, _checks = asyncio.run(
            run_comparison(
                tasks,
                harnesses=[(name, factories[name]) for name in names],
                repetitions=args.repeat,
                run_dir=run_dir,
                repo_root=repo_root,
                seed=args.seed,
                command=runtime.command,
                model=runtime.spec.id,
                reasoning_effort=runtime.spec.reasoning_effort,
                context_window=runtime.spec.context_window,
                currency=runtime.catalog.currency,
                judge_context=judge_context,
                progress=runtime.progress,
            )
        )
    except (TaskFileError, ConfigError, ValueError, OSError) as exc:
        return _fail(exc)
    report = run_dir / "report.md"
    errored = sum(1 for run in runs for case in run.cases if case.error)
    print(f"[eval] 完成：{len(runs)} 组对照；报表 {report}", file=sys.stderr)
    print(report)
    return 1 if errored else 0


def _run_eval_controls(
    args: argparse.Namespace, *, argv: Sequence[str]
) -> int:
    """控制 agent 自检：不调用模型、不需要 Docker/密钥，直接检验评分链路。"""
    try:
        if args.repeat < 1:
            raise ConfigError(f"--repeat 要 ≥1（给了 {args.repeat}）")
        repo_root, tasks_dir, out_dir = _eval_paths(args)
        tasks = _select_eval_tasks(
            load_tasks(tasks_dir), task_ids=args.task, buckets=args.bucket
        )
        judge_tasks = [task.id for task in tasks if task.verifier.judge is not None]
        if judge_tasks:
            print(
                "提示：控制组不调用模型，跳过 judge 任务："
                + ", ".join(judge_tasks),
                file=sys.stderr,
            )
            tasks = [task for task in tasks if task.verifier.judge is None]
            if not tasks:
                raise ConfigError("筛选后只剩 judge 任务；控制 agent 自检不调用模型")
        snapshot_refs = resolve_task_snapshots(tasks, repo_root)
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            _print_eval_task_plan(tasks, snapshot_refs)
            print(
                f"计划：oracle / no-op / cheating × {len(tasks)} 任务 × {args.repeat} 次"
                f" = {3 * len(tasks) * args.repeat} 条案例"
            )
            print("预期：oracle 100% 通过；no-op 0% 通过；cheating 0% 通过且全部被标记。")
            print("dry-run：任务/快照校验通过，未写 run 目录。")
            return 0
        run_id = make_run_id(current_git_ref(repo_root)) + "-controls"
        run_dir = create_run_dir(out_dir, run_id)
        command = "codelotte " + shlex.join(list(argv))
        runs, checks = asyncio.run(
            run_comparison(
                tasks,
                harnesses=[
                    ("oracle", OracleHarness),
                    ("no-op", NoOpHarness),
                    ("cheating", CheatingHarness),
                ],
                repetitions=args.repeat,
                run_dir=run_dir,
                repo_root=repo_root,
                seed=args.seed,
                command=command,
                model="—",
                reasoning_effort="—",
                context_window=0,
                currency="CNY",
            )
        )
    except (TaskFileError, ConfigError, ValueError, OSError) as exc:
        return _fail(exc)
    report = run_dir / "report.md"
    passed = bool(checks) and all(check.passed for check in checks)
    print(
        f"[eval] 控制 agent 自检{'通过' if passed else '未通过'}；"
        f"{len(runs)} 组案例；报表 {report}",
        file=sys.stderr,
    )
    print(report)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
    try:
        settings = (
            load_settings()
        )  # 用户级 ~/.codelotte/settings.json（文件键与字段一一对应）
    except ConfigError as exc:
        return _fail(exc)  # 坏配置给可读错误 + 退出码 2（不裸 traceback）
    for note in settings.notices:
        print(f"提示：{note}", file=sys.stderr)

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "eval":
        eval_command = getattr(args, "eval_command", None)
        if eval_command == "compaction":
            return _run_eval_compaction(
                args,
                settings=settings,
                argv=list(argv) if argv is not None else sys.argv[1:],
            )
        if eval_command == "run":
            return _run_eval_run(
                args,
                settings=settings,
                argv=list(argv) if argv is not None else sys.argv[1:],
            )
        if eval_command == "compare":
            return _run_eval_compare(
                args,
                settings=settings,
                argv=list(argv) if argv is not None else sys.argv[1:],
            )
        if eval_command == "controls":
            return _run_eval_controls(
                args,
                argv=list(argv) if argv is not None else sys.argv[1:],
            )
        if eval_command == "judge":
            return _run_eval_judge(args, settings=settings)
        if eval_command == "attribute":
            return _run_eval_attribute(args)
        if eval_command == "regression":
            return _run_eval_regression(args)
        if eval_command == "cost":
            return _run_eval_cost(
                args,
                argv=list(argv) if argv is not None else sys.argv[1:],
            )
        if eval_command == "defense":
            return _run_eval_defense(args)
        parser.error(
            "用法：codelotte eval {compaction,run,compare,controls,judge,attribute,regression,cost,defense} …；"
            "compaction 跑压缩回归，run 跑通用测评，compare 跑对照组，"
            "controls 跑控制 agent 自检，judge 校准 LLM judge，"
            "attribute 量归因准确率，regression 把失败转成回归任务，"
            "cost 重算缓存/off-peak 成本曲线，defense 量死循环/注入防御与误报"
        )
    if args.command == "export":
        return _run_export(args)
    if args.command == "trust":
        return _run_trust()
    if args.command in ("allow", "ask", "deny"):
        return _run_perm_write(args)
    if args.resume == "":
        if args.prompt is not None:
            parser.error(
                "--resume 不带序号只是列出会话、不会执行提示词；"
                "要恢复并执行请加序号（--resume <序号>）"
            )
        if args.fork is not None:
            parser.error(
                "--resume 不带序号只是列出会话；--fork 要和 --resume <序号> 一起用"
            )
        return _list_sessions()
    if args.continue_ and args.fork is not None:
        parser.error(
            "-c/--continue 与 --fork 不能同用：--fork 不带 --resume 就是从最近会话分岔"
        )
    resume_index: int | None = None
    if args.resume is not None:
        try:
            resume_index = int(args.resume)
        except ValueError:
            print(
                f"错误：--resume 的序号要是一个数字（给了 {args.resume!r}）",
                file=sys.stderr,
            )
            return 2
    try:  # 规则只解析一次（main），三个入口共用（审查修正：三参数结块）
        rules = _parse_cli_rules(args.allow or (), args.ask or (), args.deny or ())
    except SessionError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    # 更新提示只在"真的开始一次运行"时处理（-p / TUI）：只读命令（export/--resume/trust…）
    # 不改用户文件、不打扰。写回是读-改-写 + 原子替换，见 config.record_changelog_version。
    notice = changelog_notice(settings.last_changelog_version, __version__)
    record_changelog_version(__version__)  # 已在位就不写（幂等）
    if args.prompt is not None:
        if notice:
            print(notice, file=sys.stderr)  # 更新提示：-p 打 stderr（TUI 里进对话流）
        if args.no_sandbox:
            print(SANDBOX_OFF_WARNING, file=sys.stderr)  # 逃生门：风险必须显式可见
        return _run_prompt(
            args.prompt,
            resume=args.continue_,
            resume_index=resume_index,
            fork_from_end=args.fork,
            rules=rules,
            settings=settings,
            no_sandbox=args.no_sandbox,
        )

    startup_notices = [notice] if notice else []
    if args.no_sandbox:
        startup_notices.append(SANDBOX_OFF_WARNING)
    return _run_tui(
        resume=args.continue_,
        resume_index=resume_index,
        fork_from_end=args.fork,
        rules=rules,
        notices=startup_notices,
        settings=settings,
        no_sandbox=args.no_sandbox,
    )
