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
        help="非交互模式：执行一次提示词，流式打印回答后退出",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prompt is not None:
        try:
            return asyncio.run(run_once(args.prompt))
        except ConfigError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        except ProviderError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
    # 当前阶段尚无交互界面：无参数时打印帮助并成功退出。票据 05 起在此接入 TUI。
    parser.print_help()
    return 0
