"""codelotte 命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
import sys

from codelotte import __version__
from codelotte.config import ConfigError, get_home_dir, load_env_files
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
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"codelotte {__version__}",
    )
    parser.add_argument(
        "-p",
        "--print",
        dest="prompt",
        metavar="PROMPT",
        help='非交互模式：执行一次提示词，流式打印回答后退出（提示词以 "-" 开头时用 `--print=...` 或直接放在 -p 之后）',
    )
    parser.add_argument(
        "-r",
        "--reasoning",
        action="store_true",
        help="把思考过程（reasoning_content）以暗色实时输出到 stderr；默认只写入会话文件",
    )
    return parser


def _run_prompt(prompt: str, *, show_reasoning: bool = False) -> int:
    try:
        return asyncio.run(run_once(prompt, show_reasoning=show_reasoning))
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
    load_env_files(home=get_home_dir())  # 自动加载 ~/.codelotte/.env 与 ./.env
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    # 兼容以 "-" 开头的提示词（如 `codelotte -p --dry-run`）：argparse 会把它当选项，
    # 所以仅当 -p/--print 打头且其后首个词以 "-" 开头时，整段按提示词处理。
    # 提示词不以 "-" 开头时交给 argparse 正常解析，从而支持 flag 后置写法：
    # `codelotte -p "问题" -r`
    if (
        raw_argv[:1] in (["-p"], ["--print"])
        and len(raw_argv) >= 2
        and raw_argv[1].startswith("-")
    ):
        return _run_prompt(" ".join(raw_argv[1:]))
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prompt is not None:
        return _run_prompt(args.prompt, show_reasoning=args.reasoning)
    # 当前阶段尚无交互界面：无参数时打印帮助并成功退出。票据 05 起在此接入 TUI。
    parser.print_help()
    return 0
