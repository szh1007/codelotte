"""依赖自检：Redis / Kafka / PostgreSQL 三项，全通退出 0。

每一项独立检查、独立报错——运维要知道「哪一个不通」，而不是「都不通」。
三项并发执行，总耗时取最慢的一项。

用法：``python -m codelotte.serve.healthcheck``（需要 ``uv sync --extra serve``）。
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import redis.asyncio as redis_asyncio
from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient

from codelotte.serve.clients import create_redis
from codelotte.serve.config import ConfigError, ServeConfig

# asyncpg 的 timeout 参数在类型存根里是 int，这里保持整数避免类型窄化告警
_CHECK_TIMEOUT_S = 3


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def redact_url(url: str) -> str:
    """打印前抹掉密码；自检输出经常被贴进 issue，不能带凭证。"""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    userinfo = f"{parts.username}:***"
    host = parts.hostname or ""
    netloc = f"{userinfo}@{host}:{parts.port}" if parts.port else f"{userinfo}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def _check_redis(cfg: ServeConfig) -> CheckResult:
    client: redis_asyncio.Redis | None = None
    try:
        # 构造与连接都可能在调用方无感知的情况下抛错，全部收进 try
        client = create_redis(cfg)
        await client.ping()
        return CheckResult("redis", True, redact_url(cfg.redis_url))
    except (redis_asyncio.RedisError, OSError, ValueError) as exc:
        return CheckResult("redis", False, f"{type(exc).__name__}: {exc}")
    finally:
        if client is not None:
            await client.aclose()


async def _check_postgres(cfg: ServeConfig) -> CheckResult:
    try:
        conn = await asyncpg.connect(cfg.postgres_dsn, timeout=_CHECK_TIMEOUT_S)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return CheckResult("postgres", True, redact_url(cfg.postgres_dsn))
    except (asyncpg.PostgresError, OSError, TimeoutError, ValueError) as exc:
        return CheckResult("postgres", False, f"{type(exc).__name__}: {exc}")


def _list_topics(bootstrap: str, timeout: float) -> None:
    AdminClient({"bootstrap.servers": bootstrap}).list_topics(timeout=timeout)


async def _check_kafka(cfg: ServeConfig) -> CheckResult:
    try:
        # confluent-kafka 是同步库；放进线程，避免阻塞事件循环
        await asyncio.to_thread(_list_topics, cfg.kafka_bootstrap, _CHECK_TIMEOUT_S)
        return CheckResult("kafka", True, cfg.kafka_bootstrap)
    except (KafkaException, RuntimeError, OSError) as exc:
        return CheckResult("kafka", False, f"{type(exc).__name__}: {exc}")


async def check_all(cfg: ServeConfig) -> list[CheckResult]:
    """并发检查三项，返回顺序固定为 redis / kafka / postgres。"""
    return list(
        await asyncio.gather(
            _check_redis(cfg),
            _check_kafka(cfg),
            _check_postgres(cfg),
        )
    )


def format_results(results: list[CheckResult]) -> str:
    """把检查结果排成对齐的三行文本，一行一项。

    Args:
        results: ``check_all`` 的返回值。

    Returns:
        可直接打印的多行字符串。
    """
    return "\n".join(
        f"{result.name:<9} {'OK  ' if result.ok else 'FAIL'} {result.detail}" for result in results
    )


def main() -> int:
    """CLI 入口。

    Returns:
        0 —— 三项全部就绪；1 —— 至少一项不通；2 —— 配置本身不合法。
    """
    try:
        config = ServeConfig.from_env()
    except ConfigError as exc:
        # 配置错误不是「依赖不通」，用不同退出码区分；同时只打一行，不抛栈
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    results = asyncio.run(check_all(config))
    print(format_results(results))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
