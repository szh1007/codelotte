"""mini-swe-agent 对照组（票据 16）：外部教学级 agent，同模型、同任务、同次数。

mini-swe-agent 不在项目依赖里（它带 litellm/datasets 等重依赖）：用
`uv tool install mini-swe-agent==2.4.6` 或 `--mini-python` 指定解释器即可。
适配层只做三件事：准备隔离环境、跑它的 CLI、把它的轨迹与真实 usage 读回来。

安全：被测 agent 的 bash 会继承子进程环境，所以真实 API key 不放进子进程；
子进程只拿到本地录制代理的假 key（见 `mini_proxy.py`）。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from codelotte.config import ConfigError
from codelotte.cost import Catalog, price_call
from codelotte.evals.harness_types import HarnessExecution
from codelotte.evals.mini_proxy import PROXY_KEY, RecordingProxy
from codelotte.evals.tasks import Task
from codelotte.providers.base import StreamUsage

logger = logging.getLogger(__name__)

MINI_PACKAGE = "mini-swe-agent"
MINI_COMMAND = "mini"
MINI_RUNNER = Path(__file__).with_name("mini_runner.py")
_SECRET_ENV = {
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
}


def _python_next_to(executable: str) -> str | None:
    """从 `<venv>/Scripts/mini.exe` 或 `<venv>/bin/mini` 推同环境的解释器。"""
    path = Path(executable)
    candidates = [path.with_name("python.exe"), path.with_name("python")]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_mini_command(*, mini_python: str | None = None) -> tuple[str, ...]:
    """决定用哪个解释器跑 mini 适配入口：显式解释器 > PATH 上 mini 的同环境解释器 > 当前解释器。"""
    if mini_python is not None:
        resolved = shutil.which(mini_python)
        if resolved is None:
            candidate = Path(mini_python)
            if not candidate.is_file():
                raise ConfigError(f"--mini-python 指向的解释器不存在：{mini_python}")
            resolved = str(candidate)
        if not MINI_RUNNER.is_file():
            raise ConfigError(f"mini 适配入口缺失：{MINI_RUNNER}")
        # 子进程的 cwd 是临时工作区：相对解释器路径必须先变成绝对路径，
        # 否则 Windows 上会以 FileNotFoundError 启动失败（票据 19 实测）。
        return (os.path.abspath(resolved), str(MINI_RUNNER))
    executable = shutil.which(MINI_COMMAND)
    if executable is not None:
        python = _python_next_to(executable)
        if python is not None:
            return (python, str(MINI_RUNNER))
        raise ConfigError(
            f"找到 {executable}，但推不出同环境的 Python 解释器；"
            "请用 --mini-python 指定装了 mini-swe-agent 的解释器"
        )
    if importlib.util.find_spec("minisweagent") is not None:
        return (sys.executable, str(MINI_RUNNER))
    raise ConfigError(
        f"未找到 {MINI_PACKAGE}：建议建独立 venv 安装（uv venv .mini-venv && "
        f"uv pip install --python .mini-venv/Scripts/python.exe {MINI_PACKAGE}==2.4.6），"
        "再用 --mini-python 指定该解释器；只跑另外两组可加 "
        "--harness codelotte --harness raw"
    )


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    """超时后杀整棵进程树（mini 会再起 bash 子进程）。"""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            timeout=15,
        )
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _tail(text: str, limit: int = 600) -> str:
    return text[-limit:] if len(text) > limit else text


def _mini_env(
    proxy: RecordingProxy,
    *,
    session_root: Path,
    case_name: str,
    global_config_dir: Path | None,
    max_model_calls: int,
) -> dict[str, str]:
    """构造 mini 子进程环境：去掉真实密钥与用户级 mini 配置，只留代理假 key。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _SECRET_ENV and not key.startswith("MSWEA_")
    }
    env.update(
        {
            "OPENAI_API_KEY": PROXY_KEY,
            "OPENAI_API_BASE": proxy.base_url,
            "OPENAI_BASE_URL": proxy.base_url,
            "MSWEA_GLOBAL_CONFIG_DIR": str(
                global_config_dir or session_root / f"{case_name}-mini-home"
            ),
            "MSWEA_GLOBAL_CALL_LIMIT": str(max_model_calls),
            "MSWEA_COST_TRACKING": "ignore_errors",
            "MSWEA_SILENT_STARTUP": "1",
            "MSWEA_CONFIGURED": "true",  # 跳过首次运行的交互式 setup

            "PYTHONUTF8": "1",
            "NO_COLOR": "1",
            "TERM": "dumb",
        }
    )
    return env


def _trajectory_info(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("mini 轨迹读不动：%s（%s: %s）", path, type(exc).__name__, exc)
        return {}
    info = payload.get("info") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        logger.warning("mini 轨迹缺少 info 对象：%s", path)
        return {}
    return info


@dataclass(frozen=True)
class MiniSweAgentHarness:
    """mini-swe-agent 的外部进程适配。"""

    model: str
    base_url: str
    api_key: str
    catalog: Catalog
    command: tuple[str, ...]
    reasoning_effort: str = "high"
    global_config_dir: Path | None = None
    name: str = "mini-swe-agent"
    kind: str = "agent"
    isolation: str = "local"

    async def run(
        self,
        task: Task,
        *,
        workspace: Path,
        session_root: Path,
        case_name: str,
    ) -> HarnessExecution:
        trajectory = session_root / f"{case_name}-mini.traj.json"
        log_path = session_root / f"{case_name}-mini.log"
        proxy = RecordingProxy(self.base_url, self.api_key)
        env = _mini_env(
            proxy,
            session_root=session_root,
            case_name=case_name,
            global_config_dir=self.global_config_dir,
            max_model_calls=task.max_model_calls,
        )
        args = [
            *self.command,
            "--model",
            self.model,
            "--task",
            task.instruction,
            "--output",
            str(trajectory),
            "--workspace",
            str(workspace),
            "--step-limit",
            str(task.max_model_calls),
            "--wall-time",
            str(max(1, int(task.timeout_seconds) - 5)),
            "--reasoning-effort",
            self.reasoning_effort,
        ]
        error: str | None = None
        output_text = ""
        with proxy:
            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=workspace,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                return HarnessExecution(
                    error=f"mini-swe-agent 无法启动：{type(exc).__name__}: {exc}",
                    harness_version=None,
                )
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(), timeout=task.timeout_seconds
                )
            except asyncio.TimeoutError:
                _kill_tree(process)
                try:
                    stdout, _ = await process.communicate()
                except Exception as exc:  # 进程已杀，管道可能已关闭；保留已读输出为空
                    logger.warning(
                        "mini 超时后回收输出失败：%s: %s", type(exc).__name__, exc
                    )
                    stdout = b""
                error = f"mini-swe-agent 超时（{task.timeout_seconds:g}s）"
            output_text = stdout.decode("utf-8", errors="replace")

        if process.returncode != 0 and error is None:
            error = (
                f"mini-swe-agent 退出码 {process.returncode}："
                f"{_tail(output_text)}"
            )
        records = proxy.records
        successful = [record for record in records if record.status == 200]
        if not trajectory.is_file():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(output_text, encoding="utf-8", newline="\n")
            if error is None:
                error = f"mini-swe-agent 未生成轨迹：{_tail(output_text)}"
            session_path = str(log_path)
            info: dict[str, object] = {}
        else:
            session_path = str(trajectory)
            info = _trajectory_info(trajectory)

        if not successful and error is None:
            if records:
                last = records[-1]
                error = f"mini-swe-agent 模型调用失败：{last.error or 'HTTP ' + str(last.status)}"
            else:
                error = "mini-swe-agent 没有记录到模型调用"

        cost = 0.0
        input_tokens = 0
        output_tokens = 0
        periods: dict[str, int] = {}
        for record in successful:
            input_tokens += record.input_tokens
            output_tokens += record.output_tokens
            priced = price_call(
                self.catalog,
                self.model,
                StreamUsage(
                    record.input_tokens,
                    record.output_tokens,
                    record.cache_hit_tokens,
                    record.cache_miss_tokens,
                ),
                at=record.at,
            )
            cost += priced.cost or 0.0
            periods[priced.period] = periods.get(priced.period, 0) + 1

        notes: list[str] = []
        exit_status = info.get("exit_status")
        if isinstance(exit_status, str) and exit_status:
            notes.append(f"exit_status={exit_status}")
        if not records:
            notes.append("代理未记录到调用")
        return HarnessExecution(
            model_calls=len(successful),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            periods=tuple(sorted(periods.items())),
            session_path=session_path,
            error=error,
            harness_version=(
                str(info["mini_version"]) if "mini_version" in info else None
            ),
            note="；".join(notes) or None,
        )
