"""serve 地基的离线测试：配置解析、依赖不通时的点名、退出码。

**不碰网络**：Redis 客户端工厂、`asyncpg.connect`、Kafka AdminClient 在测试里都替换成
确定性失败。真实连通性由 `pytest -m serve` 的集成用例与 healthcheck CLI 本身覆盖
（CONTRIBUTING 测试约定：单元测试不得访问网络）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("asyncpg")
pytest.importorskip("redis")
pytest.importorskip("confluent_kafka")

from codelotte.serve import healthcheck  # noqa: E402
from codelotte.serve.config import ConfigError, ServeConfig  # noqa: E402


def _fail(*args: Any, **kwargs: Any) -> None:
    raise OSError("connection refused")


async def _fail_async(*args: Any, **kwargs: Any) -> None:
    raise OSError("connection refused")


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """把三个外部边界替换成确定性失败，测试不建立任何真实连接。"""
    monkeypatch.setattr(healthcheck, "create_redis", _fail)
    monkeypatch.setattr(healthcheck.asyncpg, "connect", _fail_async)
    monkeypatch.setattr(healthcheck, "_list_topics", _fail)


def test_config_defaults_match_local_compose() -> None:
    cfg = ServeConfig.from_env({})

    assert cfg.redis_url == "redis://localhost:16379/0"
    assert cfg.kafka_bootstrap == "localhost:19092"
    assert ":15432/" in cfg.postgres_dsn
    assert cfg.queue_lag_threshold == 10000


def test_config_reads_overrides() -> None:
    cfg = ServeConfig.from_env(
        {
            "CODELOTTE_RATE_LIMIT_PER_MINUTE": "120",
            "CODELOTTE_DAILY_QUOTA_CENTS": "0",
        }
    )

    assert cfg.rate_limit_per_minute == 120
    assert cfg.daily_quota_cents == 0


def test_config_rejects_non_integer() -> None:
    with pytest.raises(ConfigError, match="CODELOTTE_RATE_LIMIT_PER_MINUTE"):
        ServeConfig.from_env({"CODELOTTE_RATE_LIMIT_PER_MINUTE": "abc"})


def test_config_rejects_out_of_range() -> None:
    with pytest.raises(ConfigError, match="不能小于 1"):
        ServeConfig.from_env({"CODELOTTE_QUEUE_LAG_THRESHOLD": "0"})


def test_redact_url_hides_password() -> None:
    redacted = healthcheck.redact_url("postgresql://alice:s3cret@db:5432/app")

    assert "s3cret" not in redacted
    assert redacted == "postgresql://alice:***@db:5432/app"


def test_redact_url_leaves_passwordless_url_alone() -> None:
    assert healthcheck.redact_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


def test_healthcheck_reports_each_failing_dependency(unreachable: None) -> None:
    results = asyncio.run(healthcheck.check_all(ServeConfig.from_env({})))
    by_name = {result.name: result for result in results}

    assert set(by_name) == {"redis", "kafka", "postgres"}
    assert all(not result.ok for result in results)
    rendered = healthcheck.format_results(results)
    assert rendered.count("FAIL") == 3
    assert "redis" in rendered and "kafka" in rendered and "postgres" in rendered


def test_main_exits_1_when_a_dependency_is_unreachable(
    unreachable: None, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = healthcheck.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out.count("FAIL") == 3


def test_main_reports_config_error_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CODELOTTE_RATE_LIMIT_PER_MINUTE", "abc")

    exit_code = healthcheck.main()
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "CODELOTTE_RATE_LIMIT_PER_MINUTE" in captured.err
    assert "Traceback" not in captured.err


def test_malformed_connection_strings_are_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis/PG 的 URL 解析在本地完成（不建连接），畸形串也必须走 FAIL 而不是抛栈。"""
    monkeypatch.setattr(healthcheck, "_list_topics", _fail)
    cfg = ServeConfig.from_env(
        {
            "CODELOTTE_REDIS_URL": "not-a-url",
            "CODELOTTE_KAFKA_BOOTSTRAP": "127.0.0.1:9099",
            "CODELOTTE_PG_DSN": "not-a-dsn",
        }
    )

    results = asyncio.run(healthcheck.check_all(cfg))

    assert all(not result.ok for result in results)


# `clients.create_kafka_consumer` 是纯适配器：订阅结果没有公开查询接口，离线断言只能
# 对着实现细节写。它的行为由票据 08 的 `pytest -m serve` 集成用例端到端覆盖。
