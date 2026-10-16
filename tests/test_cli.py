"""CLI 入口的冒烟测试（票据 01/02 验收项）。

测试缝在"进程边界"——以子进程方式运行真实 CLI，只验证外部可观察行为。
子进程环境与调用器在 tests/support.py（三个测试模块共用）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import codelotte
from tests.support import (
    PROJECT_ROOT,
    TIMEOUT_SECONDS,
    child_env,
    home_env,
    run_cli,
    write_user_config,
)


def test_version_flag_prints_version_and_exits_zero() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"codelotte {codelotte.__version__}"


def test_no_args_without_a_real_terminal_fails_readably(tmp_path: Path) -> None:
    """无参数 = 进 TUI（票据 05）：管道/CI 里没有真实终端时给可读错误，不往 stdout 喷转义码。"""
    env = _session_env(tmp_path)
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
    env = _session_env(tmp_path)
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
    """测试用子进程环境：配置全部写进临时 home 的用户级文件（不再有环境变量来源）。"""
    home = write_user_config(
        tmp_path / "home",
        session_dir=tmp_path / "sessions",
        api_key="test-key" if with_key else None,
    )
    return home_env(home)


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

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home", session_dir=tmp_path / "sessions")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
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

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home", session_dir=tmp_path / "sessions")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
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
    home = write_user_config(tmp_path / "home", session_dir=tmp_path / "sessions", api_key=None)
    env = home_env(home)
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
    """settings.json 配好了模型但没配密钥：报错要指路到 models.json 的 apiKey。"""
    home = write_user_config(tmp_path / "home", api_key=None)
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=home_env(home),
        cwd=tmp_path,  # 空目录；codelotte 不读取项目级配置
    )
    assert result.returncode == 2
    assert "API 密钥" in result.stderr and "models.json" in result.stderr  # 报错指路
    assert "Traceback" not in result.stderr


def test_missing_model_fails_with_readable_error(tmp_path: Path) -> None:
    """没有默认模型：settings.json 缺 "model" 就报错，并指引去用户级目录配置。"""
    home = write_user_config(tmp_path / "home", model=None)
    result = subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", "hi"],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=TIMEOUT_SECONDS,
        env=home_env(home),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "未配置模型" in result.stderr and "settings.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_trust_without_rules_file_says_no_need(tmp_path: Path) -> None:
    result = run_cli(
        "trust", cwd=tmp_path, env=home_env(tmp_path / "home")
    )
    assert result.returncode == 0
    assert "无需信任" in result.stdout


def test_trust_declined_keeps_rules_ignored(tmp_path: Path) -> None:
    (tmp_path / ".codelotte").mkdir()
    (tmp_path / ".codelotte" / "permissions.json").write_text(
        '{"deny": ["read"]}', encoding="utf-8"
    )
    home = tmp_path / "home"
    result = run_cli(
        "trust", cwd=tmp_path, env=child_env(CODELOTTE_HOME=str(home)), input_text="n\n"
    )
    assert result.returncode == 1
    assert "未信任——项目级规则继续被忽略" in result.stdout
    assert not (home / ".codelotte" / "trusted").exists()


def _rules_file(home: Path) -> Path:
    return home / ".codelotte" / "permissions.json"


def test_allow_subcommand_writes_user_rules_json(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = home_env(home)
    result = run_cli("allow", "read", "bash(git diff*)", cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    assert "追加" in result.stdout and "新增 2 条" in result.stdout
    data = json.loads(_rules_file(home).read_text(encoding="utf-8"))
    assert data == {"allow": ["read", "bash(git diff*)"], "ask": [], "deny": []}

    again = run_cli("allow", "read", cwd=tmp_path, env=env)  # 重复追加：跳过
    assert again.returncode == 0
    assert "已存在，跳过" in again.stdout
    data2 = json.loads(_rules_file(home).read_text(encoding="utf-8"))
    assert data2["allow"] == ["read", "bash(git diff*)"]


def test_ask_and_deny_subcommands_write_their_buckets(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = home_env(home)
    assert run_cli("ask", "bash(git push*)", cwd=tmp_path, env=env).returncode == 0
    assert run_cli("deny", "bash(curl*)", cwd=tmp_path, env=env).returncode == 0
    data = json.loads(_rules_file(home).read_text(encoding="utf-8"))
    assert data == {"allow": [], "ask": ["bash(git push*)"], "deny": ["bash(curl*)"]}


def test_permission_writer_rejects_bad_rule_without_writing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = home_env(home)
    result = run_cli("allow", "bash git diff", cwd=tmp_path, env=env)  # 缺括号
    assert result.returncode == 2
    assert "格式不对" in result.stderr
    assert not _rules_file(home).exists()  # 坏规则一条都不写


def test_permission_writer_project_flag_and_trust_hint(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    home = tmp_path / "home"
    env = home_env(home)
    result = run_cli("allow", "read", "--project", cwd=project, env=env)
    assert result.returncode == 0, result.stderr
    data = json.loads((project / ".codelotte" / "permissions.json").read_text(encoding="utf-8"))
    assert data["allow"] == ["read"]
    assert "codelotte trust" in result.stdout  # 提示先去信任
    assert not _rules_file(home).exists()  # 没写用户级


def test_permission_writer_refuses_to_clobber_broken_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _rules_file(home).parent.mkdir(parents=True)
    _rules_file(home).write_text("[1, 2]", encoding="utf-8")  # 损坏（顶层不是对象）
    env = home_env(home)
    result = run_cli("allow", "read", cwd=tmp_path, env=env)
    assert result.returncode == 1
    assert "先手动修好" in result.stderr
    assert _rules_file(home).read_text(encoding="utf-8") == "[1, 2]"  # 原文件不动
