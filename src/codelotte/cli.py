"""codelotte 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys

from codelotte import __version__
from codelotte.config import ConfigError
from codelotte.providers.base import ProviderError
from codelotte.run import run_once


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
    parser.add_argument("--version", action="version", version=f"codelotte {__version__}")
    parser.add_argument(
        "-p",
        "--print",
        dest="prompt",
        metavar="PROMPT",
        help='非交互模式：执行一次提示词，流式打印回答后退出（提示词以 "-" 开头时用 `--print=...` 或直接放在 -p 之后）',
    )
    return parser


def _run_prompt(prompt: str) -> int:
    try:
        return asyncio.run(run_once(prompt))
    except ConfigError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except ProviderError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        # 管道提前关闭（`codelotte ... | head`）、会话目录不可写等
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    # 兼容以 "-" 开头的提示词（如 `codelotte -p --dry-run`）：
    # argparse 会把 --dry-run 当选项；当 -p/--print 是首个参数时，其后全部按提示词处理
    if raw_argv[:1] in (["-p"], ["--print"]) and len(raw_argv) >= 2:
        return _run_prompt(" ".join(raw_argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prompt is not None:
        return _run_prompt(args.prompt)
    # 当前阶段尚无交互界面：无参数时打印帮助并成功退出。票据 05 起在此接入 TUI。
    parser.print_help()
    return 0
