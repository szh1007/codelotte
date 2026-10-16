"""成本记账（票据 07）：峰谷判定、按调用计价、目录加载、账单渲染。

峰谷用固定日期钉死（2026-10-15 是周四、10-17 是周六——2026-10-01 也是周四，用来测节假日），
避免测试随"今天星期几"漂移。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from codelotte.config import ConfigError
from codelotte.cost import (
    OFFPEAK,
    PEAK,
    CallRecord,
    Catalog,
    Ledger,
    ModelInfo,
    PeakWindow,
    call_record_from_entry,
    format_money,
    load_catalog,
    price_call,
)
from codelotte.providers.base import StreamUsage
from tests.support import PROJECT_ROOT

UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))


def _catalog(**overrides: object) -> Catalog:
    """测试目录：北京 9–12 / 14–18 高峰，2026-10-01 是节假日，谷价五折。"""
    defaults: dict[str, object] = {
        "models": {
            "m": ModelInfo(
                name="m",
                context_window=1000,
                max_output_tokens=100,
                reasoning_effort="high",
                cache_hit_price=0.04,
                cache_miss_price=2.0,
                output_price=8.0,
            )
        },
        "utc_offset_hours": 8,
        "peak_windows": (PeakWindow(9 * 60, 12 * 60), PeakWindow(14 * 60, 18 * 60)),
        "off_peak_multiplier": 0.5,
        "holidays": frozenset({date(2026, 10, 1)}),
    }
    defaults.update(overrides)
    return Catalog(**defaults)  # type: ignore[arg-type]


def _utc(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def _usage(hit: int = 0, miss: int = 0, out: int = 0) -> StreamUsage:
    return StreamUsage(
        input_tokens=hit + miss, output_tokens=out, cache_hit_tokens=hit, cache_miss_tokens=miss
    )


def test_period_boundaries_in_beijing_time() -> None:
    """跨时段边界：左闭右开；北京 09:00=UTC 01:00，午休与傍晚都算低谷。"""
    catalog = _catalog()
    assert catalog.period_at(_utc(1, 0)) == PEAK  # 09:00 整，窗口左端含
    assert catalog.period_at(_utc(0, 59)) == OFFPEAK
    assert catalog.period_at(_utc(3, 59)) == PEAK  # 11:59
    assert catalog.period_at(_utc(4, 0)) == OFFPEAK  # 12:00 起午休，右端不含
    assert catalog.period_at(_utc(5, 0)) == OFFPEAK  # 13:00 午休
    assert catalog.period_at(_utc(6, 0)) == PEAK  # 14:00
    assert catalog.period_at(_utc(9, 59)) == PEAK  # 17:59
    assert catalog.period_at(_utc(10, 0)) == OFFPEAK  # 18:00
    assert catalog.period_at(_utc(16, 0)) == OFFPEAK  # 次日 00:00（北京）


def test_weekend_and_holiday_are_offpeak() -> None:
    catalog = _catalog()
    saturday = _utc(2, 0, day=17)  # 周六 10:00（北京）
    sunday = _utc(2, 0, day=18)
    holiday = _utc(2, 0, day=1)  # 2026-10-01 周四，但在节假日表里
    assert catalog.period_at(saturday) == OFFPEAK
    assert catalog.period_at(sunday) == OFFPEAK
    assert catalog.period_at(holiday) == OFFPEAK
    # 同一时刻，去掉节假日表就是峰——证明差异确实来自配置
    assert _catalog(holidays=frozenset()).period_at(holiday) == PEAK


def test_period_accepts_any_timezone_and_rejects_naive() -> None:
    catalog = _catalog()
    instant = _utc(1, 0)
    assert catalog.period_at(instant) == catalog.period_at(instant.astimezone(BEIJING)) == PEAK
    with pytest.raises(ValueError, match="带时区"):
        catalog.period_at(datetime(2026, 10, 15, 1, 0))


def test_price_matrix_hit_miss_output_times_peak_offpeak() -> None:
    """计费组合矩阵：命中/未命中/输出 × 峰/谷（1M token 便于对表）。"""
    catalog = _catalog()
    peak_at, offpeak_at = _utc(1, 0), _utc(12, 0)  # 北京 09:00 / 20:00
    million = 1_000_000
    for at, period, rate in ((peak_at, PEAK, 1.0), (offpeak_at, OFFPEAK, 0.5)):
        hit = price_call(catalog, "m", _usage(hit=million), at=at)
        miss = price_call(catalog, "m", _usage(miss=million), at=at)
        out = price_call(catalog, "m", _usage(out=million), at=at)
        assert hit.period == period
        assert hit.cost == pytest.approx(0.04 * rate)
        assert miss.cost == pytest.approx(2.0 * rate)
        assert out.cost == pytest.approx(8.0 * rate)
    combined = price_call(catalog, "m", _usage(hit=million, miss=million, out=million), at=peak_at)
    assert combined.cost == pytest.approx(0.04 + 2.0 + 8.0)
    assert price_call(
        catalog, "m", _usage(hit=million, miss=million, out=million), at=offpeak_at
    ).cost == pytest.approx((0.04 + 2.0 + 8.0) / 2)


def test_unknown_model_records_period_but_no_price() -> None:
    priced = price_call(_catalog(), "who-knows", _usage(hit=10), at=_utc(1, 0))
    assert priced.period == PEAK
    assert priced.cost is None


def test_unsplit_usage_charges_remainder_as_miss() -> None:
    """provider 没拆缓存时（hit+miss 盖不住 input），差额按未命中算——估价宁高不低。"""
    priced = price_call(_catalog(), "m", StreamUsage(10, 5, 0, 0), at=_utc(1, 0))
    assert priced.cache_miss_tokens == 10
    assert priced.cost == pytest.approx((10 * 2.0 + 5 * 8.0) / 1_000_000)
    # 拆全了就照拆的算（全命中不产生未命中费）
    split = price_call(_catalog(), "m", StreamUsage(7, 0, 7, 0), at=_utc(1, 0))
    assert split.cache_miss_tokens == 0
    assert split.cost == pytest.approx(7 * 0.04 / 1_000_000)


def test_load_builtin_catalog() -> None:
    catalog = load_catalog()
    assert set(catalog.models) >= {"deepseek-flash", "deepseek-v4-pro"}
    flash = catalog.models["deepseek-flash"]
    assert flash.cache_miss_price == 2.0
    assert flash.context_window == 1_048_576  # 展示/上限默认值（官方上限，用户只能下调）
    assert flash.max_output_tokens == 393_216
    assert flash.reasoning_effort == "high"  # 思考强度默认档（用户级没写时用它；none 关闭）
    assert catalog.off_peak_multiplier == 0.5
    assert catalog.base_urls["deepseek"] == "https://api.deepseek.com"  # 报错指路参考值
    assert "官方定价页" in catalog.price_note  # 出处备注（导出脚注引用）
    assert catalog.period_at(_utc(1, 0)) == PEAK  # 2026-10-15 周四 09:00 北京
    assert catalog.period_at(_utc(2, 0, day=1)) == OFFPEAK  # 国庆假期


def test_builtin_catalog_carries_no_secrets() -> None:
    """守卫：随包 models.json 绝不能带密钥（会进公开仓库）——密钥只在用户级 models.json。"""
    text = (PROJECT_ROOT / "src" / "codelotte" / "providers" / "models.json").read_text(
        encoding="utf-8"
    )
    assert "apiKey" not in text
    assert all(not hasattr(info, "api_key") for info in load_catalog().models.values())


def test_explicit_catalog_path_is_read_alone(tmp_path: Path) -> None:
    """显式传路径（测试用）= 只读该文件，不读随包目录。"""
    import json as _json

    other = tmp_path / "catalog.json"
    other.write_text(
        _json.dumps(
            {
                "providers": {
                    "p": {
                        "peakDays": "weekdays",
                        "peakWindows": [{"start": "09:00", "end": "12:00"}],
                        "offPeakMultiplier": 0.5,
                        "holidays": [],
                        "models": [
                            {
                                "id": "m",
                                "contextWindow": 1,
                                "maxTokens": 1,
                                "reasoning_effort": "high",
                                "peakPricePerMillion": {
                                    "inputCacheHit": 0.1, "inputCacheMiss": 0.2, "output": 0.3,
                                },
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert set(load_catalog(other).models) == {"m"}


def test_broken_catalog_reports_readably(tmp_path: Path) -> None:
    broken = tmp_path / "models.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="不是合法 JSON"):
        load_catalog(broken)
    with pytest.raises(ConfigError, match="读不动"):
        load_catalog(tmp_path / "nope.json")
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text('{"models": {}}', encoding="utf-8")  # 缺 peakWindows / offPeakMultiplier
    with pytest.raises(ConfigError, match="字段不完整"):
        load_catalog(incomplete)
    wrong_days = tmp_path / "days.json"
    wrong_days.write_text(
        '{"providers": {"p": {"peakDays": "weekends", "peakWindows": [{"start": "09:00", "end": "10:00"}],'
        ' "offPeakMultiplier": 1.0, "models": []}}}',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="peakDays"):
        load_catalog(wrong_days)


def _record(
    *,
    model: str = "m",
    period: str = PEAK,
    hit: int = 0,
    miss: int = 0,
    out: int = 0,
    cost: float | None = None,
) -> CallRecord:
    return CallRecord(
        model=model,
        period=period,
        input_tokens=hit + miss,
        output_tokens=out,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        cost=cost,
    )


def test_ledger_totals_and_hit_rate() -> None:
    ledger = Ledger()
    ledger.record(_record(hit=80, miss=20, out=5, cost=0.001))
    ledger.record(_record(period=OFFPEAK, hit=0, miss=100, out=5, cost=0.002))
    assert ledger.input_tokens == 200
    assert ledger.output_tokens == 10
    assert ledger.cost == pytest.approx(0.003)
    assert ledger.cache_hit_rate == pytest.approx(0.4)
    assert ledger.priced
    empty = Ledger()
    assert empty.cache_hit_rate is None
    assert not empty.priced
    assert empty.invoice(_catalog()) == []


def test_invoice_groups_by_model_period_and_cache() -> None:
    """分项账单三组：按模型 / 按时段 / 按缓存（各分类金额按各自时段折算）。"""
    ledger = Ledger()
    ledger.record(_record(hit=1_000_000, cost=0.04))  # 峰：1M 命中（0.04 元/M）
    ledger.record(_record(period=OFFPEAK, miss=1_000_000, cost=1.0))  # 谷：1M 未命中（2.0 × 0.5）
    text = "\n".join(ledger.invoice(_catalog()))
    assert "账单（会话累计，人民币元）：2 次模型调用" in text
    assert "按模型  m 2 次 ≈¥1.040000" in text
    assert "峰值 1 次 ≈¥0.040000" in text
    assert "低谷 1 次 ≈¥1.000000" in text
    assert "命中 1000000 tok ≈¥0.040000" in text
    assert "未命中 1000000 tok ≈¥1.000000" in text
    assert "输出 0 tok ≈¥0.000000" in text
    assert "合计 ≈¥1.040000 · 缓存命中率 50%" in text


def test_invoice_notes_unpriced_model() -> None:
    ledger = Ledger()
    ledger.record(_record(model="who", hit=10, cost=None))
    text = "\n".join(ledger.invoice(_catalog()))
    assert "这些记录没有估价" in text
    assert not ledger.priced


def test_invoice_class_split_scales_to_recorded_cost() -> None:
    """审查修正回归：三组金额都从记录 cost 派生——改价后分类不会翻倍、之和恒等于合计。"""
    ledger = Ledger()
    ledger.record(_record(hit=1_000_000, cost=0.04))  # 记账时按当时价目估的 0.04
    doubled = _catalog(
        models={
            "m": ModelInfo(
                name="m",
                context_window=1,
                max_output_tokens=1,
                reasoning_effort="high",
                cache_hit_price=0.08,  # 平台改价翻倍
                cache_miss_price=4.0,
                output_price=16.0,
            )
        }
    )
    text = "\n".join(ledger.invoice(doubled))
    assert "命中 1000000 tok ≈¥0.040000" in text  # 仍是记录金额，不随今日价目翻倍
    assert "合计 ≈¥0.040000" in text


def test_invoice_legacy_entry_with_known_model_counts_tokens_only() -> None:
    """老记录（无 cost）即便模型在目录里也不回溯改账：token 照列、金额不计、理由文案不误导。"""
    ledger = Ledger()
    ledger.record(_record(model="m", hit=1000, cost=None))
    text = "\n".join(ledger.invoice(_catalog()))
    assert "这些记录没有估价" in text
    assert "命中 1000 tok ≈¥0.000000" in text


def test_call_record_from_entry_keeps_legacy_entries_token_only() -> None:
    """票据 05 时代的老 usage 记录没有 period/cost：token 照统计，金额置 None（不回溯改账）。"""
    legacy = {
        "type": "usage",
        "model": "m",
        "inputTokens": 12,
        "outputTokens": 3,
        "cacheHitTokens": 8,
        "cacheMissTokens": 4,
    }
    record = call_record_from_entry(legacy)
    assert record.cost is None
    assert record.period == ""
    assert record.input_tokens == 12
    assert record.cache_hit_tokens == 8
    fresh = call_record_from_entry({**legacy, "period": "peak", "cost": 0.0001})
    assert fresh.cost == pytest.approx(0.0001)
    assert fresh.period == PEAK


def test_format_money_uses_catalog_currency() -> None:
    assert format_money(0.0000126, "CNY") == "¥0.000013"
    assert format_money(1.5, "USD") == "$1.500000"
    assert format_money(1.5, "EUR") == "EUR 1.500000"  # 认不出的货币退化为代码前缀，不猜符号
    assert format_money(0.04) == "¥0.040000"  # 默认人民币（官方价目）
