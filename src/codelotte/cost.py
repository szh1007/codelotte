"""成本记账（SPEC §I，票据 07）：价目表数据化 + 峰谷判定 + 按调用计价与分项账单。

计价事实与出处（官方定价页 api-docs.deepseek.com/zh-cn/quick_start/pricing，2026-10-16 核对；
docs/tech/deepseek-api.md §2 同步更正——早前记录的是美元换算值，实际是人民币元）：
峰价 flash 命中 0.04 / 未命中 2 / 输出 8 元每百万 tokens，v4-pro 0.30 / 9 / 27；
空闲价 = 峰价 × 0.5；高峰 = 北京时间工作日 09:00–12:00、14:00–18:00（法定节假日除外），
其余时段（含周末）为空闲价。pi 式目录只建峰价、谷时会高估 2 倍——本模块刻意按时段建模。

价目、峰谷窗口、节假日表、货币都在随包目录 src/codelotte/providers/models.json（**provider 级**：
DeepSeek 的专属规则就写在 providers.deepseek 下）。随包目录只用于**计费、展示与上限参考**
（纯函数逻辑）——运行参数（端点/密钥/选用模型）只从用户级 ~/.codelotte/models.json 读
（models.py），这里不碰凭据。判定与计价是纯函数（传入时刻即可复算任意一次调用）；
Ledger 只做累计与渲染，不碰文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from codelotte.config import ConfigError
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

# 思考强度档位（DeepSeek thinking_mode 的参数面，2026-10-17 核对）：none 关闭思考；
# 其余为强度档，接口方按官方映射表自行折算（minimal→low、medium→high、xhigh/ultra→max…）。
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")

_MILLION = 1_000_000
_BUILTIN_PATH = Path(__file__).parent / "providers" / "models.json"  # 随包目录（providers 域的数据随 providers 走）


@dataclass(frozen=True)
class PeakWindow:
    """一个高峰窗口（当天分钟数，左闭右开：`end` 那一刻起已是低谷）。"""

    start_minute: int
    end_minute: int

    def contains(self, minute: int) -> bool:
        return self.start_minute <= minute < self.end_minute


@dataclass(frozen=True)
class ModelInfo:
    """随包目录里一个模型的**纯函数用事实**：展示名、窗口/输出上限（默认值兼上限）、
    思考强度默认档、峰价。

    只有参与逻辑的字段在这里（vision/schema/priceUnit 等能力标记留在 JSON 里供开发人员阅读，
    不解析——解析了没人用就是死字段）。货币随 Catalog.currency（官方价目为人民币元 / M tokens）。
    **凭据（apiKey/baseUrl）不在这里**：运行参数只从用户级 ~/.codelotte/models.json 读
    （models.py）；随包文件带密钥会进公开仓库（有测试守卫）。
    """

    name: str  # 展示名（TUI 状态栏；用户级 models.json 没写 name 时用它）
    context_window: int  # 窗口上限（用户可下调，不可上调；票据 12 的压缩阈值也从这取）
    max_output_tokens: int  # 单次输出上限（同上）
    reasoning_effort: str  # 思考强度默认档（用户级没写 reasoning_effort 时用它；none 关闭思考）
    cache_hit_price: float
    cache_miss_price: float
    output_price: float


@dataclass(frozen=True)
class Catalog:
    """随包模型目录：价目 + 峰谷规则 + 节假日表 + 官方端点（报错指路用）。"""

    models: dict[str, ModelInfo]
    utc_offset_hours: int
    peak_windows: tuple[PeakWindow, ...]
    off_peak_multiplier: float
    holidays: frozenset[date]
    currency: str = "CNY"  # 价目与账单的货币（官方定价页为人民币元）
    base_urls: dict[str, str] = field(default_factory=dict)  # provider 名 → 官方端点（缺 baseUrl 时报错提示用）
    price_note: str = ""  # 价目出处备注（导出账单脚注引用）

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


_RULE_KEYS = ("peakWindows", "offPeakMultiplier", "holidays", "currency", "timezone", "peakDays")


def _parse_catalog(raw: dict[str, Any], source: Path) -> Catalog:
    """解析随包目录：计费规则（峰谷/节假日/货币）是 **provider 级**的——DeepSeek 的专属设置
    就写在 providers.deepseek 下。v1 的运行时只有一套规则，检出多个 provider 各自定义规则时
    直接报错（等第二条协议/第二家 provider 落地再建模）。
    """
    providers: dict[str, dict[str, Any]] = raw["providers"]
    declaring = [
        name for name, spec in providers.items() if any(key in spec for key in _RULE_KEYS)
    ]
    if len(declaring) > 1:
        raise ConfigError(
            f"模型目录 {source}：多个 provider 各自定义了计费规则（{declaring}），v1 只支持一套"
        )
    rules: dict[str, Any] = providers[declaring[0]] if declaring else {}
    if rules.get("peakDays", "weekdays") != "weekdays":
        raise ConfigError(
            f"模型目录 {source} 的 peakDays 只支持 weekdays（给了 {rules.get('peakDays')!r}）"
        )
    windows = tuple(
        PeakWindow(start_minute=_minutes(w["start"]), end_minute=_minutes(w["end"]))
        for w in rules["peakWindows"]
    )
    if not windows:
        raise ConfigError(f"模型目录 {source} 的 peakWindows 不能为空")
    models: dict[str, ModelInfo] = {}
    base_urls: dict[str, str] = {}
    for provider_name, provider in providers.items():
        if provider.get("baseUrl"):
            base_urls[provider_name] = str(provider["baseUrl"])  # 报错指路参考（不参与请求）
        for spec in provider["models"]:
            model_id = str(spec["id"])
            prices = spec["peakPricePerMillion"]
            effort = str(spec["reasoning_effort"])
            if effort not in REASONING_EFFORTS:
                raise ConfigError(
                    f"模型目录 {source}：{model_id} 的 reasoning_effort 要在 "
                    f"{'/'.join(REASONING_EFFORTS)} 里（给了 {effort!r}）"
                )
            models[model_id] = ModelInfo(
                name=str(spec.get("name") or model_id),
                context_window=int(spec["contextWindow"]),
                max_output_tokens=int(spec["maxTokens"]),
                reasoning_effort=effort,
                cache_hit_price=float(prices["inputCacheHit"]),
                cache_miss_price=float(prices["inputCacheMiss"]),
                output_price=float(prices["output"]),
            )
    return Catalog(
        models=models,
        utc_offset_hours=int(rules.get("timezone", {}).get("utcOffsetHours", 8)),
        peak_windows=windows,
        off_peak_multiplier=float(rules["offPeakMultiplier"]),
        holidays=frozenset(date.fromisoformat(d) for d in rules.get("holidays", [])),
        currency=str(rules.get("currency", "CNY")),
        base_urls=base_urls,
        price_note=str(rules.get("priceNote", "")),
    )


def _read_catalog_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"模型目录读不动：{path}（{exc}）") from exc
    except ValueError as exc:
        raise ConfigError(f"模型目录不是合法 JSON：{path}（{exc}）") from exc


def load_catalog(path: Path | None = None) -> Catalog:
    """加载随包模型目录（计费事实 + 展示/上限默认值）。显式 path = 只读该文件（测试用）。"""
    source = path if path is not None else _BUILTIN_PATH
    raw = _read_catalog_file(source)
    try:
        return _parse_catalog(raw, source)
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"模型目录字段不完整或类型不对：{source}（{exc!r}）") from exc


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
