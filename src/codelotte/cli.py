"""codelotte 命令行入口：无参数进 TUI，`-p` 一次性执行，`--continue`/`--resume`/`--fork` 接会话。

恢复三兄弟（互斥）：`--continue` 回到最近活动的分支；`--resume` 列出/选择历史会话与分支；
`--fork N` 从最近会话活动分支的倒数第 N 条消息处分岔（同一文件内成树，原分支不受影响）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from codelotte import __version__
from codelotte.config import (
    ConfigError,
    get_api_key,
    get_base_url,
    get_home_dir,
    get_model,
    get_session_dir,
    load_env_files,
)
from codelotte.cost import load_catalog
from codelotte.export import render_session_html, render_session_markdown
from codelotte.loop import AgentLoop
from codelotte.providers.base import ProviderError
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.run import print_session_invoice, run_once
from codelotte.sandbox import LocalExecutor
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
    parser.add_argument(
        "-r",
        "--reasoning",
        action="store_true",
        help="把思考过程（reasoning_content）以暗色实时输出到 stderr；默认只写入会话文件",
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
    subcommands = parser.add_subparsers(dest="command", metavar="命令")
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
    items, skipped = list_resumable(Path.cwd(), base_dir=get_session_dir())
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
    cwd, base = Path.cwd(), get_session_dir()
    try:
        if selector == "":
            path = latest_session_path(cwd, base_dir=base)
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
                print(f"错误：{flag} 的序号要是一个数字（给了 {selector!r}）", file=sys.stderr)
                return 2
            items, skipped = list_resumable(cwd, base_dir=base)
            _warn_skipped(skipped)
            if not 1 <= index <= len(items):
                raise SessionError(f"没有第 {index} 个可恢复的会话（共 {len(items)} 个）")
            item = items[index - 1]
            path, leaf_id = item.path, item.leaf_id
        try:
            entries = load_branch(path, leaf_id)
        except json.JSONDecodeError as exc:  # 坏文件给可读错误，不裸 traceback（审查修正）
            print(f"错误：会话文件有坏行，读不动（{path.name}）：{exc}", file=sys.stderr)
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


def _build_agent(
    *,
    resume: bool = False,
    resume_index: int | None = None,
    fork_from_end: int | None = None,
) -> AgentLoop:
    """装配一次真实运行的循环——无头与 TUI 共用这一处（票据 10 在这里换 Docker 执行器）。

    先读配置、后建会话文件：配置缺失（如没密钥）不得留下"只有会话头的空文件"，
    否则 --continue 按 mtime 会挑中它，把真实历史跳过。

    resume_index 给出时恢复指定分支；fork_from_end 可与其组合（在选中的分支上再分岔）。
    """
    model = get_model()
    catalog = (
        load_catalog()
    )  # 价目/峰谷/节假日（票据 07）；坏目录在这里就以 ConfigError 报出
    client = OpenAICompletionsClient(
        base_url=get_base_url(), api_key=get_api_key(), model=model
    )
    executor = LocalExecutor()
    cwd, base = Path.cwd(), get_session_dir()
    if resume_index is not None:
        items, skipped = list_resumable(cwd, base_dir=base)
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
        store, messages = fork_session(cwd, base_dir=base, from_end=fork_from_end)
    else:
        store, messages = open_session(cwd, base_dir=base, resume=resume)
    return AgentLoop(
        client=client,
        tools=default_tools(executor),
        store=store,
        model=model,
        env=executor.env,
        messages=messages,
        catalog=catalog,
    )


def _run_prompt(
    prompt: str,
    *,
    show_reasoning: bool,
    resume: bool = False,
    resume_index: int | None = None,
    fork_from_end: int | None = None,
) -> int:
    try:
        loop = _build_agent(
            resume=resume, resume_index=resume_index, fork_from_end=fork_from_end
        )
        return asyncio.run(run_once(loop, prompt, show_reasoning=show_reasoning))
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

        loop = _build_agent(
            resume=resume, resume_index=resume_index, fork_from_end=fork_from_end
        )
        history = load_branch(loop.session_path, loop.leaf_id)  # 只回放活动分支
        TuiApp(agent=loop, model=get_model(), history=history).run()
        print_session_invoice(loop)  # 会话结束汇总：与 -p 同一口径（票据 07）
        return 0
    except (ConfigError, SessionError, OSError) as exc:
        return _fail(exc)


def main(argv: list[str] | None = None) -> int:
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
    load_env_files(home=get_home_dir())  # 自动加载 ~/.codelotte/.env 与 ./.env

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "export":
        return _run_export(args)
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
    if args.prompt is not None:
        return _run_prompt(
            args.prompt,
            show_reasoning=args.reasoning,
            resume=args.continue_,
            resume_index=resume_index,
            fork_from_end=args.fork,
        )

    return _run_tui(
        resume=args.continue_, resume_index=resume_index, fork_from_end=args.fork
    )
