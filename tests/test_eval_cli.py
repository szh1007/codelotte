"""压缩回归的 CLI 端到端（票据 13）：真实子进程 + 本地假 DeepSeek 服务器。

覆盖验收主句："一条命令跑出 3 条任务 × k 的报表"——这里用 1 条任务 × k=1
把命令链路（CLI → 真实 loop → 强制压缩 → checkpoint 探针 → 报表四件套）跑穿。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from tests.support import PROJECT_ROOT, home_env, run_cli, write_user_config

SUMMARY = (
    "1. 任务目标：生成 report.txt，统计 TODO 次数\n"
    "2. 已完成事项：读取 a.txt\n"
    "3. 关键决策及其理由：先读后写\n"
    "4. 活跃约束：按顺序输出，不要写其他内容\n"
    "5. 涉及文件清单：a.txt\n"
    "6. 当前未解决问题：还没写 report.txt\n"
    "7. 下一步：写 report.txt"
)
CHECKPOINT = (
    "1. 生成 report.txt，统计 TODO 次数。\n"
    "2. 读取了 a.txt。\n"
    "3. report.txt 必须按顺序输出，不要写其他内容。"
)
REPORT = "a.txt:2\nb.txt:1\nc.txt:0\n"


def _sse(*events: str) -> bytes:
    return b"".join(f"data: {event}\n\n".encode("utf-8") for event in events) + b"data: [DONE]\n\n"


def _text_turn(text: str) -> bytes:
    payload = json.dumps(
        {"choices": [{"delta": {"content": text}, "index": 0}]}, ensure_ascii=False
    )
    usage = json.dumps(
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    )
    return _sse(
        payload,
        '{"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
        usage,
    )


def _tool_turn(name: str, arguments: dict[str, object], call_id: str) -> bytes:
    payload = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(arguments, ensure_ascii=False),
                                },
                            }
                        ]
                    },
                    "index": 0,
                }
            ]
        },
        ensure_ascii=False,
    )
    usage = json.dumps(
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    )
    return _sse(
        payload,
        '{"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
        usage,
    )


def _handler(received: list[dict[str, Any]]):
    responses = [
        _tool_turn("read", {"path": "a.txt"}, "call_read"),
        _text_turn(SUMMARY),
        _text_turn(CHECKPOINT),  # 压缩事件后立即探针（早于下一次 agent 请求）
        _tool_turn(
            "write", {"path": "report.txt", "content": REPORT}, "call_write"
        ),
        _text_turn("完成"),
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            index = len(received)
            received.append(body)
            payload = responses[min(index, len(responses) - 1)]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def _serve() -> tuple[ThreadingHTTPServer, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(received))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def test_eval_compaction_command_writes_a_report_end_to_end(tmp_path: Path) -> None:
    server, received = _serve()
    port = server.server_address[1]
    try:
        home = write_user_config(
            tmp_path / "home", base_url=f"http://127.0.0.1:{port}", api_key="test-key"
        )
        out = tmp_path / "runs"
        result = run_cli(
            "eval",
            "compaction",
            "--k",
            "1",
            "--task",
            "001-audit-report",
            "--tasks",
            str(PROJECT_ROOT / "evals" / "tasks"),
            "--out",
            str(out),
            "--no-sandbox",
            cwd=PROJECT_ROOT,
            env=home_env(home),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    report_path = Path(result.stdout.strip())
    assert report_path == out / report_path.parent.name / "report.md"
    assert report_path.parent.parent == out  # 跑数落在 --out 下
    assert report_path.is_file()
    assert "001-audit-report" in report_path.read_text(encoding="utf-8")
    assert "k=1" in report_path.read_text(encoding="utf-8")

    run_dir = report_path.parent
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    (case,) = data["cases"]
    assert case["task_id"] == "001-audit-report"
    assert case["completed"] is True
    assert case["compactions"] == 1
    assert case["checkpoints"][0]["scores"][0]["passed"] is True
    assert (run_dir / "annotations.csv").is_file()
    assert (run_dir / "checkpoints.jsonl").is_file()

    # 请求顺序：读 → 摘要 → 探针 → 写 → 终答；探针无工具且拿到的是压缩后的上下文
    assert len(received) == 5
    probe = received[2]
    assert "tools" not in probe
    probe_messages = probe["messages"]
    assert probe_messages[0]["role"] == "system"
    assert "1. 任务目标" in probe_messages[0]["content"]
    assert "现在暂停任务" in probe_messages[-1]["content"]

    # 压缩后的写请求：旧指令不再逐字出现，system 摘要在最前
    write_request = received[3]["messages"]
    assert write_request[0]["role"] == "system"
    assert all(
        not (
            message.get("role") == "user"
            and "执行纪律" in str(message.get("content", ""))
        )
        for message in write_request
    )

    # 原始轨迹落盘，压缩 entry 可查
    sessions = list((run_dir / "sessions").rglob("*.jsonl"))
    assert len(sessions) == 1
    types = [json.loads(line)["type"] for line in sessions[0].read_text(encoding="utf-8").splitlines()]
    assert "compaction" in types


def _write_general_task(directory: Path, *, checkpoints: bool = False) -> Path:
    directory.mkdir()
    checkpoint = (
        """
[[checkpoints]]
question = "任务目标是什么？"
facts = [["out.txt"]]
"""
        if checkpoints
        else ""
    )
    (directory / "copy-file.toml").write_text(
        f"""
id = "copy-file"
bucket = "A"
instruction = "把 in.txt 的内容写到 out.txt"
[setup.files]
"in.txt" = "hello\\n"
[verifier]
[[verifier.files]]
path = "out.txt"
equals = "hello\\n"
{checkpoint}
""",
        encoding="utf-8",
    )
    return directory


def _serve_general_turns() -> tuple[ThreadingHTTPServer, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []
    responses = [
        _tool_turn("write", {"path": "out.txt", "content": "hello\n"}, "call_write"),
        _text_turn("done"),
        _tool_turn("write", {"path": "out.txt", "content": "hello\n"}, "call_write"),
        _text_turn("done"),
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            index = len(received)
            received.append(body)
            payload = responses[min(index, len(responses) - 1)]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def test_eval_run_command_writes_a_pass_pow_k_report_end_to_end(tmp_path: Path) -> None:
    tasks_dir = _write_general_task(tmp_path / "tasks")
    server, received = _serve_general_turns()
    port = server.server_address[1]
    try:
        home = write_user_config(
            tmp_path / "home", base_url=f"http://127.0.0.1:{port}", api_key="test-key"
        )
        out = tmp_path / "runs"
        result = run_cli(
            "eval",
            "run",
            "--repeat",
            "2",
            "--task",
            "copy-file",
            "--tasks",
            str(tasks_dir),
            "--out",
            str(out),
            "--no-sandbox",
            cwd=PROJECT_ROOT,
            env=home_env(home),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    report_path = Path(result.stdout.strip())
    assert report_path == out / report_path.parent.name / "report.md"
    assert report_path.is_file()
    markdown = report_path.read_text(encoding="utf-8")
    assert "pass^2" in markdown
    assert "copy-file" in markdown
    assert "✅" in markdown

    run_dir = report_path.parent
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert data["meta"]["repetitions"] == 2
    assert len(data["cases"]) == 2
    assert all(case["passed"] for case in data["cases"])
    assert data["summaries"][0]["pass_pow_k"] is True
    assert len(list((run_dir / "sessions").rglob("*.jsonl"))) == 2
    assert len(received) == 4


def test_eval_run_dry_run_does_not_require_a_model_or_create_a_run(
    tmp_path: Path,
) -> None:
    tasks_dir = _write_general_task(tmp_path / "tasks")
    home = write_user_config(
        tmp_path / "home", base_url="http://127.0.0.1:1", api_key="test-key"
    )

    result = run_cli(
        "eval",
        "run",
        "--repeat",
        "3",
        "--tasks",
        str(tasks_dir),
        "--out",
        str(tmp_path / "runs"),
        "--dry-run",
        cwd=PROJECT_ROOT,
        env=home_env(home),
    )

    assert result.returncode == 0, result.stderr
    assert "dry-run" in result.stdout
    assert "pass^3" in result.stdout
    assert not (tmp_path / "runs").exists()


def test_eval_run_bucket_filter_only_prints_the_selected_bucket(tmp_path: Path) -> None:
    home = write_user_config(
        tmp_path / "home", base_url="http://127.0.0.1:1", api_key="test-key"
    )

    result = run_cli(
        "eval",
        "run",
        "--dry-run",
        "--bucket",
        "B",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        cwd=PROJECT_ROOT,
        env=home_env(home),
    )

    assert result.returncode == 0, result.stderr
    assert "003-constrained-append" in result.stdout
    assert "004-prompt-injection-resistance" in result.stdout
    assert "005-scope-discipline" in result.stdout
    assert "001-audit-report" not in result.stdout


def _write_judge_task(directory: Path, *, samples: int = 20) -> Path:
    directory.mkdir()
    labels = directory / "samples.jsonl"
    labels.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"s{index:02d}",
                    "submission": f"sample {index}",
                    "human_pass": index < samples // 2,
                    "labeler": "author-draft",
                }
            )
            for index in range(samples)
        )
        + "\n",
        encoding="utf-8",
    )
    (directory / "calibration.json").write_text("{}\n", encoding="utf-8")
    (directory / "judge.toml").write_text(
        """
id = "judge-task"
bucket = "A"
instruction = "写 out.txt，并说明理由"
[setup.files]
"in.txt" = "x\\n"
[verifier]
[[verifier.files]]
path = "out.txt"
equals = "hello\\n"
[verifier.judge]
dimensions = ["correctness"]
rubric = "correctness: 内容正确"
pass_threshold = 0.6
samples = "tasks/samples.jsonl"
calibration = "tasks/calibration.json"
""",
        encoding="utf-8",
    )
    return directory


def test_eval_judge_dry_run_validates_the_sample_count(tmp_path: Path) -> None:
    tasks_dir = _write_judge_task(tmp_path / "tasks")
    home = tmp_path / "home"
    home.mkdir()

    result = run_cli(
        "eval",
        "judge",
        "--dry-run",
        "--tasks",
        str(tasks_dir),
        cwd=tmp_path,
        env=home_env(home),
    )

    assert result.returncode == 0, result.stderr
    assert "20 条样本" in result.stdout
    assert "dry-run" in result.stdout


def test_eval_judge_dry_run_rejects_fewer_than_twenty_samples(tmp_path: Path) -> None:
    tasks_dir = _write_judge_task(tmp_path / "tasks", samples=19)
    home = tmp_path / "home"
    home.mkdir()

    result = run_cli(
        "eval",
        "judge",
        "--dry-run",
        "--tasks",
        str(tasks_dir),
        cwd=tmp_path,
        env=home_env(home),
    )

    assert result.returncode == 2
    assert "20" in result.stderr


def _serve_judge_turns() -> tuple[ThreadingHTTPServer, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []
    agent_responses = [
        _tool_turn("write", {"path": "out.txt", "content": "hello\n"}, "call_write"),
        _text_turn("done"),
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            received.append(body)
            if "tools" in body:
                index = sum(1 for item in received[:-1] if "tools" in item)
                payload = agent_responses[min(index, len(agent_responses) - 1)]
            else:
                payload = _text_turn(
                    json.dumps(
                        {
                            "scores": {"correctness": 0.9},
                            "reasons": {"correctness": "内容正确"},
                        },
                        ensure_ascii=False,
                    )
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, received


def test_eval_run_runs_a_declared_judge_and_reports_its_scores(
    tmp_path: Path,
) -> None:
    tasks_dir = _write_judge_task(tmp_path / "tasks")
    server, received = _serve_judge_turns()
    port = server.server_address[1]
    try:
        home = write_user_config(
            tmp_path / "home", base_url=f"http://127.0.0.1:{port}", api_key="test-key"
        )
        out = tmp_path / "runs"
        result = run_cli(
            "eval",
            "run",
            "--task",
            "judge-task",
            "--repeat",
            "1",
            "--tasks",
            str(tasks_dir),
            "--out",
            str(out),
            "--no-sandbox",
            cwd=tmp_path,
            env=home_env(home),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    report_path = Path(result.stdout.strip())
    markdown = report_path.read_text(encoding="utf-8")
    assert "## LLM judge" in markdown
    assert "overall 0.90" in markdown
    assert "内容正确" in markdown
    assert "⚠ 不可靠" in markdown  # 没有真实校准文件
    data = json.loads((report_path.parent / "report.json").read_text(encoding="utf-8"))
    case = data["cases"][0]
    assert case["judge_used"] is True
    assert case["judge_passed"] is True
    assert case["judge_overall"] == 0.9
    assert case["judge_calls"] == 1
    assert case["judge_reliable"] is False
    assert case["model_calls"] == 3
    # 三次请求：两次 agent（带 tools）+ 一次 judge（不带 tools）
    assert sum(1 for body in received if "tools" in body) == 2
    assert sum(1 for body in received if "tools" not in body) == 1


def test_eval_controls_self_check_passes_without_a_model(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    out = tmp_path / "runs"

    result = run_cli(
        "eval",
        "controls",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        "--out",
        str(out),
        cwd=PROJECT_ROOT,
        env=home_env(home),
    )

    assert result.returncode == 0, result.stderr
    report_path = Path(result.stdout.strip())
    assert report_path.parent.parent == out
    markdown = report_path.read_text(encoding="utf-8")
    assert "控制 agent 自检" in markdown
    assert "自检结论" in markdown
    assert "oracle" in markdown and "no-op" in markdown and "cheating" in markdown
    data = json.loads((report_path.parent / "report.json").read_text(encoding="utf-8"))
    assert data["mode"] == "controls"
    assert data["checks"] and all(check["passed"] for check in data["checks"])
    # 每组都有自己的明细报表与轨迹
    for name in ("oracle", "no-op", "cheating"):
        assert (report_path.parent / "harnesses" / name / "report.md").is_file()
    assert list((report_path.parent / "harnesses" / "cheating" / "sessions").glob("*-cheating.json"))


def test_eval_compare_dry_run_does_not_need_a_model(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_cli(
        "eval",
        "compare",
        "--harness",
        "codelotte",
        "--harness",
        "raw",
        "--dry-run",
        "--tasks",
        str(PROJECT_ROOT / "evals" / "tasks"),
        "--out",
        str(tmp_path / "runs"),
        cwd=PROJECT_ROOT,
        env=home_env(home),
    )

    assert result.returncode == 0, result.stderr
    assert "2 组" in result.stdout
    assert "codelotte" in result.stdout and "raw" in result.stdout
    assert "dry-run" in result.stdout
    assert not (tmp_path / "runs").exists()


def test_eval_compare_runs_a_baseline_and_writes_a_comparison_report(
    tmp_path: Path,
) -> None:
    tasks_dir = _write_general_task(tmp_path / "tasks")
    server, received = _serve_general_turns()
    port = server.server_address[1]
    try:
        home = write_user_config(
            tmp_path / "home", base_url=f"http://127.0.0.1:{port}", api_key="test-key"
        )
        out = tmp_path / "runs"
        result = run_cli(
            "eval",
            "compare",
            "--harness",
            "raw",
            "--repeat",
            "1",
            "--task",
            "copy-file",
            "--tasks",
            str(tasks_dir),
            "--out",
            str(out),
            "--no-sandbox",
            cwd=PROJECT_ROOT,
            env=home_env(home),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    report_path = Path(result.stdout.strip())
    assert report_path.parent.parent == out
    markdown = report_path.read_text(encoding="utf-8")
    assert "对照组" in markdown
    assert "裸单轮 API" in markdown
    assert "copy-file" in markdown
    assert "❌" in markdown
    data = json.loads((report_path.parent / "report.json").read_text(encoding="utf-8"))
    assert data["mode"] == "compare"
    assert [item["name"] for item in data["harnesses"]] == ["raw"]
    assert data["harnesses"][0]["cases"][0]["passed"] is False
    assert len(received) == 1  # 裸单轮 API 只调用一次
    assert "tools" not in received[0]


def test_eval_compaction_rejects_tasks_without_checkpoints(tmp_path: Path) -> None:
    tasks_dir = _write_general_task(tmp_path / "tasks", checkpoints=False)
    home = write_user_config(
        tmp_path / "home", base_url="http://127.0.0.1:1", api_key="test-key"
    )

    result = run_cli(
        "eval",
        "compaction",
        "--dry-run",
        "--tasks",
        str(tasks_dir),
        cwd=PROJECT_ROOT,
        env=home_env(home),
    )

    assert result.returncode == 2
    assert "checkpoint" in result.stderr


def test_relative_out_keeps_sessions_outside_the_agent_workspace(tmp_path: Path) -> None:
    """审查发现：相对 --out 曾在 chdir 后解析，会话落进工作区并污染被测环境。"""
    server, _received = _serve()
    port = server.server_address[1]
    try:
        home = write_user_config(
            tmp_path / "home", base_url=f"http://127.0.0.1:{port}", api_key="test-key"
        )
        result = run_cli(
            "eval",
            "compaction",
            "--k",
            "1",
            "--task",
            "001-audit-report",
            "--tasks",
            str(PROJECT_ROOT / "evals" / "tasks"),
            "--out",
            "runs",
            "--no-sandbox",
            cwd=tmp_path,
            env=home_env(home),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    report = tmp_path / result.stdout.strip()
    assert report.is_file()
    run_dir = report.parent
    assert report.parent.parent == tmp_path / "runs"

    sessions = list((run_dir / "sessions").rglob("*.jsonl"))
    assert len(sessions) == 1
    assert not list((run_dir / "workspaces").rglob("*.jsonl"))
