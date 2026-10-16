"""端到端首穿测试（票据 02）：真实子进程 CLI + 本地假 DeepSeek 服务器。

覆盖验收：-p 流式打印、退出码 0、会话 JSONL 落盘（session/message/usage）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from tests.support import child_env, run_cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ANSWER_PARTS = ["递归", "就是", "函数调用自身。"]
SSE_BODY = (
    b"".join(
        b'data: {"choices":[{"delta":{"content":"' + part.encode("utf-8") + b'"},"index":0}]}\n\n'
        for part in ANSWER_PARTS
    )
    + b'data: {"choices":[{"delta":{},"finish_reason":"stop","index":0}]}\n\n'
    + b'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":11,'
    + b'"prompt_cache_hit_tokens":2,"prompt_cache_miss_tokens":5}}\n\n'
    + b"data: [DONE]\n\n"
)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(SSE_BODY)))
        self.end_headers()
        self.wfile.write(SSE_BODY)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_headless_roundtrip_streams_answer_and_writes_session(tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = run_cli(
            "-p", "用一句话解释递归", env=_server_env(port, tmp_path), cwd=PROJECT_ROOT
        )
        assert result.returncode == 0, result.stderr
        assert "".join(ANSWER_PARTS) in result.stdout

        session_files = list((tmp_path / "sessions").rglob("*.jsonl"))
        assert len(session_files) == 1
        lines = session_files[0].read_text(encoding="utf-8").splitlines()
        entries = [json.loads(x) for x in lines if x.strip()]
        types = [e["type"] for e in entries]
        assert types[0] == "session"
        assert types[-1] == "usage"
        user_msg = next(e for e in entries if e["type"] == "message" and e["role"] == "user")
        assert user_msg["content"] == "用一句话解释递归"
        assistant = next(e for e in entries if e["type"] == "message" and e["role"] == "assistant")
        assert assistant["content"] == "".join(ANSWER_PARTS)
        usage = entries[-1]
        assert usage["inputTokens"] == 7
        assert usage["outputTokens"] == 11
        assert usage["cacheHitTokens"] == 2
        assert usage["cacheMissTokens"] == 5
        # 票据 07：时段档 + 按当时价目表的估算 + 请求指纹（对账与缓存排查的原始数据）
        assert usage["period"] in {"peak", "offpeak"}
        rate = 1.0 if usage["period"] == "peak" else 0.5
        assert usage["cost"] == pytest.approx((2 * 0.04 + 5 * 2.0 + 11 * 8.0) / 1_000_000 * rate)
        assert re.fullmatch(r"[0-9a-f]{16}", usage["requestFingerprint"])
        # 会话结束打印分项账单（按模型/时段/缓存三类，会话累计口径）
        assert "账单（会话累计，人民币元）：1 次模型调用" in result.stderr
        assert "按模型  deepseek-flash 1 次" in result.stderr
        assert "按缓存" in result.stderr and "缓存命中率 29%" in result.stderr  # 2/(2+5)
    finally:
        server.shutdown()
        server.server_close()


def _serve_once(sse_body: bytes, handler_cls: type[BaseHTTPRequestHandler] | None = None):
    """起一个只服务一次请求的假服务器，返回 (server, port)。"""
    cls = handler_cls if handler_cls is not None else _make_body_handler(sse_body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def _make_body_handler(sse_body: bytes) -> type[BaseHTTPRequestHandler]:
    class _BodyHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(sse_body)))
            self.end_headers()
            self.wfile.write(sse_body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return _BodyHandler


def _server_env(port: int, tmp_path: Path) -> dict[str, str]:
    return child_env(
        DEEPSEEK_API_KEY="test-key",
        CODELOTTE_BASE_URL=f"http://127.0.0.1:{port}",
        CODELOTTE_SESSION_DIR=str(tmp_path / "sessions"),
    )


def _run_cli_against(
    port: int, prompt: str, tmp_path: Path, *extra_args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return run_cli(
        "-p",
        prompt,
        *extra_args,
        cwd=cwd if cwd is not None else PROJECT_ROOT,
        env=_server_env(port, tmp_path),
    )


def _load_entries(tmp_path: Path) -> list[dict]:
    session_files = list((tmp_path / "sessions").rglob("*.jsonl"))
    assert len(session_files) == 1
    lines = session_files[0].read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def _sse(*payloads: str) -> bytes:
    joined = "".join("data: " + payload + chr(10) + chr(10) for payload in payloads)
    return joined.encode("utf-8")


def test_reasoning_content_is_recorded(tmp_path: Path) -> None:
    body = _sse(
        '{"choices":[{"delta":{"reasoning_content":"先想"},"index":0}]}',
        '{"choices":[{"delta":{"reasoning_content":"再答"},"index":0}]}',
        '{"choices":[{"delta":{"content":"答案"},"index":0}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
        '{"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":5}}',
        "[DONE]",
    )
    server, port = _serve_once(body)
    try:
        result = _run_cli_against(port, "问题", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert "答案" in result.stdout
    assistant = next(
        e for e in _load_entries(tmp_path) if e["type"] == "message" and e["role"] == "assistant"
    )
    assert assistant["reasoningContent"] == "先想再答"
    assert assistant["content"] == "答案"
    assert "先想" not in result.stdout  # 默认不打印思考过程
    assert "先想" not in result.stderr


def test_show_reasoning_streams_to_stderr_without_polluting_stdout(tmp_path: Path) -> None:
    """-r/--reasoning：思考过程走 stderr，stdout 保持"只有答案"（可安全重定向/管道）。

    短 flag 写在提示词之后，同时覆盖 cli 的 argparse 透传路径（-p 打头但提示词不以 "-" 开头）。
    """
    body = _sse(
        '{"choices":[{"delta":{"reasoning_content":"先想"},"index":0}]}',
        '{"choices":[{"delta":{"reasoning_content":"再答"},"index":0}]}',
        '{"choices":[{"delta":{"content":"答案"},"index":0}]}',
        '{"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
        '{"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":5}}',
        "[DONE]",
    )
    server, port = _serve_once(body)
    try:
        result = _run_cli_against(port, "问题", tmp_path, "-r")
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert result.stdout == "答案\n"  # stdout 只有答案
    assert "先想再答\n\n" in result.stderr  # 思考结束后空一行再输出回答
    assert "\x1b" not in result.stderr  # 非终端不写 ANSI 转义序列


def test_dash_leading_prompt_is_accepted(tmp_path: Path) -> None:
    server, port = _serve_once(SSE_BODY)
    try:
        result = _run_cli_against(port, "--dry-run 是什么意思", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert "".join(ANSWER_PARTS) in result.stdout


def test_truncated_stream_saves_partial_answer_and_exits_nonzero(tmp_path: Path) -> None:
    class _TruncatingHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "100000")  # 声明很长，实际提前断开
            self.end_headers()
            self.wfile.write(_sse('{"choices":[{"delta":{"content":"前半"},"index":0}]}'))
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            pass

    server, port = _serve_once(b"", handler_cls=_TruncatingHandler)
    try:
        result = _run_cli_against(port, "问题", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 1
    assert "前半" in result.stdout  # 已打印的部分保留
    assistant = next(
        e for e in _load_entries(tmp_path) if e["type"] == "message" and e["role"] == "assistant"
    )
    assert assistant["content"] == "前半"
    assert assistant["stopReason"] == "interrupted"  # 记录是事实源：部分内容也落盘


def test_dotenv_is_loaded_without_env_file_flag(tmp_path: Path) -> None:
    """验收：项目目录里放好 .env 后，直接 `codelotte -p ...` 即可（无需 --env-file）。"""
    server, port = _serve_once(SSE_BODY)
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text(
        "DEEPSEEK_API_KEY=from-dotenv\n"
        f"CODELOTTE_BASE_URL=http://127.0.0.1:{port}\n"
        "CODELOTTE_SESSION_DIR=" + str(tmp_path / "sessions") + "\n",
        encoding="utf-8",
    )
    empty_home = tmp_path / "home"
    empty_home.mkdir()
    env = {
        "PYTHONUTF8": "1",
        "CODELOTTE_HOME": str(empty_home),
        "PATH": os.environ.get("PATH", ""),
        "SystemRoot": os.environ.get("SystemRoot", ""),
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "codelotte", "-p", "用一句话解释递归"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=env,
            cwd=project,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert "".join(ANSWER_PARTS) in result.stdout
    assert len(list((tmp_path / "sessions").rglob("*.jsonl"))) == 1


def test_continue_resumes_previous_session_without_loss_or_duplication(tmp_path: Path) -> None:
    """--continue（票据 05 验收）：第二个进程重建上一轮的上下文、续写同一会话文件。"""
    project = tmp_path / "proj"
    project.mkdir()
    handler_cls, _received = _scripted_handler([_answer_turn("第一答")])
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        first = _run_cli_against(port, "第一问", tmp_path, cwd=project)
    finally:
        server.shutdown()
        server.server_close()
    assert first.returncode == 0, first.stderr

    handler_cls2, received2 = _scripted_handler([_answer_turn("第二答")])
    server2, port2 = _serve_once(b"", handler_cls=handler_cls2)
    try:
        second = _run_cli_against(port2, "第二问", tmp_path, "--continue", cwd=project)
    finally:
        server2.shutdown()
        server2.server_close()
    assert second.returncode == 0, second.stderr
    assert second.stdout == "第二答\n"

    # 重建的上下文被原样发给模型：上一轮完整对话 + 新问题
    messages = received2[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "第一问"
    assert messages[1]["content"] == "第一答"
    assert messages[2]["content"] == "第二问"

    # 同一个会话文件：两问两答，不重不漏
    session_files = list((tmp_path / "sessions").rglob("*.jsonl"))
    assert len(session_files) == 1
    entries = [json.loads(x) for x in session_files[0].read_text(encoding="utf-8").splitlines() if x.strip()]
    users = [e["content"] for e in entries if e["type"] == "message" and e["role"] == "user"]
    assistants = [e["content"] for e in entries if e["type"] == "message" and e["role"] == "assistant"]
    assert users == ["第一问", "第二问"]
    assert assistants == ["第一答", "第二答"]


def _scripted_handler(
    bodies: list[bytes],
) -> tuple[type[BaseHTTPRequestHandler], list[dict]]:
    """按序应答的假服务器 handler；返回 (handler 类, 收到的请求体列表)。

    请求数超出剧本时复用最后一个 body（迭代上限类测试需要"永远调工具"的服务器）。
    """
    received: list[dict] = []

    class _ScriptedHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            body = bodies[min(len(received) - 1, len(bodies) - 1)]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return _ScriptedHandler, received


def _tool_call_turn(tool_name: str, arguments: dict, call_id: str = "call_r1") -> bytes:
    """一轮"请求调用工具"的 SSE 回复（带思考与用量）。"""
    payload = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "先读文件",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "type": "function",
                                "function": {"name": tool_name, "arguments": json.dumps(arguments)},
                            }
                        ],
                    },
                    "index": 0,
                }
            ]
        }
    )
    return _sse(
        payload,
        '{"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
        '{"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}',
        "[DONE]",
    )


def _answer_turn(text: str) -> bytes:
    return _sse(
        json.dumps({"choices": [{"delta": {"content": text}, "index": 0}]}),
        '{"choices":[{"delta":{},"finish_reason":"stop","index":0}]}',
        '{"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":8}}',
        "[DONE]",
    )


def test_agent_loop_reads_file_and_answers(tmp_path: Path) -> None:
    """验收：模型触发 read 拿到真实文件内容；工具调用与结果成对落盘；stdout 只有回答。"""
    handler_cls, received = _scripted_handler(
        [
            _tool_call_turn("read", {"path": "CONTEXT.md"}),
            _answer_turn("第一行是 # codelotte"),
        ]
    )
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "读一下 CONTEXT.md 并告诉我第一行", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout == "第一行是 # codelotte\n"  # stdout 只有答案：思考与工具活动都在 stderr
    assert "→ read(" in result.stderr
    assert "← read" in result.stderr
    assert "calls=2" in result.stderr

    # 第二次请求：assistant 回传了 tool_calls 与 reasoning_content（deepseek 带 tools 时必须回传），
    # 且带上了工具结果（role=tool，内容来自真实读取的 CONTEXT.md）
    assert len(received) == 2
    messages = received[1]["messages"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["reasoning_content"] == "先读文件"
    assert messages[1]["tool_calls"][0]["id"] == "call_r1"
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == json.dumps({"path": "CONTEXT.md"})
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_r1"
    assert "1\t# codelotte" in messages[2]["content"]

    entries = _load_entries(tmp_path)
    assert [e["type"] for e in entries] == [
        "session",
        "message",  # user
        "message",  # assistant（含工具调用）
        "usage",
        "tool_call",
        "tool_result",
        "message",  # 最终回答
        "usage",
    ]
    assistant_with_call = entries[2]
    assert assistant_with_call["content"] == ""
    assert assistant_with_call["stopReason"] == "tool_calls"
    assert assistant_with_call["reasoningContent"] == "先读文件"
    assert assistant_with_call["toolCalls"] == [
        {"id": "call_r1", "name": "read", "arguments": json.dumps({"path": "CONTEXT.md"})}
    ]
    tool_call_entry = entries[4]
    assert tool_call_entry["toolCallId"] == "call_r1"
    assert tool_call_entry["name"] == "read"
    assert tool_call_entry["arguments"] == {"path": "CONTEXT.md"}
    tool_result_entry = entries[5]
    assert tool_result_entry["toolCallId"] == "call_r1"
    assert tool_result_entry["ok"] is True
    assert tool_result_entry["content"].startswith("CONTEXT.md（第 1-")
    assert isinstance(tool_result_entry["durationMs"], int)
    # 每个 usage 属于一次模型调用：in=10+20
    usages = [e for e in entries if e["type"] == "usage"]
    assert [u["inputTokens"] for u in usages] == [10, 20]


def test_tool_error_is_fed_back_and_loop_recovers(tmp_path: Path) -> None:
    """验收：读取失败（文件不存在）不是系统错误——错误文本回传模型，循环继续。"""
    handler_cls, received = _scripted_handler(
        [
            _tool_call_turn("read", {"path": "no-such-file.txt"}),
            _answer_turn("那个文件不存在。"),
        ]
    )
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "读一下 no-such-file.txt", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout == "那个文件不存在。\n"
    feedback = received[1]["messages"][2]["content"]
    assert feedback.startswith("错误：")
    assert "文件不存在" in feedback
    tool_result_entry = next(e for e in _load_entries(tmp_path) if e["type"] == "tool_result")
    assert tool_result_entry["ok"] is False


def test_iteration_cap_forces_turn_end(tmp_path: Path) -> None:
    """验收：迭代硬上限兜底——模型永远请求工具时，回合被强制结束并记为事件。"""
    from codelotte.loop import MAX_ITERATIONS

    handler_cls, received = _scripted_handler([_tool_call_turn("read", {"path": "CONTEXT.md"})])
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "无限读文件", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 1
    assert f"已达迭代上限 {MAX_ITERATIONS} 轮" in result.stderr
    assert len(received) == MAX_ITERATIONS
    entries = _load_entries(tmp_path)
    assert entries[-1]["type"] == "event"
    assert entries[-1]["kind"] == "iterationLimit"
    assert entries[-1]["iterations"] == MAX_ITERATIONS
    assert sum(1 for e in entries if e["type"] == "tool_call") == MAX_ITERATIONS


def test_malformed_parallel_call_is_fed_back_while_sibling_executes(tmp_path: Path) -> None:
    """一个坏调用不拖垮并行的好调用：畸形参数回传错误让模型自纠，好调用照常执行。"""
    malformed_turn = _sse(
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "bad",
                                    "type": "function",
                                    "function": {"name": "read", "arguments": '{"path": '},
                                },
                                {
                                    "index": 1,
                                    "id": "good",
                                    "type": "function",
                                    "function": {
                                        "name": "read",
                                        "arguments": json.dumps({"path": "CONTEXT.md", "limit": 1}),
                                    },
                                },
                            ]
                        },
                        "index": 0,
                    }
                ]
            }
        ),
        '{"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
        "[DONE]",
    )
    handler_cls, received = _scripted_handler([malformed_turn, _answer_turn("好")])
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "读文件", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout == "好\n"
    messages = received[1]["messages"]
    # assistant 原样回传两个调用（含畸形那个的原始文本——回传雷区要求逐字节一致）
    assert [c["id"] for c in messages[1]["tool_calls"]] == ["bad", "good"]
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == '{"path": '
    # 坏调用收到错误结果、好调用拿到真实文件内容
    assert messages[2]["tool_call_id"] == "bad"
    assert messages[2]["content"].startswith("错误：")
    assert messages[3]["tool_call_id"] == "good"
    assert "1\t# codelotte" in messages[3]["content"]

    entries = _load_entries(tmp_path)
    bad_call = next(e for e in entries if e["type"] == "tool_call" and e["toolCallId"] == "bad")
    assert bad_call["parseError"]
    assert bad_call["arguments"] == '{"path": '  # 无法解析时记原始文本
    bad_result = next(e for e in entries if e["type"] == "tool_result" and e["toolCallId"] == "bad")
    assert bad_result["ok"] is False
    good_result = next(e for e in entries if e["type"] == "tool_result" and e["toolCallId"] == "good")
    assert good_result["ok"] is True


def test_intermediate_narration_goes_to_stderr_not_stdout(tmp_path: Path) -> None:
    """管道/重定向下 stdout 只有终轮答案：中间轮次的过渡叙述走 stderr。"""
    narration_turn = _sse(
        json.dumps(
            {
                "choices": [
                    {
                        "delta": {
                            "content": "我先读一下这个文件。",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "read",
                                        "arguments": json.dumps({"path": "CONTEXT.md", "limit": 1}),
                                    },
                                }
                            ],
                        },
                        "index": 0,
                    }
                ]
            }
        ),
        '{"choices":[{"delta":{},"finish_reason":"tool_calls","index":0}]}',
        "[DONE]",
    )
    handler_cls, _received = _scripted_handler([narration_turn, _answer_turn("第一行是 # codelotte。")])
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "读文件", tmp_path)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout == "第一行是 # codelotte。\n"  # 答案通道纯净
    assert "我先读一下这个文件。" in result.stderr  # 叙述不丢，在 stderr
    entries = _load_entries(tmp_path)
    narrated = entries[2]
    assert narrated["content"] == "我先读一下这个文件。"
    assert narrated["toolCalls"][0]["id"] == "c1"


def _run_cli_list(tmp_path: Path, project: Path) -> subprocess.CompletedProcess[str]:
    """`--resume`（无序号）：只读列出可恢复的会话/分支（不需要假服务器）。"""
    env = child_env(
        DEEPSEEK_API_KEY="test-key", CODELOTTE_SESSION_DIR=str(tmp_path / "sessions")
    )
    return run_cli("--resume", cwd=project, env=env)


def _one_turn(
    tmp_path: Path, project: Path, answer: str, prompt: str, *extra_args: str
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    """跑一次真实 CLI（单轮问答），返回 (进程结果, 假服务器收到的请求体)。"""
    handler_cls, received = _scripted_handler([_answer_turn(answer)])
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, prompt, tmp_path, *extra_args, cwd=project)
    finally:
        server.shutdown()
        server.server_close()
    return result, received


def test_fork_and_resume_keep_two_branches_independent(tmp_path: Path) -> None:
    """验收（票据 06）：fork 之后两条分支各自 --continue/--resume，互不污染（真实 CLI 全链路）。"""
    project = tmp_path / "proj"
    project.mkdir()

    # 线性两问两答：Q1 A1 Q2 A2
    first, _ = _one_turn(tmp_path, project, "第一答", "第一问")
    assert first.returncode == 0, first.stderr
    second, _ = _one_turn(tmp_path, project, "第二答", "第二问", "--continue")
    assert second.returncode == 0, second.stderr

    # --fork 2：在"第二问"处分岔——请求里不该再出现"第二答"
    fork_run, fork_received = _one_turn(tmp_path, project, "方案B答", "换个方案", "--fork", "2")
    assert fork_run.returncode == 0, fork_run.stderr
    assert [m["content"] for m in fork_received[0]["messages"]] == [
        "第一问",
        "第一答",
        "第二问",
        "换个方案",
    ]

    # --resume 列表：两条分支各一行，分支行带标注、排在前面（活动更新）
    listing = _run_cli_list(tmp_path, project)
    assert listing.returncode == 0, listing.stderr
    assert "可恢复的会话/分支（2 个）" in listing.stdout
    assert listing.stdout.count("⎇ 分支（fork 于 ") == 1
    assert "第一问" in listing.stdout

    # --continue 回到最后说话的分支（新分支）：请求含"换个方案"，不含"第二答"
    branch_run, branch_received = _one_turn(tmp_path, project, "分支续答", "分支续问", "--continue")
    assert branch_run.returncode == 0, branch_run.stderr
    assert [m["content"] for m in branch_received[0]["messages"]] == [
        "第一问",
        "第一答",
        "第二问",
        "换个方案",
        "方案B答",
        "分支续问",
    ]

    # --resume 2 回到主线老分支：请求完整重建线性历史，分支的记录一条都不在
    main_run, main_received = _one_turn(tmp_path, project, "主线续答", "主线续问", "--resume", "2")
    assert main_run.returncode == 0, main_run.stderr
    assert [m["content"] for m in main_received[0]["messages"]] == [
        "第一问",
        "第一答",
        "第二问",
        "第二答",
        "主线续问",
    ]

    # --resume 2 --fork 1：在第 2 行（现在 = 分叉分支）上再分岔——组合形式覆盖"非最近分支"
    combo_run, combo_received = _one_turn(
        tmp_path, project, "组合答", "组合问", "--resume", "2", "--fork", "1"
    )
    assert combo_run.returncode == 0, combo_run.stderr
    assert [m["content"] for m in combo_received[0]["messages"]] == [
        "第一问",
        "第一答",
        "第二问",
        "换个方案",
        "方案B答",
        "分支续问",
        "分支续答",
        "组合问",
    ]  # 操作对象是分叉分支，不是主线

    # 文件层面：同一棵树上两条链，各自的叶子都还在（互不污染）
    entries = _load_entries(tmp_path)
    assert sum(1 for e in entries if e["type"] == "event" and e.get("kind") == "fork") == 2
    users = [e["content"] for e in entries if e.get("role") == "user"]
    assert users == ["第一问", "第二问", "换个方案", "分支续问", "主线续问", "组合问"]


def test_agent_writes_edits_and_verifies_with_bash(tmp_path: Path) -> None:
    """验收：agent 修改真实文件并运行命令验证改动（write → edit → bash 全链路，本地模式）。"""
    project = tmp_path / "proj"
    project.mkdir()
    # 验证命令要跟执行器实际选用的 shell 一致：Windows 优先 Git Bash（cat 可用），
    # 找不到 Git Bash、退回 cmd 时才用 type
    from codelotte.sandbox.local import _find_git_bash

    use_cmd = os.name == "nt" and _find_git_bash() is None
    verify_cmd = "type hello.txt" if use_cmd else "cat hello.txt"
    handler_cls, received = _scripted_handler(
        [
            _tool_call_turn("write", {"path": "hello.txt", "content": "你好\n"}, call_id="w1"),
            _tool_call_turn(
                "edit",
                {"path": "hello.txt", "old_string": "你好", "new_string": "你好，世界"},
                call_id="e1",
            ),
            _tool_call_turn("bash", {"command": verify_cmd}, call_id="b1"),
            _answer_turn("已完成"),
        ]
    )
    server, port = _serve_once(b"", handler_cls=handler_cls)
    try:
        result = _run_cli_against(port, "创建 hello.txt 并改成问候", tmp_path, cwd=project)
    finally:
        server.shutdown()
        server.server_close()

    assert result.returncode == 0, result.stderr
    assert result.stdout == "已完成\n"
    assert (project / "hello.txt").read_text(encoding="utf-8") == "你好，世界\n"
    # 第四次请求里：bash 的真实输出被回填（验证链路闭环）
    assert len(received) == 4
    assert "你好，世界" in received[3]["messages"][-1]["content"]

    entries = _load_entries(tmp_path)
    tool_calls = [e for e in entries if e["type"] == "tool_call"]
    assert [e["name"] for e in tool_calls] == ["write", "edit", "bash"]
    assert all(e["env"] == "local" for e in tool_calls)  # 执行环境可审计（SPEC §E）
    results = [e for e in entries if e["type"] == "tool_result"]
    assert [e["ok"] for e in results] == [True, True, True]
    assert all(e["env"] == "local" for e in results)
