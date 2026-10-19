"""成本曲线（E2）：从会话 usage 反事实重算缓存与 off-peak 的节省。

不重新调用模型：读 run 的 `report.json` + 每条案例的 session JSONL，按 usage 记录
重算三种“如果”：

- **实际**：记录里已经发生的 cost（含缓存命中与当时时段）；
- **无缓存**：把命中 token 全部按未命中价重算（确定性序列化 + 前缀纪律的反事实基线）；
- **全峰价**：同一份 usage 全部按峰价重算（off-peak 调度之前的反事实）；
- **无缓存 + 全峰价**：两者都去掉，作为总节省的分母。

口径限制：只读会话里的 usage；压缩回归的 checkpoint 探针不写回会话，因此不在这里
（E2 用通用测评 run）。这是**理论反事实**，不是重新跑一遍模型。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from codelotte.cost import (
    OFFPEAK,
    PEAK,
    PERIOD_LABELS,
    Catalog,
    format_money,
    price_tokens,
)
from codelotte.session.store import load_entries

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallUsage:
    """一条 usage 记录（成本曲线的最小单位）。"""

    model: str
    period: str
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    cost: float
    case_task: str
    case_repetition: int
    call_index: int


@dataclass(frozen=True)
class IndexBucket:
    """同一案例内第 N 次调用的聚合（看缓存命中是否随前缀增长）。"""

    index: int
    calls: int
    hit_tokens: int
    miss_tokens: int
    actual_cost: float = 0.0

    @property
    def hit_rate(self) -> float | None:
        total = self.hit_tokens + self.miss_tokens
        return self.hit_tokens / total if total else None


@dataclass(frozen=True)
class RunCost:
    """一个 run 的成本曲线数据。"""

    run_id: str
    path: str
    cases: int
    calls: int
    input_tokens: int
    output_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    actual_cost: float
    no_cache_cost: float
    peak_cost: float
    no_cache_peak_cost: float
    missing_cases: int
    unknown_cost_calls: int
    periods: tuple[tuple[str, int], ...]
    by_index: tuple[IndexBucket, ...]

    @property
    def cache_hit_rate(self) -> float | None:
        total = self.cache_hit_tokens + self.cache_miss_tokens
        return self.cache_hit_tokens / total if total else None

    @property
    def offpeak_calls(self) -> int:
        return dict(self.periods).get(OFFPEAK, 0)

    @property
    def cache_saving(self) -> float:
        return self.no_cache_cost - self.actual_cost

    @property
    def offpeak_saving(self) -> float:
        return self.peak_cost - self.actual_cost

    @property
    def total_saving(self) -> float:
        return self.no_cache_peak_cost - self.actual_cost


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _entry_tokens(entry: dict[str, object], path: Path) -> tuple[int, int, int, int]:
    """usage 的四个 token 字段；坏值带文件名报出来，不静默当 0。"""
    values: list[int] = []
    for key in ("inputTokens", "outputTokens", "cacheHitTokens", "cacheMissTokens"):
        value = entry.get(key, 0) or 0
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} 的 usage 字段 {key} 不是整数：{value!r}")
        values.append(value)
    return (values[0], values[1], values[2], values[3])


def _usage_cost(catalog: Catalog, usage: dict[str, object], period: str) -> float:
    model = str(usage.get("model", ""))
    hit = _as_int(usage.get("cacheHitTokens", 0))
    miss = _as_int(usage.get("cacheMissTokens", 0))
    output = _as_int(usage.get("outputTokens", 0))
    recorded = usage.get("cost")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
        return float(recorded)
    priced = price_tokens(
        catalog,
        model,
        period=period,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        output_tokens=output,
    )
    return priced or 0.0


def collect_calls(catalog: Catalog, run_dir: Path) -> tuple[list[CallUsage], int]:
    """读 run 的 report.json 与 session；返回 (usage 记录, 缺少可读会话的案例数)。"""
    report_path = run_dir / "report.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"成本分析读不动 report.json：{report_path}（{exc}）") from exc
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError(f"report.json 缺少 cases 数组：{report_path}")
    calls: list[CallUsage] = []
    missing = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        session_path = case.get("session_path")
        if not isinstance(session_path, str):
            missing += 1
            continue
        path = Path(session_path)
        if not path.is_file():
            missing += 1
            continue
        try:
            entries = load_entries(path)
        except (OSError, ValueError):
            missing += 1
            continue
        index = 0
        for entry in entries:
            if entry.get("type") != "usage":
                continue
            index += 1
            period = str(entry.get("period") or PEAK)
            input_tokens, output_tokens, hit, miss = _entry_tokens(entry, path)
            calls.append(
                CallUsage(
                    model=str(entry.get("model", "")),
                    period=period,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_hit_tokens=hit,
                    cache_miss_tokens=miss,
                    cost=_usage_cost(catalog, entry, period),
                    case_task=str(case.get("task_id", "")),
                    case_repetition=int(case.get("repetition", 0) or 0),
                    call_index=index,
                )
            )
    return calls, missing


def analyze_run(catalog: Catalog, run_dir: Path) -> RunCost:
    """一个 run 的实际/无缓存/全峰价成本与命中率曲线。"""
    calls, missing = collect_calls(catalog, run_dir)
    actual = no_cache = peak = no_cache_peak = 0.0
    hit_total = miss_total = out_total = in_total = 0
    periods: dict[str, int] = defaultdict(int)
    by_index: dict[int, list[float]] = defaultdict(lambda: [0, 0, 0, 0.0])
    unknown_cost_calls = 0

    def priced(call: CallUsage, *, period: str, hit: int, miss: int) -> float:
        nonlocal unknown_cost_calls
        value = price_tokens(
            catalog,
            call.model,
            period=period,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            output_tokens=call.output_tokens,
        )
        if value is None:
            unknown_cost_calls += 1
            logger.warning(
                "成本曲线：目录里没有模型 %r（%s），反事实按 0 计",
                call.model,
                run_dir,
            )
            return 0.0
        return value

    for call in calls:
        hit, miss, output = (
            call.cache_hit_tokens,
            call.cache_miss_tokens,
            call.output_tokens,
        )
        actual += call.cost
        no_cache += priced(call, period=call.period, hit=0, miss=hit + miss)
        peak += priced(call, period=PEAK, hit=hit, miss=miss)
        no_cache_peak += priced(call, period=PEAK, hit=0, miss=hit + miss)
        hit_total += hit
        miss_total += miss
        out_total += output
        in_total += call.input_tokens
        periods[call.period] += 1
        bucket = by_index[call.call_index]
        bucket[0] += 1
        bucket[1] += hit
        bucket[2] += miss
        bucket[3] += call.cost
    buckets = tuple(
        IndexBucket(
            index=index,
            calls=int(data[0]),
            hit_tokens=int(data[1]),
            miss_tokens=int(data[2]),
            actual_cost=float(data[3]),
        )
        for index, data in sorted(by_index.items())
    )
    return RunCost(
        run_id=run_dir.name,
        path=str(run_dir),
        cases=len({(c.case_task, c.case_repetition) for c in calls}),
        calls=len(calls),
        input_tokens=in_total,
        output_tokens=out_total,
        cache_hit_tokens=hit_total,
        cache_miss_tokens=miss_total,
        actual_cost=actual,
        no_cache_cost=no_cache,
        peak_cost=peak,
        no_cache_peak_cost=no_cache_peak,
        missing_cases=missing,
        unknown_cost_calls=unknown_cost_calls,
        periods=tuple(sorted(periods.items())),
        by_index=buckets,
    )


def _rate_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _pct(part: float, whole: float) -> str:
    return "—" if whole <= 0 else f"{part / whole:.1%}"


def _money(value: float, currency: str) -> str:
    return format_money(value, currency)


def render_cost_markdown(
    runs: list[RunCost], *, catalog: Catalog, command: str
) -> str:
    """成本曲线报表（Markdown）。"""
    lines = [
        "# 成本曲线（E2）：缓存与 off-peak",
        "",
        "> 从会话 usage 反事实重算：实际 / 无缓存 / 全峰价 / 两者都去掉。",
        "> 不重新调用模型；详见文末口径。",
        "",
        "## 结论速览",
        "",
        "| run | 调用 | 缓存命中率 | 实际成本 | 无缓存反事实 | 全峰价反事实 | "
        "总反事实（无缓存+峰价） | 缓存节省 | off-peak 节省 | 总节省 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| `{run.run_id}` | {run.calls} | {_rate_text(run.cache_hit_rate)} | "
            f"{_money(run.actual_cost, catalog.currency)} | "
            f"{_money(run.no_cache_cost, catalog.currency)} | "
            f"{_money(run.peak_cost, catalog.currency)} | "
            f"{_money(run.no_cache_peak_cost, catalog.currency)} | "
            f"{_money(run.cache_saving, catalog.currency)} "
            f"({_pct(run.cache_saving, run.no_cache_cost)}) | "
            f"{_money(run.offpeak_saving, catalog.currency)} "
            f"({_pct(run.offpeak_saving, run.peak_cost)}) | "
            f"{_money(run.total_saving, catalog.currency)} "
            f"({_pct(run.total_saving, run.no_cache_peak_cost)}) |"
        )
    lines.extend(
        [
            "",
            "读法：缓存节省 = 无缓存 − 实际；off-peak 节省 = 全峰价 − 实际；"
            "总节省 = 无缓存+全峰价 − 实际。百分比的分母分别是各自的反事实成本。",
            "",
            "## 逐 run 明细",
            "",
        ]
    )
    for run in runs:
        lines.extend(
            [
                f"### `{run.run_id}`",
                "",
                f"- 路径：`{run.path}`",
                f"- 案例 / 调用：{run.cases} / {run.calls}；"
                f"缺 usage 会话的案例：{run.missing_cases}；"
                f"目录里没有模型的调用：{run.unknown_cost_calls}",
                f"- token：输入 {run.input_tokens}（命中 {run.cache_hit_tokens} / "
                f"未命中 {run.cache_miss_tokens}），输出 {run.output_tokens}",
                f"- 时段：{', '.join(f'{PERIOD_LABELS.get(p, p)} {n}' for p, n in run.periods) or '—'}"
                f"；off-peak 调用占比 {_pct(run.offpeak_calls, run.calls)}",
                "",
                "| 调用序号 | 调用数 | 命中 token | 未命中 token | 命中率 | 实际成本 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for bucket in run.by_index:
            lines.append(
                f"| {bucket.index} | {bucket.calls} | {bucket.hit_tokens} | "
                f"{bucket.miss_tokens} | {_rate_text(bucket.hit_rate)} | "
                f"{_money(bucket.actual_cost, catalog.currency)} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 口径与局限",
            "",
            "- **实测值**来自会话 `usage` 记录（input/output/cache hit/miss/cost/period）。",
            "- **无缓存反事实**：把命中 token 全部按未命中价重算；不是重新跑模型，"
            "也不是“关掉 provider 缓存”的实测。",
            "- **全峰价反事实**：同一份 usage 全部按峰价重算；实际跑数落在低谷，"
            "所以这是 off-peak 调度前的理论成本。",
            "- **缓存命中率**是 `hit / (hit + miss)`；按调用序号看前缀是否随对话增长。",
            "- 只读会话里的 usage：压缩回归的 checkpoint 探针不写回会话，"
            "因此本报表不覆盖探针成本（E2 用通用测评 run）。",
            "- 价目、峰谷窗口与倍率来自随包 `providers/models.json`；换价目后重跑即重算。",
            "",
            "## 复现",
            "",
            "```bash",
            command,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_cost_report(
    out_dir: Path, runs: list[RunCost], *, catalog: Catalog, command: str
) -> Path:
    """写 cost-report.md / cost-report.json，返回 Markdown 路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "cost-report.md"
    path.write_text(
        render_cost_markdown(runs, catalog=catalog, command=command),
        encoding="utf-8",
        newline="\n",
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "currency": catalog.currency,
        "runs": [asdict(run) for run in runs],
        "savings": [
            {
                "run_id": run.run_id,
                "cache_saving": run.cache_saving,
                "offpeak_saving": run.offpeak_saving,
                "total_saving": run.total_saving,
            }
            for run in runs
        ],
    }
    (out_dir / "cost-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
