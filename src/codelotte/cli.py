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
    # 当前阶段尚无任何子命令：唯一可达路径是"无参数"，打印帮助并成功退出。
    # 票据 02 起在此按解析结果分发（`-p` 无头模式 / 交互式 TUI）。
    parser.print_help()
    return 0
