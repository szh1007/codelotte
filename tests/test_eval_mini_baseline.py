"""mini-swe-agent 对照组适配（票据 16）：外部进程 + 本地录制代理。

不依赖真正安装 mini-swe-agent：测试用一个假可执行脚本模拟它的行为（读环境、
请求 OpenAI 兼容端点、写轨迹、改工作区），从而验证适配层与代理的完整链路。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from codelotte.config import ConfigError
from codelotte.evals.execution import execute_harness
from codelotte.evals.mini_baseline import (
    MiniSweAgentHarness,
    resolve_mini_command,
)
from codelotte.evals.tasks import FileExpectation, Task, Verifier
from tests.fake_client import fake_catalog


def _upstream() -> tuple[ThreadingHTTPServer, list[dict[str, Any]]]:
    """假 DeepSeek：返回带缓存明细的 usage，并记录收到的 Authorization。"""
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            received.append(
                {
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            payload = json.dumps(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "prompt_cache_hit_tokens": 40,
                        "prompt_cache_miss_tokens": 60,
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


FAKE_MINI = r'''
import json
import os
import sys
import urllib.request
from pathlib import Path

args = sys.argv[1:]
output = Path(args[args.index("--output") + 1])
task = args[args.index("--task") + 1]
base = os.environ["OPENAI_API_BASE"].rstrip("/")
request = urllib.request.Request(
    base + "/chat/completions",
    data=json.dumps({"model": "fake-model", "messages": [{"role": "user", "content": task}]}).encode(),
    headers={
        "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    response.read()
Path("out.txt").write_text("hello\n", encoding="utf-8")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({
    "info": {
        "mini_version": "9.9.9",
        "exit_status": "Submitted",
        "model_stats": {"api_calls": 1, "instance_cost": 0.0},
    },
    "messages": [{"role": "assistant", "extra": {"cost": 0.0}}],
    "trajectory_format": "mini-swe-agent-1.1",
}), encoding="utf-8")
Path(os.environ["MSWEA_GLOBAL_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["MSWEA_GLOBAL_CONFIG_DIR"], "seen.json").write_text(
    json.dumps({
        "api_key": os.environ["OPENAI_API_KEY"],
        "base": os.environ["OPENAI_API_BASE"],
        "deepseek": os.environ.get("DEEPSEEK_API_KEY"),
        "cwd": os.getcwd(),
    }),
    encoding="utf-8",
)
'''


def _fake_mini(tmp_path: Path) -> Path:
    script = tmp_path / "fake_mini.py"
    script.write_text(FAKE_MINI, encoding="utf-8")
    return script


def _task() -> Task:
    return Task(
        id="mini-task",
        bucket="A",
        instruction="把 hello 写到 out.txt",
        setup={},
        verifier=Verifier(
            files=(FileExpectation(path="out.txt", equals="hello\n"),)
        ),
    )


def test_mini_harness_runs_agent_through_recording_proxy(tmp_path: Path) -> None:
    server, received = _upstream()
    port = server.server_address[1]
    env_home = tmp_path / "mini-home"
    script = _fake_mini(tmp_path)
    harness = MiniSweAgentHarness(
        model="fake-model",
        base_url=f"http://127.0.0.1:{port}",
        api_key="real-test-key",
        catalog=fake_catalog(),
        command=(sys.executable, str(script)),
        global_config_dir=env_home,
    )
    try:
        execution = asyncio.run(
            execute_harness(
                _task(),
                harness,
                workspace=tmp_path / "workspace",
                session_root=tmp_path / "sessions",
                repo_root=None,
                snapshot_ref=None,
            )
        )
    finally:
        server.shutdown()
        server.server_close()

    assert execution.completed is True
    assert execution.error is None
    assert execution.model_calls == 1
    assert execution.input_tokens == 100
    assert execution.output_tokens == 20
    # 40 命中 + 60 未命中 + 20 输出（fake_catalog 单价）
    assert execution.cost == pytest.approx(0.0002816)
    (period, count), = execution.periods
    assert period in {"peak", "offpeak"} and count == 1
    assert execution.harness_version == "9.9.9"
    assert execution.session_path is not None
    trajectory = Path(execution.session_path).read_text(encoding="utf-8")
    assert "mini-swe-agent-1.1" in trajectory

    # 子进程只看到代理的假 key；真 key 由代理注入上游
    seen = json.loads((env_home / "seen.json").read_text(encoding="utf-8"))
    assert seen["api_key"] == "codelotte-eval-proxy"
    assert seen["deepseek"] is None
    assert seen["base"].startswith("http://127.0.0.1:")
    assert seen["cwd"] == str((tmp_path / "workspace").resolve())
    assert received[0]["authorization"] == "Bearer real-test-key"
    assert received[0]["body"]["model"] == "fake-model"


def test_mini_harness_reports_missing_trajectory(tmp_path: Path) -> None:
    script = tmp_path / "no_trajectory.py"
    script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    harness = MiniSweAgentHarness(
        model="fake-model",
        base_url="http://127.0.0.1:1",
        api_key="real-test-key",
        catalog=fake_catalog(),
        command=(sys.executable, str(script)),
        global_config_dir=tmp_path / "mini-home",
    )

    execution = asyncio.run(
        execute_harness(
            _task(),
            harness,
            workspace=tmp_path / "workspace",
            session_root=tmp_path / "sessions",
            repo_root=None,
            snapshot_ref=None,
        )
    )

    assert execution.completed is False
    assert execution.error is not None
    assert "轨迹" in execution.error


def test_resolve_mini_command_prefers_explicit_python(tmp_path: Path) -> None:
    command = resolve_mini_command(mini_python=sys.executable)

    assert command == (sys.executable, str(Path(command[1])))
    assert Path(command[1]).name == "mini_runner.py"
    assert Path(command[1]).is_file()


def test_resolve_mini_command_rejects_a_missing_python(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="解释器不存在"):
        resolve_mini_command(mini_python=str(tmp_path / "no-python"))
