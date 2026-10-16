"""成本记账（SPEC §I，票据 07）：价目表数据化 + 峰谷判定 + 按调用计价与分项账单。

计价事实与出处（官方定价页 api-docs.deepseek.com/zh-cn/quick_start/pricing，2026-10-16 核对；
docs/tech/deepseek-api.md §2 同步更正——早前记录的是美元换算值，实际是人民币元）：
峰价 flash 命中 0.04 / 未命中 2 / 输出 8 元每百万 tokens，v4-pro 0.30 / 9 / 27；
空闲价 = 峰价 × 0.5；高峰 = 北京时间工作日 09:00–12:00、14:00–18:00（法定节假日除外），
其余时段（含周末）为空闲价。pi 式目录只建峰价、谷时会高估 2 倍——本模块刻意按时段建模。

价目、峰谷窗口、节假日表都在 models.json：随包内置，可被 ~/.codelotte/models.json 整份覆写。
判定与计价是纯函数（传入时刻即可复算任意一次调用）；Ledger 只做累计与渲染，不碰文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from codelotte.config import ConfigError, get_home_dir
from codelotte.providers.base import StreamUsage

__all__ = [
    "CURRENCY_LABELS",
    "OFFPEAK",
    "PEAK",
    "PERIOD_LABELS",
    "CallRecord",
    "Catalog",
    "Ledger",
    "ModelInfo",
    "PeakWindow",
    "PricedCall",
    "call_record_from_entry",
    "format_money",
    "load_catalog",
    "price_call",
]

PEAK = "peak"
OFFPEAK = "offpeak"
PERIOD_LABELS = {PEAK: "峰值", OFFPEAK: "低谷"}
CURRENCY_LABELS = {"CNY": "人民币元", "USD": "美元"}
_CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "$"}

_MILLION = 1_000_000
_BUILTIN_PATH = Path(__file__).with_name("models.json")


def _user_catalog_path() -> Path:
    home = get_home_dir() or Path.home()
    return home / ".codelotte" / "models.json"


@dataclass(frozen=True)
class PeakWindow:
    """一个高峰窗口（当天分钟数，左闭右开：`end` 那一刻起已是低谷）。"""

    start_minute: int
    end_minute: int

    def contains(self, minute: int) -> bool:
        return self.start_minute <= minute < self.end_minute


@dataclass(frozen=True)
class ModelInfo:
    """一个模型的元数据与峰价（货币随 Catalog.currency，官方价目为人民币元 / M tokens）。"""

    name: str
    context_window: int
    max_output_tokens: int
    vision: bool
    cache_hit_price: float
    cache_miss_price: float
    output_price: float


@dataclass(frozen=True)
class Catalog:
    """模型目录：价目 + 峰谷规则 + 节假日表（全部来自 models.json）。"""

    models: dict[str, ModelInfo]
    utc_offset_hours: int
    peak_windows: tuple[PeakWindow, ...]
    off_peak_multiplier: float
    holidays: frozenset[date]
    currency: str = "CNY"  # 价目与账单的货币（官方定价页为人民币元）

    def period_at(self, when: datetime) -> str:
        """判定一次调用的时段（peak / offpeak）。`when` 必须是带时区的时刻。

        规则：高峰 = 本地（北京时间）工作日且不在节假日表，且落在某个高峰窗口内；
        其余（含周末、节假日、窗口外）全是低谷。
        """
        if when.tzinfo is None:
            raise ValueError(
                "period_at 需要带时区的时刻（naive datetime 会按系统时区误解）"
            )
        local = when.astimezone(timezone(timedelta(hours=self.utc_offset_hours)))
        if local.weekday() >= 5 or local.date() in self.holidays:
            return OFFPEAK
        minute = local.hour * 60 + local.minute
        return PEAK if any(w.contains(minute) for w in self.peak_windows) else OFFPEAK


@dataclass(frozen=True)
class PricedCall:
    """一次调用计价结果（时段的判定 + 费用估价 + 计价口径的 token 数）。"""

    period: str
    cost: float | None  # 目录里没有这个模型时为 None——token 照记，不瞎估价
    cache_hit_tokens: int
    cache_miss_tokens: int


def _call_cost(
    catalog: Catalog, info: ModelInfo, period: str, hit: int, miss: int, out: int
) -> float:
    """一次调用按三档 token 计价的唯一公式（峰价 × 时段系数）——估价与账单分摊共用这一处。"""
    rate = catalog.off_peak_multiplier if period == OFFPEAK else 1.0
    return (
        (
            hit * info.cache_hit_price
            + miss * info.cache_miss_price
            + out * info.output_price
        )
        / _MILLION
        * rate
    )


def price_call(
    catalog: Catalog, model: str, usage: StreamUsage, *, at: datetime
) -> PricedCall:
    """按调用当时的价目表估价（谷价 = 峰价 × offPeakMultiplier）。"""
    period = catalog.period_at(at)
    hit = usage.cache_hit_tokens
    # 计价口径的"未命中"：provider 没拆缓存时（hit+miss 不等于 input）把差额全按未命中算——
    # 不拆的部分按贵的那档记，估价宁高不低（DeepSeek 实际总会拆，这只是兜底）。
    miss = (
        usage.cache_miss_tokens
        if usage.cache_hit_tokens + usage.cache_miss_tokens >= usage.input_tokens
        else max(usage.input_tokens - hit, 0)
    )
    info = catalog.models.get(model)
    if info is None:
        return PricedCall(
            period=period, cost=None, cache_hit_tokens=hit, cache_miss_tokens=miss
        )
    cost = _call_cost(catalog, info, period, hit, miss, usage.output_tokens)
    return PricedCall(
        period=period, cost=cost, cache_hit_tokens=hit, cache_miss_tokens=miss
    )


def _minutes(text: str) -> int:
    hours, _, minutes = text.partition(":")
    return int(hours) * 60 + int(minutes)


def _parse_catalog(raw: dict[str, Any], source: Path) -> Catalog:
    if raw.get("peakDays", "weekdays") != "weekdays":
        raise ConfigError(
            f"模型目录 {source} 的 peakDays 只支持 weekdays（给了 {raw.get('peakDays')!r}）"
        )
    windows = tuple(
        PeakWindow(start_minute=_minutes(w["start"]), end_minute=_minutes(w["end"]))
        for w in raw["peakWindows"]
    )
    if not windows:
        raise ConfigError(f"模型目录 {source} 的 peakWindows 不能为空")
    models: dict[str, ModelInfo] = {}
    for name, spec in raw["models"].items():
        prices = spec["peakPricePerMillion"]
        models[name] = ModelInfo(
            name=name,
            context_window=int(spec["contextWindow"]),
            max_output_tokens=int(spec["maxOutputTokens"]),
            vision=bool(spec.get("vision", False)),
            cache_hit_price=float(prices["inputCacheHit"]),
            cache_miss_price=float(prices["inputCacheMiss"]),
            output_price=float(prices["output"]),
        )
    return Catalog(
        models=models,
        utc_offset_hours=int(raw.get("timezone", {}).get("utcOffsetHours", 8)),
        peak_windows=windows,
        off_peak_multiplier=float(raw["offPeakMultiplier"]),
        holidays=frozenset(date.fromisoformat(d) for d in raw.get("holidays", [])),
        currency=str(raw.get("currency", "CNY")),
    )


def load_catalog(path: Path | None = None) -> Catalog:
    """加载模型目录：显式 path > 用户覆写 ~/.codelotte/models.json > 随包内置。"""
    if path is None:
        user = _user_catalog_path()
        path = user if user.is_file() else _BUILTIN_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"模型目录读不动：{path}（{exc}）") from exc
    except ValueError as exc:
        raise ConfigError(f"模型目录不是合法 JSON：{path}（{exc}）") from exc
    try:
        return _parse_catalog(raw, path)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"模型目录字段不完整或类型不对：{path}（{exc!r}）") from exc


def format_money(value: float, currency: str = "CNY") -> str:
    """金额显示统一 6 位小数（单次调用常远小于 1 分钱，4 位会被截成 0.0000）。

    货币符号来自目录（官方为人民币元 ¥）；未知货币退化为代码前缀，不猜符号。
    """
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{value:.6f}" if symbol else f"{currency} {value:.6f}"


@dataclass(frozen=True)
class CallRecord:
    """账单里的一次模型调用（从事件实时来，或从会话记录回放来）。"""

    model: str
    period: str  # "peak" / "offpeak"；旧记录（票据 05 时代）没有这个字段 → ""
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    cost: float | None  # 旧记录没有估价 → None（token 照统计，不按今天的价目回溯改账）


def call_record_from_entry(entry: dict[str, Any]) -> CallRecord:
    """会话文件里的一条 usage 记录 → 账单记录（--continue 回放用）。"""
    cost = entry.get("cost")
    return CallRecord(
        model=str(entry.get("model", "")),
        period=str(entry.get("period", "")),
        input_tokens=int(entry.get("inputTokens", 0) or 0),
        output_tokens=int(entry.get("outputTokens", 0) or 0),
        cache_hit_tokens=int(entry.get("cacheHitTokens", 0) or 0),
        cache_miss_tokens=int(entry.get("cacheMissTokens", 0) or 0),
        cost=(
            float(cost)
            if isinstance(cost, (int, float)) and not isinstance(cost, bool)
            else None
        ),
    )


class Ledger:
    """账单累计：保留逐次调用记录，累计与分项都从它渲染（不碰文件、不管呈现）。"""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    def record(self, call: CallRecord) -> None:
        self.calls.append(call)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def cache_hit_tokens(self) -> int:
        return sum(c.cache_hit_tokens for c in self.calls)

    @property
    def cache_miss_tokens(self) -> int:
        return sum(c.cache_miss_tokens for c in self.calls)

    @property
    def cost(self) -> float:
        return sum(c.cost or 0.0 for c in self.calls)

    @property
    def priced(self) -> bool:
        """是否有任何一次调用能对上价目（决定"≈¥"值不值得显示）。"""
        return any(c.cost is not None for c in self.calls)

    @property
    def cache_hit_rate(self) -> float | None:
        cached = self.cache_hit_tokens + self.cache_miss_tokens
        return self.cache_hit_tokens / cached if cached else None

    @property
    def hit_rate_text(self) -> str:
        """命中率显示文本（TUI 状态栏与账单共用一处）。"""
        rate = self.cache_hit_rate
        return f"{rate:.0%}" if rate is not None else "—"

    def _class_split(
        self, catalog: Catalog, call: CallRecord, info: ModelInfo
    ) -> tuple[float, float, float]:
        """把一次调用**记录在案**的金额按三档计价权重分摊成 (命中, 未命中, 输出)。

        权重用当前价目算（改价后分摊是近似），再缩放回记录的 cost——三组之和恒等于合计，
        不会出现"分类加起来不等于总账"（审查修正：原实现拿当前价目重算分类金额）。
        """
        hit_w = _call_cost(catalog, info, call.period, call.cache_hit_tokens, 0, 0)
        miss_w = _call_cost(catalog, info, call.period, 0, call.cache_miss_tokens, 0)
        out_w = _call_cost(catalog, info, call.period, 0, 0, call.output_tokens)
        total_w = hit_w + miss_w + out_w
        if total_w <= 0 or call.cost is None:
            return 0.0, 0.0, 0.0
        scale = call.cost / total_w
        return hit_w * scale, miss_w * scale, out_w * scale

    def invoice(self, catalog: Catalog) -> list[str]:
        """分项账单（按模型 / 按时段 / 按缓存三组，票据 07 验收）。

        三组金额都从**记录在案**的 cost 派生（分类按计价权重分摊）——同源，改价或老记录
        都不会出现"分类加起来不等于总账"；没有估价的记录 token 照列、金额不计。
        """
        if not self.calls:
            return []

        def money(value: float) -> str:
            return format_money(value, catalog.currency)

        currency_label = CURRENCY_LABELS.get(catalog.currency, catalog.currency)
        by_model: dict[str, list[CallRecord]] = {}
        for call in self.calls:
            by_model.setdefault(call.model, []).append(call)
        model_parts: list[str] = []
        for name, calls in by_model.items():
            part = f"{name} {len(calls)} 次"
            if any(c.cost is not None for c in calls):
                part += f" ≈{money(sum(c.cost or 0.0 for c in calls))}"
            else:
                part += "（这些记录没有估价，只记 token）"
            model_parts.append(part)

        by_period: dict[str, list[CallRecord]] = {}
        for call in self.calls:
            by_period.setdefault(call.period or "未判定", []).append(call)
        period_parts = [
            f"{PERIOD_LABELS.get(period, period)} {len(calls)} 次 ≈{money(sum(c.cost or 0.0 for c in calls))}"
            for period, calls in by_period.items()
        ]

        hit_cost = miss_cost = out_cost = 0.0
        for call in self.calls:
            info = catalog.models.get(call.model)
            if info is None or call.cost is None:
                continue
            split_hit, split_miss, split_out = self._class_split(catalog, call, info)
            hit_cost += split_hit
            miss_cost += split_miss
            out_cost += split_out

        return [
            f"账单（会话累计，{currency_label}）：{len(self.calls)} 次模型调用",
            "  按模型  " + " · ".join(model_parts),
            "  按时段  " + " · ".join(period_parts),
            "  按缓存  "
            f"命中 {self.cache_hit_tokens} tok ≈{money(hit_cost)}"
            f" · 未命中 {self.cache_miss_tokens} tok ≈{money(miss_cost)}"
            f" · 输出 {self.output_tokens} tok ≈{money(out_cost)}",
            f"  合计 ≈{money(self.cost)} · 缓存命中率 {self.hit_rate_text}",
        ]
