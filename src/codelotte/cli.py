"""codelotte 命令行入口：无参数进 TUI，`-p` 一次性执行，`--continue` 恢复上次会话。"""

from __future__ import annotations

import argparse
import asyncio
import sys
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
from codelotte.session.store import load_entries, open_session
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
    parser.add_argument(
        "-c",
        "--continue",
        dest="continue_",
        action="store_true",
        help="恢复本项目目录下最近一次会话，接着聊（--continue）",
    )
    return parser


def _build_agent(*, resume: bool) -> AgentLoop:
    """装配一次真实运行的循环——无头与 TUI 共用这一处（票据 10 在这里换 Docker 执行器）。

    先读配置、后建会话文件：配置缺失（如没密钥）不得留下"只有会话头的空文件"，
    否则 --continue 按 mtime 会挑中它，把真实历史跳过。
    """
    model = get_model()
    client = OpenAICompletionsClient(
        base_url=get_base_url(), api_key=get_api_key(), model=model
    )
    executor = LocalExecutor()
    store, messages = open_session(
        Path.cwd(), base_dir=get_session_dir(), resume=resume
    )
    return AgentLoop(
        client=client,
        tools=default_tools(executor),
        store=store,
        model=model,
        env=executor.env,
        messages=messages,
    )


def _run_prompt(prompt: str, *, show_reasoning: bool, resume: bool = False) -> int:
    try:
        loop = _build_agent(resume=resume)
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
    except OSError as exc:
        # 管道提前关闭（`codelotte ... | head`）、--continue 但无会话、会话目录不可写等
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def _run_tui(*, resume: bool) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            "错误：交互界面需要真实终端（当前 stdin/stdout 不是 tty）。"
            "一次性任务请用 -p；恢复会话可加 --continue。",
            file=sys.stderr,
        )
        return 2
    try:
        from codelotte.tui import TuiApp  # 延迟导入：无头模式不必加载 Textual

        loop = _build_agent(resume=resume)
        history = load_entries(loop.session_path)  # 新会话只有头记录，渲染时自动跳过
        TuiApp(agent=loop, model=get_model(), history=history).run()
        return 0
    except ConfigError as exc:
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
    if args.prompt is not None:
        return _run_prompt(
            args.prompt, show_reasoning=args.reasoning, resume=args.continue_
        )

    return _run_tui(resume=args.continue_)
