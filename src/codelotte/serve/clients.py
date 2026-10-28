"""三个中间件的连接工厂。

只负责「建连接」，不做重试、熔断与业务语义——那些属于调用方（API / worker），
放在这里会让测试无法注入失败。连接超时统一给短值：基础设施不可用时要快速失败，
而不是把请求挂住（票据 02 的 /readyz 依赖这一点）。
"""

from __future__ import annotations

from collections.abc import Sequence

import asyncpg
import redis.asyncio as redis_asyncio
from confluent_kafka import Consumer, Producer

from codelotte.serve.config import ServeConfig

CONNECT_TIMEOUT_S = 3.0


def create_redis(cfg: ServeConfig) -> redis_asyncio.Redis:
    """建一个异步 Redis 客户端；连接失败在首次命令时暴露，不在构造时。

    Args:
        cfg: 进程配置快照，只用其中的 ``redis_url``。

    Returns:
        配置好的 ``redis.asyncio.Redis``，调用方负责 ``aclose()``。
    """
    return redis_asyncio.from_url(
        cfg.redis_url,
        decode_responses=True,
        socket_connect_timeout=CONNECT_TIMEOUT_S,
        socket_timeout=CONNECT_TIMEOUT_S,
    )


async def create_pg_pool(cfg: ServeConfig) -> asyncpg.Pool:
    """建 PostgreSQL 连接池。

    Args:
        cfg: 进程配置快照，只用其中的 ``postgres_dsn``。

    Returns:
        已建立的 ``asyncpg.Pool``；调用方负责 ``close()``。

    Raises:
        asyncpg.PostgresError: 认证失败或 DSN 指向的库不存在。
        OSError: 网络不可达。
    """
    return await asyncpg.create_pool(
        dsn=cfg.postgres_dsn,
        min_size=1,
        max_size=10,
        timeout=CONNECT_TIMEOUT_S,
    )


def create_kafka_producer(cfg: ServeConfig) -> Producer:
    """建 Kafka 生产者。

    生产者是惰性的：构造不建链，首次 ``produce`` 才连 broker。调用方必须在退出前
    ``flush()``，否则缓冲区里的消息会丢。

    Args:
        cfg: 进程配置快照，只用其中的 ``kafka_bootstrap``。

    Returns:
        配置好的 ``confluent_kafka.Producer``。
    """
    return Producer(
        {
            "bootstrap.servers": cfg.kafka_bootstrap,
            "client.id": "codelotte-serve",
            "socket.timeout.ms": 3000,
        }
    )


def create_kafka_consumer(cfg: ServeConfig, *, group_id: str, topics: Sequence[str]) -> Consumer:
    """建 Kafka 消费者并订阅给定 topic。

    ``enable.auto.commit`` 固定为 False（ADR-0012）：位点只有在处理成功后才手动提交，
    否则消费者崩溃会永久丢消息。这是本模块唯一有意写死的策略。

    Args:
        cfg: 进程配置快照，只用其中的 ``kafka_bootstrap``。
        group_id: 消费者组名；同一组内分区会被分摊。
        topics: 要订阅的 topic 列表。

    Returns:
        已订阅的 ``confluent_kafka.Consumer``；调用方负责 ``close()``。
    """
    consumer = Consumer(
        {
            "bootstrap.servers": cfg.kafka_bootstrap,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "socket.timeout.ms": 3000,
        }
    )
    consumer.subscribe(list(topics))
    return consumer
