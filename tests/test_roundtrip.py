"""端到端首穿测试（票据 02）：真实子进程 CLI + 本地假 DeepSeek 服务器。

覆盖验收：-p 流式打印、退出码 0、会话 JSONL 落盘（session/message/usage）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "DEEPSEEK_API_KEY": "test-key",
            "CODELOTTE_BASE_URL": f"http://127.0.0.1:{port}",
            "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
        }
        result = subprocess.run(
            [sys.executable, "-m", "codelotte", "-p", "用一句话解释递归"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=env,
            cwd=PROJECT_ROOT,
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


def _run_cli_against(port: int, prompt: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "DEEPSEEK_API_KEY": "test-key",
        "CODELOTTE_BASE_URL": f"http://127.0.0.1:{port}",
        "CODELOTTE_SESSION_DIR": str(tmp_path / "sessions"),
    }
    return subprocess.run(
        [sys.executable, "-m", "codelotte", "-p", prompt],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
        cwd=PROJECT_ROOT,
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
