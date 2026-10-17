"""本地执行器测试（票据 04）：退出码、输出分离、cwd、超时杀整个进程组。

用真实命令（SPEC §K：Executor 缝的测试走本地实现，不引入测试专用开关）。
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

from codelotte.sandbox import ExecResult, LocalExecutor

# 子进程一律以 UTF-8 模式跑（-X utf8）：stdout/stderr 的编码不随机器区域设置漂移。
# 反例（CI windows runner 真实翻过车）：英文 locale 下管道编码是 cp1252——子进程 print 中文
# 直接 UnicodeEncodeError（stdout 严格编码），写 stderr 则退化成 "坏了" 转义
# （stderr 默认 backslashreplace），两类断言都会误伤。UTF-8 模式下与机器 locale 无关。
PY = f'"{sys.executable}" -X utf8'

# 外层脚本：启动一个持续"心跳"的孙进程（每 0.5 秒往文件追加一行，最多 60 秒），自己睡 30 秒。
# 若超时/取消只杀到 shell 或只杀到本进程，孙进程会继续心跳——"心跳停止"就是整树被杀的直接证据。
# 用心跳采样而不是"睡固定时长看某个标记"：后者依赖"杀进程发生在标记写入之前"的时序假设，
# CI 冷启动下孙进程的创建恰好撞上杀进程时刻时会误报（真实翻车过）；心跳法只要求两个事实：
# 活着（杀之前已有心跳）与 死了（杀之后没有新心跳），不含任何时刻假设。
SPAWNER_SCRIPT = """\
import subprocess, sys, time

beat = sys.argv[1]
inner = (
    "import sys, time" + chr(10)
    + "for _ in range(120):" + chr(10)
    + "    open(sys.argv[1], 'a').write('x' + chr(10))" + chr(10)
    + "    time.sleep(0.5)" + chr(10)
)
subprocess.Popen([sys.executable, "-c", inner, beat])
time.sleep(30)
"""


def _run(command: str, cwd: Path, timeout: float = 30.0) -> ExecResult:
    return asyncio.run(LocalExecutor().run(command, cwd=cwd, timeout=timeout))


def _beat_count(beat: Path) -> int:
    """孙进程的心跳行数（文件还不存在=0）。"""
    try:
        return beat.read_text(encoding="utf-8").count("\n")
    except OSError:
        return 0


def _assert_heartbeat_stopped(beat: Path) -> None:
    """杀完后再采两次心跳行数：整树被杀 → 不再有新行（两个样本相等）。"""
    time.sleep(1.5)  # 留出一整拍的心跳间隔：还活着的话，这期间必然有新行
    beats_after = _beat_count(beat)
    time.sleep(1.5)
    assert _beat_count(beat) == beats_after, "孙进程还在心跳——杀掉/收回的不是整棵进程树"


def test_echo_succeeds_with_stdout(tmp_path: Path) -> None:
    result = _run(f'{PY} -c "print(\'你好\')"', tmp_path)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert "你好" in result.stdout
    assert result.stderr == ""


def test_nonzero_exit_code_is_reported(tmp_path: Path) -> None:
    result = _run(f'{PY} -c "import sys; sys.exit(3)"', tmp_path)
    assert result.exit_code == 3
    assert result.timed_out is False


def test_stderr_is_captured_separately(tmp_path: Path) -> None:
    result = _run(f'{PY} -c "import sys; sys.stderr.write(\'坏了\')"', tmp_path)
    assert result.stdout == ""
    assert "坏了" in result.stderr


def test_cwd_is_honored(tmp_path: Path) -> None:
    result = _run(f'{PY} -c "import os; print(os.getcwd())"', tmp_path)
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_invalid_utf8_output_does_not_crash(tmp_path: Path) -> None:
    script = tmp_path / "emit_raw.py"
    script.write_text("import sys\nsys.stdout.buffer.write(bytes([255, 254]))\n", encoding="utf-8")
    result = _run(f'{PY} "{script}"', tmp_path)
    assert result.exit_code == 0
    assert isinstance(result.stdout, str)  # 坏字节被替换而不是抛异常


def test_timeout_kills_whole_process_tree(tmp_path: Path) -> None:
    spawner = tmp_path / "spawner.py"
    spawner.write_text(SPAWNER_SCRIPT, encoding="utf-8")
    beat = tmp_path / "beat.txt"
    started = time.perf_counter()
    result = _run(f'{PY} "{spawner}" "{beat}"', tmp_path, timeout=3.0)
    elapsed = time.perf_counter() - started
    assert result.timed_out is True
    assert elapsed < 10.0  # 没有傻等 30 秒：超时即杀即返回
    assert _beat_count(beat) > 0, "孙进程没有跑起来（心跳为空）——测试前提不成立"
    _assert_heartbeat_stopped(beat)


def test_console_encoding_fallback_for_legacy_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows 控制台工具（cmd 报错等）按 ANSI 代码页输出：UTF-8 解不开时按 locale.getencoding() 兜底。

    通过 run() 的可观察行为断言（不直接测私有函数）：控制台编码固定为 cp936，
    子进程吐出 cp936 字节，结果应能正确解码。
    """
    from codelotte.sandbox import executor as executor_module

    # 解码逻辑与 Docker 执行器共用（sandbox.executor.decode_output），这里替换它的代码页来源
    monkeypatch.setattr(executor_module.locale, "getencoding", lambda: "cp936")
    script = tmp_path / "emit_gbk.py"
    script.write_text(
        "import sys" + chr(10) + "sys.stdout.buffer.write('你好'.encode('cp936'))" + chr(10),
        encoding="utf-8",
    )
    result = _run(f'{PY} "{script}"', tmp_path)
    assert result.exit_code == 0
    assert result.stdout == "你好"


def test_cancellation_kills_whole_process_tree(tmp_path: Path) -> None:
    """run 被中断（Ctrl+C → 协程取消）时也要收回子进程：不能让命令留在后台继续跑。"""
    spawner = tmp_path / "spawner2.py"
    spawner.write_text(SPAWNER_SCRIPT, encoding="utf-8")
    beat = tmp_path / "beat_cancel.txt"

    async def scenario() -> None:
        task = asyncio.create_task(
            LocalExecutor().run(f'{PY} "{spawner}" "{beat}"', cwd=tmp_path, timeout=60)
        )
        # 等孙进程确实开始心跳（轮询而非固定时长：CI 冷启动下启动慢也不误伤）
        for _ in range(150):
            if _beat_count(beat) > 0:
                break
            await asyncio.sleep(0.1)
        assert _beat_count(beat) > 0, "孙进程没有跑起来（心跳为空）——测试前提不成立"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    _assert_heartbeat_stopped(beat)


def test_windows_prefers_git_bash_so_bash_syntax_works(tmp_path: Path) -> None:
    """回归（2026-10-15 真机）：工具名叫 bash，Windows 上也应支持 bash 语法。

    cmd 会把 `;` 当普通字符原样打出、把 `cd /d/...` 里的 /d 当自己的开关；
    Git Bash 不会。找不到 Git Bash（执行器退回 cmd 模式）时本断言不适用，跳过。
    """
    from codelotte.sandbox.local import _find_git_bash

    if _find_git_bash() is None:
        pytest.skip("本机找不到 Git Bash：执行器退回 cmd 模式")
    result = _run("echo one; echo two", tmp_path)
    assert result.exit_code == 0
    assert result.stdout.split() == ["one", "two"]
