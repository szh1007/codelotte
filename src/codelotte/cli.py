"""codelotte 命令行入口。"""

from __future__ import annotations

import argparse

from codelotte import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codelotte",
        description="minimal-core, extensible terminal coding agent",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"codelotte {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    # 无参数时暂打印帮助；后续票据接入 `-p` 无头模式与交互式 TUI
    parser.print_help()
    return 0
