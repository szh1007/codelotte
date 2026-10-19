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
from codelotte.evals.tasks import load_tasks
from tests.support import (
    PROJECT_ROOT,
    TIMEOUT_SECONDS,
    child_env,
    home_env,
    run_cli,
    sessions_dir,
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


def test_no_sandbox_flag_parses() -> None:
    from codelotte.cli import build_parser

    parser = build_parser()
    assert parser.parse_args([]).no_sandbox is False
    assert parser.parse_args(["--no-sandbox"]).no_sandbox is True


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
    assert not sessions_dir(tmp_path / "home").exists()


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


def test_resume_list_warns_about_damaged_and_lists_healthy(tmp_path: Path) -> None:
    """回归（审查发现）：损坏的会话要被跳过并警告，健康的会话不受牵连。"""
    from codelotte.session.store import SessionStore

    home = write_user_config(tmp_path / "home")
    store = SessionStore.start(tmp_path, base_dir=sessions_dir(home))
    store.append("message", role="user", content="好的会话")
    (store.path.parent / "20990101T000000Z_damaged0.jsonl").write_text(
        '{"id": "x", "parentId": "zzz", "type": "session"}\n', encoding="utf-8"
    )

    result = _cli(tmp_path, "--resume")
    assert result.returncode == 0
    assert "警告：跳过损坏的会话" in result.stderr
    assert "好的会话" in result.stdout


def test_build_agent_defaults_to_docker_and_honors_no_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认沙箱是 Docker；显式 --no-sandbox 才换成本地执行器（票据 10）。"""
    from codelotte.cli import _build_agent
    from codelotte.sandbox import DockerExecutor, LocalExecutor

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    _loop, _spec, sandboxed = _build_agent()
    assert isinstance(sandboxed, DockerExecutor)
    _loop, _spec, local = _build_agent(no_sandbox=True)
    assert isinstance(local, LocalExecutor)


def test_build_agent_applies_guardrail_limits_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """票据 11：settings.json 的四档阈值进 AgentLoop；没写用默认值。"""
    from codelotte.cli import _build_agent
    from codelotte.guardrails import GuardrailLimits

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    loop, _spec, _executor = _build_agent()
    assert loop.guardrail_limits == GuardrailLimits()

    home = write_user_config(
        tmp_path / "home2",
        settings_extra={
            "guardrailRepeatLimit": 5,
            "guardrailStagnationLimit": 3,
            "guardrailFailureLimit": 4,
            "guardrailPlanningLimit": 2,
        },
    )
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    loop, _spec, _executor = _build_agent()
    assert loop.guardrail_limits == GuardrailLimits(
        repeat=5, stagnation=3, failure=4, planning=2
    )


def test_build_agent_passes_the_effective_context_window_to_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """票据 12 预置决策：压缩分母 = 用户级生效窗口，必须与 TUI 状态栏同源。"""
    from codelotte.cli import _build_agent

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home", context_window=1234)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    loop, spec, _executor = _build_agent()
    assert spec.context_window == 1234
    assert loop.context_window == 1234


def test_build_agent_applies_compaction_thresholds_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """票据 12：压缩软/硬阈值从 settings.json 进 loop；没写用 0.60/0.85。"""
    from codelotte.cli import _build_agent
    from codelotte.compaction import CompactionLimits

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))

    loop, _spec, _executor = _build_agent()
    assert loop.compaction_limits == CompactionLimits()

    home = write_user_config(
        tmp_path / "home2",
        settings_extra={
            "compactionSoftThreshold": 0.5,
            "compactionHardThreshold": 0.8,
        },
    )
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    loop, _spec, _executor = _build_agent()
    assert loop.compaction_limits == CompactionLimits(soft=0.5, hard=0.8)


def test_build_agent_history_follows_selected_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TUI 回放回归：--fork 之后按 leaf_id 取到的历史只含活动分支——不能把其它分支也画出来。"""
    from codelotte.cli import _build_agent
    from codelotte.session.store import SessionStore, load_branch

    monkeypatch.chdir(tmp_path)
    home = write_user_config(tmp_path / "home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    store = SessionStore.start(tmp_path, base_dir=sessions_dir(home))
    store.append("message", role="user", content="第一问")
    store.append("message", role="assistant", content="第一答", model="m", stopReason="stop")
    store.append("message", role="user", content="第二问")

    loop, _spec, _executor = _build_agent(fork_from_end=2)  # 在"第一答"处分岔
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
    home = write_user_config(tmp_path / "home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    store = SessionStore.start(tmp_path, base_dir=sessions_dir(home))
    store.append("message", role="user", content="好的会话")
    (store.path.parent / "20990101T000000Z_damaged0.jsonl").write_text(
        '{"id": "x", "parentId": "zzz", "type": "session"}\n', encoding="utf-8"
    )

    loop, _spec, _executor = _build_agent(resume_index=1)
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
    home = write_user_config(tmp_path / "home", api_key=None)
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
    sessions = sessions_dir(home)
    assert not (sessions.exists() and list(sessions.rglob("*.jsonl")))


def test_version_matches_pyproject() -> None:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == codelotte.__version__


def test_missing_api_key_fails_with_readable_error(tmp_path: Path) -> None:
    """provider 配好了端点但没配密钥：报错要指路到 models.json 的 apiKey。"""
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
    assert "providers.deepseek 缺少 apiKey" in result.stderr
    assert "models.json" in result.stderr  # 报错指路
    assert "Traceback" not in result.stderr


def test_missing_default_model_fails_with_readable_error(tmp_path: Path) -> None:
    """没有默认模型：settings.json 缺 "defaultModel" 就报错，并列出可选项。"""
    home = write_user_config(tmp_path / "home", default_model=None)
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
    assert "未配置默认模型" in result.stderr and "defaultModel" in result.stderr
    assert "deepseek-flash" in result.stderr  # 列出可选值
    assert "Traceback" not in result.stderr


def test_read_only_commands_leave_settings_untouched(tmp_path: Path) -> None:
    """只读命令（--resume/export/trust）不改用户文件：版本水位只在真正跑一次时写回。"""
    home = write_user_config(
        tmp_path / "home", settings_extra={"lastChangelogVersion": "0.0.1"}
    )
    result = run_cli("--resume", cwd=tmp_path, env=home_env(home))
    assert result.returncode == 0
    data = json.loads((home / ".codelotte" / "settings.json").read_text(encoding="utf-8"))
    assert data["lastChangelogVersion"] == "0.0.1"  # 原样不动
    assert data["defaultModel"] == "deepseek-flash"
    assert "更新内容" not in result.stderr  # 只读命令也不打更新提示


def test_broken_settings_fail_readably_without_traceback(tmp_path: Path) -> None:
    """回归（审查发现）：坏 settings.json（如写回被打断）给可读错误 + 退出码 2，不裸 traceback。"""
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "settings.json").write_text("{ broken", encoding="utf-8")
    result = run_cli("--resume", cwd=tmp_path, env=home_env(home))
    assert result.returncode == 2
    assert "不是合法 JSON" in result.stderr
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
    result = run_cli("trust", cwd=tmp_path, env=home_env(home), input_text="n\n")
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


def test_eval_compaction_parser_defaults() -> None:
    from codelotte.cli import build_parser

    args = build_parser().parse_args(
        ["eval", "compaction", "--task", "001-audit-report", "--no-sandbox"]
    )
    assert args.command == "eval" and args.eval_command == "compaction"
    assert args.k == "0,1,3,5"
    assert args.repeat == 1 and args.seed == 0
    assert args.no_sandbox is True
    assert args.task == ["001-audit-report"]


def test_eval_run_parser_defaults() -> None:
    from codelotte.cli import build_parser

    args = build_parser().parse_args(
        [
            "eval",
            "run",
            "--bucket",
            "B",
            "--task",
            "004-prompt-injection-resistance",
            "--no-sandbox",
        ]
    )
    assert args.command == "eval" and args.eval_command == "run"
    assert args.repeat == 3 and args.seed == 0
    assert args.bucket == ["B"]
    assert args.task == ["004-prompt-injection-resistance"]
    assert args.no_sandbox is True


def test_eval_compaction_rejects_duplicate_k_readably(tmp_path: Path) -> None:
    """一条命令的入口：坏参数给可读错误 + 退出码 2，不裸 traceback。"""
    result = run_cli(
        "eval",
        "compaction",
        "--k",
        "1,3,1",
        "--no-sandbox",
        cwd=tmp_path,
        env=_session_env(tmp_path),
    )
    assert result.returncode == 2
    assert "--k 不能有重复值" in result.stderr
    assert "Traceback" not in result.stderr


def test_eval_compaction_reports_missing_task_id(tmp_path: Path) -> None:
    result = run_cli(
        "eval",
        "compaction",
        "--k",
        "0",
        "--task",
        "no-such-task",
        "--no-sandbox",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        "--out",
        str(tmp_path / "runs"),
        cwd=tmp_path,
        env=_session_env(tmp_path),
    )
    assert result.returncode == 2
    assert "没有这些任务 id" in result.stderr
    assert "001-audit-report" in result.stderr


def test_eval_compaction_dry_run_validates_tasks_without_calling_models(
    tmp_path: Path,
) -> None:
    """新增/修改任务后先 dry-run：只校验 TOML 并打印计划，不花钱、不建 run 目录。"""
    result = run_cli(
        "eval",
        "compaction",
        "--dry-run",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        cwd=tmp_path,
        env=_session_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    task_count = len(load_tasks(PROJECT_ROOT / "evals" / "tasks"))
    assert (
        f"计划：{task_count} 任务 × 4 个 k × 1 个组合 × 1 次重复 = "
        f"{task_count * 4} 条案例"
        in result.stdout
    )
    assert "001-audit-report" in result.stdout
    assert "dry-run" in result.stdout
    assert not (tmp_path / "evals" / "runs").exists()


def test_eval_compaction_dry_run_lists_strategy_template_matrix(
    tmp_path: Path,
) -> None:
    result = run_cli(
        "eval",
        "compaction",
        "--dry-run",
        "--combo",
        "minimal:seven",
        "--combo",
        "wide:compact",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        cwd=tmp_path,
        env=_session_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "2 个组合" in result.stdout
    assert "minimal/seven" in result.stdout
    assert "wide/compact" in result.stdout
