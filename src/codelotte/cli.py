"""codelotte 命令行入口：无参数进 TUI，`-p` 一次性执行，`--continue`/`--resume`/`--fork` 接会话。

恢复三兄弟（互斥）：`--continue` 回到最近活动的分支；`--resume` 列出/选择历史会话与分支；
`--fork N` 从最近会话活动分支的倒数第 N 条消息处分岔（同一文件内成树，原分支不受影响）。
"""

from __future__ import annotations

import argparse
import asyncio
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
from codelotte.loop import AgentLoop
from codelotte.providers.base import ProviderError
from codelotte.providers.openai_completions import OpenAICompletionsClient
from codelotte.run import run_once
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import (
    SessionError,
    fork_at,
    fork_session,
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
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except SessionError as exc:
        # --resume/--fork 的序号问题（错误信息本身就是给用户看的）
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # 管道提前关闭（`codelotte ... | head`）、--continue 但无会话、会话目录不可写等
        print(f"错误：{exc}", file=sys.stderr)
        return 1


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
        return 0
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except SessionError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
    load_env_files(home=get_home_dir())  # 自动加载 ~/.codelotte/.env 与 ./.env

    parser = build_parser()
    args = parser.parse_args(argv)
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
