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
from collections.abc import Sequence
from datetime import datetime
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
from codelotte.cost import load_catalog
from codelotte.evals.meta import (
    current_git_ref,
    find_repo_root,
    make_run_id,
)
from codelotte.evals.suite import run_suite
from codelotte.evals.tasks import TaskFileError, load_tasks
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
        "eval", help="回归实验（票据 13）：一条命令跑出完整报表"
    )
    eval_sub = eval_parser.add_subparsers(dest="eval_command", metavar="实验")
    compaction_parser = eval_sub.add_parser(
        "compaction",
        help="压缩回归套件 v0：强制压缩 k 次，测完成率与 checkpoint 状态保留率",
    )
    compaction_parser.add_argument(
        "--k",
        default="0,1,3,5",
        metavar="列表",
        help="强制压缩次数（逗号分隔；0 是不压缩的对照组，默认 0,1,3,5）",
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


def _run_eval_compaction(
    args: argparse.Namespace, *, settings: Settings, argv: Sequence[str]
) -> int:
    """一条命令跑完整轮压缩回归并落报表；返回报表路径（stdout）与进度（stderr）。"""
    try:
        k_values = _parse_k_values(args.k)
        if args.repeat < 1:
            raise ConfigError(f"--repeat 要 ≥1（给了 {args.repeat}）")
        repo_root = find_repo_root(Path.cwd())
        tasks_dir = Path(args.tasks) if args.tasks else repo_root / "evals" / "tasks"
        out_dir = Path(args.out) if args.out else repo_root / "evals" / "runs"
        tasks = load_tasks(tasks_dir)
        if args.task:
            wanted = set(args.task)
            available = {task.id for task in tasks}
            missing = wanted - available
            if missing:
                raise TaskFileError(
                    f"没有这些任务 id：{sorted(missing)}；可选：{sorted(available)}"
                )
            tasks = [task for task in tasks if task.id in wanted]
        if args.dry_run:
            print(f"任务目录：{tasks_dir}")
            for task in tasks:
                print(
                    f"- {task.id}（{task.bucket} 桶，{len(task.checkpoints)} 个 checkpoint，"
                    f"超时 {task.timeout_seconds:g}s，最多 {task.max_model_calls} 次模型调用）"
                )
            cases = len(tasks) * len(k_values) * args.repeat
            print(
                f"计划：{len(tasks)} 任务 × {len(k_values)} 个 k × {args.repeat} 次重复"
                f" = {cases} 条案例；k={','.join(str(k) for k in k_values)}"
            )
            print("dry-run：任务文件校验通过，未调用模型、未创建 run 目录。")
            return 0
        catalog = load_catalog()
        spec = resolve(settings, catalog)
        compaction_limits = CompactionLimits.from_settings(settings)
        guardrail_limits = GuardrailLimits.from_settings(settings)
        if args.no_sandbox:
            print(SANDBOX_OFF_WARNING, file=sys.stderr)
            executor_factory = LocalExecutor
        else:
            _ensure_docker_available()
            executor_factory = DockerExecutor
        run_id = make_run_id(current_git_ref(repo_root))
        command = "codelotte " + shlex.join(list(argv))

        def progress(line: str) -> None:
            print(f"[eval] {line}", file=sys.stderr, flush=True)

        meta, cases = asyncio.run(
            run_suite(
                tasks,
                k_values=k_values,
                repetitions=args.repeat,
                run_id=run_id,
                runs_root=out_dir,
                repo_root=repo_root,
                model=spec.id,
                reasoning_effort=spec.reasoning_effort,
                catalog=catalog,
                context_window=spec.context_window,
                client_factory=lambda: _client_from_spec(spec),
                probe_client_factory=lambda: _client_from_spec(spec),
                executor_factory=executor_factory,
                compaction_limits=compaction_limits,
                guardrail_limits=guardrail_limits,
                seed=args.seed,
                command=command,
                progress=progress,
            )
        )
    except (TaskFileError, ConfigError, ValueError, OSError) as exc:
        return _fail(exc)
    report = out_dir / meta.run_id / "report.md"
    print(f"[eval] 完成：{len(cases)} 条案例；报表 {report}", file=sys.stderr)
    print(report)
    return 1 if any(case.error for case in cases) else 0


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
        if getattr(args, "eval_command", None) != "compaction":
            parser.error(
                "用法：codelotte eval compaction [--k 0,1,3,5] [--tasks 目录] "
                "[--out 目录] [--repeat N] [--seed N] [--task ID] [--no-sandbox]"
            )
        return _run_eval_compaction(
            args,
            settings=settings,
            argv=list(argv) if argv is not None else sys.argv[1:],
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
