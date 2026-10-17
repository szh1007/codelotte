"""mini-swe-agent 对照组的本地录制代理（票据 16）。

为什么需要它：
- mini-swe-agent / litellm 通过环境变量拿 API key；它的 bash 环境继承整个进程环境，
  真 key 会暴露给被测 agent。代理让子进程只看到假 key，真 key 只留在本进程内存里。
- 代理顺手记录每次上游调用的实际 usage 与时刻，成本按我们自己的峰谷价目表计算，
  不依赖 litellm 是否认识 DeepSeek 这个模型。

代理只监听 127.0.0.1；不记录请求体（避免把 prompt/密钥写进报表）。
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)

PROXY_KEY = "codelotte-eval-proxy"
_DEFAULT_TIMEOUT = 180.0


@dataclass(frozen=True)
class ProxyRecord:
    """一次上游调用（成功或失败）的记账事实。"""

    at: datetime
    model: str
    status: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    error: str | None = None


def _usage_from_json(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    usage = payload.get("usage")
    return usage if isinstance(usage, dict) else {}


def _usage_from_sse(data: bytes, content_type: str) -> dict[str, Any]:
    """从 SSE 响应里找最后一个 usage 帧（非流式调用走不到这里）。"""
    if "text/event-stream" not in content_type:
        try:
            return _usage_from_json(json.loads(data))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning(
                "代理收到无法解析的响应体（usage 记 0）：%s: %s",
                type(exc).__name__,
                exc,
            )
            return {}
    usage: dict[str, Any] = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            logger.warning("代理跳过无法解析的 SSE 帧（usage 可能缺失）：%s", exc)
            continue
        frame_usage = _usage_from_json(payload)
        if frame_usage:
            usage = frame_usage
    return usage


def _token_counts(usage: dict[str, Any]) -> tuple[int, int, int, int]:
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    details = usage.get("prompt_tokens_details")
    if not hit and isinstance(details, dict):
        hit = int(details.get("cached_tokens") or 0)
    if hit + miss < input_tokens:
        miss = max(input_tokens - hit, 0)
    return input_tokens, output_tokens, hit, miss


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    upstream_url: str
    api_key: str
    upstream_timeout: float
    records: list[ProxyRecord]
    lock: threading.Lock


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # http.server 的接口名（不是 snake_case）
        server = self.server
        assert isinstance(server, _ProxyServer)
        started = datetime.now(timezone.utc)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        model = ""
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                model = str(payload.get("model") or "")
        except ValueError:
            pass

        status = 502
        content_type = "application/json"
        data = b""
        error: str | None = None
        try:
            request = urllib.request.Request(
                server.upstream_url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {server.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            with urllib.request.urlopen(request, timeout=server.upstream_timeout) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
                data = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
            data = exc.read()
            error = f"上游返回 HTTP {status}"
        except Exception as exc:  # 网络/超时：给 mini 一个可读错误，不掀翻代理线程
            error = f"{type(exc).__name__}: {exc}"
            data = json.dumps(
                {"error": {"message": f"codelotte eval proxy: {error}"}},
                ensure_ascii=False,
            ).encode("utf-8")

        usage = _usage_from_sse(data, content_type)
        input_tokens, output_tokens, hit, miss = _token_counts(usage)
        record = ProxyRecord(
            at=started,
            model=model,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            error=error,
        )
        with server.lock:
            server.records.append(record)

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        pass  # 不把请求体/密钥写进日志


class RecordingProxy:
    """本地 OpenAI 兼容反向代理：子进程只拿到假 key，真 key 由这里注入上游。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        upstream_timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._server = _ProxyServer(("127.0.0.1", 0), _Handler)
        self._server.upstream_url = base_url.rstrip("/") + "/chat/completions"
        self._server.api_key = api_key
        self._server.upstream_timeout = upstream_timeout
        self._server.records = []
        self._server.lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def base_url(self) -> str:
        address = self._server.server_address
        return f"http://{address[0]}:{address[1]}"

    @property
    def records(self) -> tuple[ProxyRecord, ...]:
        with self._server.lock:
            return tuple(self._server.records)

    def __enter__(self) -> RecordingProxy:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._server.shutdown()
        self._server.server_close()
