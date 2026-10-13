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
