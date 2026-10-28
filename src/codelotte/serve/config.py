"""serve 层配置：只从环境变量读取（12-Factor）。

刻意不读 `.env` 文件——文件加载交给 compose / 部署工具，进程只认环境变量，
这样测试可以用一个 dict 完整替换配置来源。

默认值只服务本地 `deploy/docker-compose.yml`；任何共享或生产环境都必须覆盖。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# 宿主端口统一加 1 前缀（16379 / 19092 / 15432）：避开本机可能已装的同类服务
_DEFAULT_REDIS_URL = "redis://localhost:16379/0"
_DEFAULT_KAFKA_BOOTSTRAP = "localhost:19092"
# 开发密码在「本默认值 / deploy/.env.example / compose 的 POSTGRES_PASSWORD」三处完全相同，
# 所以复制 .env.example 后不配置也能直接跑通自检；生产部署必须用环境变量覆盖。
# 端口用 15432：宿主机 5432 常被本机原生 PostgreSQL 占用（见 deploy/README.md）。
_DEFAULT_PG_DSN = "postgresql://codelotte:codelotte-dev@localhost:15432/codelotte"


class ConfigError(ValueError):
    """配置缺失或不合法；消息里必须带上变量名，便于直接定位。"""


def _int_env(source: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = source.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，实际是 {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} 不能小于 {minimum}，实际是 {value}")
    return value


@dataclass(frozen=True, slots=True)
class ServeConfig:
    """一次进程生命周期内不变的配置快照。"""

    redis_url: str
    kafka_bootstrap: str
    postgres_dsn: str
    rate_limit_per_minute: int
    rate_limit_burst: int
    daily_quota_cents: int
    queue_lag_threshold: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServeConfig:
        source = os.environ if env is None else env
        return cls(
            redis_url=source.get("CODELOTTE_REDIS_URL", _DEFAULT_REDIS_URL),
            kafka_bootstrap=source.get("CODELOTTE_KAFKA_BOOTSTRAP", _DEFAULT_KAFKA_BOOTSTRAP),
            postgres_dsn=source.get("CODELOTTE_PG_DSN", _DEFAULT_PG_DSN),
            rate_limit_per_minute=_int_env(source, "CODELOTTE_RATE_LIMIT_PER_MINUTE", 60, minimum=1),
            rate_limit_burst=_int_env(source, "CODELOTTE_RATE_LIMIT_BURST", 20, minimum=1),
            daily_quota_cents=_int_env(source, "CODELOTTE_DAILY_QUOTA_CENTS", 1000, minimum=0),
            queue_lag_threshold=_int_env(source, "CODELOTTE_QUEUE_LAG_THRESHOLD", 10000, minimum=1),
        )
