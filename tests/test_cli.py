"""CLI 入口的冒烟测试（票据 01/02 验收项）。

测试缝在"进程边界"——以子进程方式运行真实 CLI，只验证外部可观察行为。
子进程强制 PYTHONUTF8=1（UTF-8 模式），父进程按 UTF-8 解码，
避免 Windows ANSI 代码页（cp936）与 UTF-8 解码错位导致的假失败。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import codelotte

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30


def child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONUTF8": "1"}


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codelotte", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=child_env(),
        cwd=PROJECT_ROOT,
    )


def test_version_flag_prints_version_and_exits_zero() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_no_args_without_a_real_terminal_fails_readably(tmp_path: Path) -> None:
    """无参数 = 进 TUI（票据 05）：管道/CI 里没有真实终端时给可读错误，不往 stdout 喷转义码。"""
    env = {
        **child_env(),
        "DEEPSEEK_API_KEY": "test-key",
        "CODELOTTE_HOME": str(tmp_path / "home"),
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "codelotte"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2
    assert "真实终端" in result.stderr
    assert "Traceback" not in result.stderr
    assert "\x1b[" not in result.stdout  # 没把全屏转义码喷进管道


def test_continue_without_any_session_fails_readably(tmp_path: Path) -> None:
    env = {
        **child_env(),
        "DEEPSEEK_API_KEY": "test-key",
        "CODELOTTE_HOME": str(tmp_path / "home"),
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi", "--continue"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "没有可继续的会话" in result.stderr
    assert "Traceback" not in result.stderr


def test_continue_flags_parse() -> None:
    from codelotte.cli import build_parser

    assert build_parser().parse_args(["--continue"]).continue_ is True
    assert build_parser().parse_args(["-c"]).continue_ is True
    assert build_parser().parse_args([]).continue_ is False


def test_resume_and_fork_flags_parse() -> None:
    """票据 06：--resume 带/不带序号、--fork N；--fork 可与 --resume 同用（选分支再分岔）。"""
    from codelotte.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["--resume"]).resume == ""  # 无序号 = 列会话
    assert parser.parse_args(["--resume", "3"]).resume == "3"
    assert parser.parse_args([]).resume is None
    assert parser.parse_args(["--fork", "2"]).fork == 2
    combined = parser.parse_args(["--resume", "1", "--fork", "1"])
    assert (combined.resume, combined.fork) == ("1", 1)
    with pytest.raises(SystemExit):
        parser.parse_args(["-c", "--resume"])  # --continue 与 --resume 仍互斥


def _session_env(tmp_path: Path, *, with_key: bool = True) -> dict[str, str]:
    env = {
        **child_env(),
        "CODELOTTE_HOME": str(tmp_path / "home"),
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    if with_key:
        env["DEEPSEEK_API_KEY"] = "test-key"
    else:
        env = {k: v for k, v in env.items() if k != "DEEPSEEK_API_KEY"}
    return env


def test_resume_list_is_readable_and_needs_no_key(tmp_path: Path) -> None:
    """--resume 无序号 = 只读查询：不需要密钥，也不该留下会话文件。"""
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "--resume"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=_session_env(tmp_path, with_key=False),
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0
    assert "还没有可恢复的会话" in result.stdout
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "sessions").exists()


def test_resume_index_out_of_range_fails_readably(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi", "--resume", "3"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=_session_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "没有第 3 个可恢复的会话" in result.stderr
    assert "Traceback" not in result.stderr


def test_fork_without_session_fails_readably(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi", "--fork", "1"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=_session_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "没有可分叉的会话" in result.stderr
    assert "Traceback" not in result.stderr


def test_fork_zero_is_rejected(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi", "--fork", "0"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=_session_env(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "--fork 要一个 ≥ 1 的位置" in result.stderr
    assert "Traceback" not in result.stderr


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "codelotte", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=_session_env(tmp_path),
        cwd=tmp_path,
    )


def test_resume_list_with_prompt_is_rejected(tmp_path: Path) -> None:
    """回归（审查发现）：`-p X --resume` 不得静默丢弃提示词。"""
    result = _cli(tmp_path, "-p", "DO-SOMETHING", "--resume")
    assert result.returncode == 2
    assert "不会执行提示词" in result.stderr
    assert "Traceback" not in result.stderr


def test_continue_with_fork_is_rejected(tmp_path: Path) -> None:
    result = _cli(tmp_path, "-p", "hi", "--continue", "--fork", "1")
    assert result.returncode == 2
    assert "不能同用" in result.stderr
    assert "Traceback" not in result.stderr


def test_resume_list_with_fork_is_rejected(tmp_path: Path) -> None:
    result = _cli(tmp_path, "--resume", "--fork", "1")
    assert result.returncode == 2
    assert "--resume <序号> 一起用" in result.stderr
    assert "Traceback" not in result.stderr


def test_resume_list_warns_about_damaged_and_lists_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归（审查发现）：损坏的会话要被跳过并警告，健康的会话不受牵连。"""
    from codelotte.session.store import SessionStore

    monkeypatch.setenv("CODELOTTE_SESSION_DIR", str(tmp_path / "sessions"))
    store = SessionStore.start(tmp_path, base_dir=tmp_path / "sessions")
    store.append("message", role="user", content="好的会话")
    (store.path.parent / "20990101T000000Z_damaged0.jsonl").write_text(
        '{"id": "x", "parentId": "zzz", "type": "session"}\n', encoding="utf-8"
    )

    result = _cli(tmp_path, "--resume")
    assert result.returncode == 0
    assert "警告：跳过损坏的会话" in result.stderr
    assert "好的会话" in result.stdout


def test_build_agent_history_follows_selected_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TUI 回放回归：--fork 之后按 leaf_id 取到的历史只含活动分支——不能把其它分支也画出来。"""
    from codelotte.cli import _build_agent
    from codelotte.session.store import SessionStore, load_branch

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("CODELOTTE_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.chdir(tmp_path)
    store = SessionStore.start(tmp_path, base_dir=tmp_path / "sessions")
    store.append("message", role="user", content="第一问")
    store.append("message", role="assistant", content="第一答", model="m", stopReason="stop")
    store.append("message", role="user", content="第二问")

    loop = _build_agent(fork_from_end=2)  # 在"第一答"处分岔
    history = load_branch(loop.session_path, loop.leaf_id)  # _run_tui 的真实取数路径
    contents = [e.get("content") for e in history if e.get("type") == "message"]
    assert contents == ["第一问", "第一答"]  # 老的叶子"第二问"不在新分支的可见记录里


def test_build_agent_resume_ignores_damaged_neighbour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归（审查发现）：会话目录里存在损坏文件时，恢复有效会话不能受牵连。"""
    from codelotte.cli import _build_agent
    from codelotte.session.store import SessionStore

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("CODELOTTE_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.chdir(tmp_path)
    store = SessionStore.start(tmp_path, base_dir=tmp_path / "sessions")
    store.append("message", role="user", content="好的会话")
    (store.path.parent / "20990101T000000Z_damaged0.jsonl").write_text(
        '{"id": "x", "parentId": "zzz", "type": "session"}\n', encoding="utf-8"
    )

    loop = _build_agent(resume_index=1)
    assert loop.session_path == store.path
    assert [m["content"] for m in loop.messages] == ["好的会话"]


def test_console_script_entry_point_works() -> None:
    script = shutil.which("codelotte")
    assert script is not None, "console script 不在 PATH 上——请通过 `uv run pytest` 运行测试"
    result = subprocess.run(
        [script, "--version"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=child_env(),
    )
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_config_error_leaves_no_session_file(tmp_path: Path) -> None:
    """回归（审查发现）：没密钥的启动不得留下"只有会话头"的空会话文件——
    否则 --continue 按 mtime 会挑中它，真实历史被跳过。"""
    env = {k: v for k, v in child_env().items() if k != "DEEPSEEK_API_KEY"}
    env["CODELOTTE_HOME"] = str(tmp_path / "home")
    env["CODELOTTE_SESSION_DIR"] = str(tmp_path / "sessions")
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 2
    sessions = tmp_path / "sessions"
    assert not (sessions.exists() and list(sessions.rglob("*.jsonl")))


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == codelotte.__version__


def test_missing_api_key_fails_with_readable_error(tmp_path: Path) -> None:
    env = {k: v for k, v in child_env().items() if k != "DEEPSEEK_API_KEY"}
    env["CODELOTTE_HOME"] = str(tmp_path / "home")  # 隔离用户级 .env
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=env,
        cwd=tmp_path,  # 空目录：不加载项目级 .env
    )
    assert result.returncode == 2
    assert "DEEPSEEK_API_KEY" in result.stderr
    assert "Traceback" not in result.stderr
