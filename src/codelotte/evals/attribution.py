"""失败归因分类器（票据 18）：一次失败“病在哪一层”。

五类病位（优先级从高到低）：

1. `environment`：沙箱/网络/依赖或验收设施本身坏了，轨迹可能根本没有；
2. `loop`：被 guardrail 拦下、迭代上限或模型调用预算耗尽；
3. `tool_schema`：工具参数不是合法 JSON、缺必需参数、调了不存在的工具；
4. `context_loss`：发生过压缩，之后又重新读取压缩前读过的文件（信息丢过）；
5. `model`：以上都不是，模型自己理解/决策/执行错——兜底类别，置信度最低。

规则全部是确定性的、可解释的：每条归因带 `evidence`（一句话证据）与
`signals`（机器可读信号）。它们不调用模型，也不看最终工作区内容；只读会话记录与
案例级事实（运行错误、验收详情、作弊标记）。规则文档见 `evals/attribution.md`。

语料评测（人工标注对照）见 `evaluate_corpus`：samples.jsonl 每行给出会话路径与
人工类别，跑分类器后算准确率与混淆矩阵。首版语料是作者构造的草稿标注，报告会显式
标 ⚠——准确率证明规则按文档工作，不等于真实失败上的泛化能力。
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codelotte.config import ConfigError
from codelotte.evals.report_utils import display_path, load_report, report_paths, short
from codelotte.session.store import load_entries

FAILURE_CLASSES: tuple[str, ...] = (
    "model",
    "tool_schema",
    "context_loss",
    "loop",
    "environment",
)

FAILURE_LABELS: dict[str, str] = {
    "model": "模型误判",
    "tool_schema": "工具 schema",
    "context_loss": "上下文丢失",
    "loop": "循环",
    "environment": "环境",
}

FAILURE_HINTS: dict[str, str] = {
    "model": "理解/决策/执行错（兜底类别）",
    "tool_schema": "工具参数畸形、缺参或调错工具",
    "context_loss": "压缩后重新读取压缩前读过的文件",
    "loop": "guardrail 拦截、迭代上限或预算耗尽",
    "environment": "沙箱/网络/依赖/验收设施故障",
}

CONFIDENCE_LABELS: dict[str, str] = {"high": "高", "medium": "中", "low": "低"}

MIN_CORPUS_SAMPLES = 10
DEFAULT_MIN_ACCURACY = 0.8

# 运行错误里出现这些标记时，先怀疑基础设施（而不是模型）。
_INFRA_MARKERS = (
    "ProviderError",
    "provider",
    "Docker",
    "docker",
    "sandbox",
    "Sandbox",
    "Connection",
    "ConnectError",
    "ConnectionError",
    "BrokenPipe",
    "BrokenPipeError",
    "OSError",
    "FileNotFoundError",
    "PermissionError",
    "No such file or directory",
    "command not found",
    "ModuleNotFoundError",
    "ImportError",
    "not found in PATH",
)

# 工具结果里的参数类错误（区别于“文件不存在”这类模型判断错误）。
_SCHEMA_ERROR_MARKERS = (
    "缺少必需参数",
    "参数不是合法 JSON",
    "参数不是 JSON 对象",
    "应为整数",
    "无法解析",
)

_FATAL_GUARDS = {"circuitBreaker", "terminate"}


class AttributionError(ConfigError):
    """归因语料/命令配置不可用（路径写错、样本不合法）——给实验者直接看。"""


@dataclass(frozen=True)
class Attribution:
    """一次失败的归因结论：五类之一 + 证据 + 置信度。"""

    failure_class: str
    confidence: str
    evidence: str
    signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttributionSample:
    """一条人工标注样本：会话路径 + 人工类别 + 可选的案例级事实。"""

    id: str
    session: str
    human_class: str
    labeler: str
    note: str = ""
    error: str | None = None
    verifier_detail: str = ""
    flagged: bool = False


@dataclass(frozen=True)
class SampleResult:
    """一条样本的分类结果（人工 vs 规则）。"""

    sample: AttributionSample
    attribution: Attribution

    @property
    def match(self) -> bool:
        return self.sample.human_class == self.attribution.failure_class


@dataclass(frozen=True)
class ClassMetrics:
    """一个类别的精确率/召回率/F1（混淆矩阵的逐类展开）。"""

    failure_class: str
    support: int  # 人工标注为该类的样本数
    predicted: int  # 规则判为该类的样本数
    true_positive: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class CorpusRun:
    """一轮语料评测：逐条结果 + 混淆矩阵。"""

    results: tuple[SampleResult, ...]
    confusion: Mapping[tuple[str, str], int]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for result in self.results if result.match)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def has_draft_labels(self) -> bool:
        return any(
            "draft" in result.sample.labeler.lower() for result in self.results
        )

    def is_acceptable(self, min_accuracy: float = DEFAULT_MIN_ACCURACY) -> bool:
        """准确率达标且标注已复核；阈值与草稿检查只在这一处定义。"""
        return self.accuracy >= min_accuracy and not self.has_draft_labels

    def per_class_counts(self) -> dict[str, tuple[int, int]]:
        """每个类别 (命中, 样本数)；没有样本的类别给 (0, 0)。"""
        totals: dict[str, list[int]] = {
            failure_class: [0, 0] for failure_class in FAILURE_CLASSES
        }
        for result in self.results:
            bucket = totals[result.sample.human_class]
            bucket[1] += 1
            if result.match:
                bucket[0] += 1
        return {key: (value[0], value[1]) for key, value in totals.items()}

    def class_metrics(self) -> tuple[ClassMetrics, ...]:
        """逐类 precision / recall / F1；没有预测或没有样本时按 0 处理。"""
        metrics: list[ClassMetrics] = []
        for failure_class in FAILURE_CLASSES:
            support = sum(
                count
                for (human, _predicted), count in self.confusion.items()
                if human == failure_class
            )
            predicted = sum(
                count
                for (_human, guess), count in self.confusion.items()
                if guess == failure_class
            )
            true_positive = self.confusion.get((failure_class, failure_class), 0)
            precision = true_positive / predicted if predicted else 0.0
            recall = true_positive / support if support else 0.0
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision + recall
                else 0.0
            )
            metrics.append(
                ClassMetrics(
                    failure_class=failure_class,
                    support=support,
                    predicted=predicted,
                    true_positive=true_positive,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                )
            )
        return tuple(metrics)

    @property
    def macro_f1(self) -> float:
        """有样本类别的 F1 算术平均；没有样本的类别不参与（无定义，不算 0）。"""
        present = [item.f1 for item in self.class_metrics() if item.support > 0]
        return sum(present) / len(present) if present else 0.0


@dataclass(frozen=True)
class FailureCase:
    """一条真实跑数里的失败案例（失败分布的一行）。"""

    run: str
    task_id: str
    bucket: str
    repetition: int
    harness: str
    failure_class: str | None
    evidence: str = ""
    session: str | None = None


@dataclass(frozen=True)
class FailureDistribution:
    """从若干 run 的 report.json 汇总的失败分布。

    只统计 `passed is False` 的案例；控制 agent 与压缩回归报表跳过。
    非 codelotte harness 的失败单独计数——归因分类器只读 codelotte 会话，
    它们不能混进五类分布。
    """

    runs: tuple[str, ...]
    cases: tuple[FailureCase, ...]
    attributed: Mapping[str, int]
    unattributed: int
    non_codelotte: int
    by_bucket: Mapping[str, Mapping[str, int]]
    skipped_control: int = 0
    skipped_incompatible: int = 0

    @property
    def total_failures(self) -> int:
        return len(self.cases)

    @property
    def codelotte_failures(self) -> int:
        return sum(self.attributed.values()) + self.unattributed


def collect_failure_distribution(
    run_dirs: Sequence[Path],
) -> FailureDistribution:
    """汇总若干 run 的失败案例；控制组/压缩报表跳过，坏报表直接报错。

    Args:
        run_dirs: run 目录或 runs 根目录；目录内的 report.json 会递归发现。

    Returns:
        FailureDistribution：五类计数、未归因数、非 codelotte 失败与桶分布。
    """
    attributed: dict[str, int] = {key: 0 for key in FAILURE_CLASSES}
    by_bucket: dict[str, dict[str, int]] = {}
    cases: list[FailureCase] = []
    runs: list[str] = []
    unattributed = 0
    non_codelotte = 0
    skipped_control = 0
    skipped_incompatible = 0
    seen_paths: set[Path] = set()

    for root in run_dirs:
        if not root.exists():
            raise AttributionError(f"跑数目录不存在：{root}")
        for path in report_paths(root):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                payload = load_report(path)
            except ValueError as exc:
                raise AttributionError(str(exc)) from exc
            meta = payload.get("meta")
            meta = meta if isinstance(meta, dict) else {}
            raw_cases = payload.get("cases")
            if not isinstance(raw_cases, list):
                skipped_incompatible += 1
                continue
            if meta.get("harness_kind") == "control":
                skipped_control += len(raw_cases)
                continue
            run_label = display_path(path.parent)
            for raw in raw_cases:
                if not isinstance(raw, dict):
                    skipped_incompatible += 1
                    continue
                passed = raw.get("passed")
                if not isinstance(passed, bool):
                    # 压缩回归报表用 completed/checkpoints，不是通用测评的案例。
                    skipped_incompatible += 1
                    continue
                if passed:
                    continue
                harness = str(raw.get("harness") or meta.get("harness") or "codelotte")
                if harness in {"oracle", "no-op", "cheating"}:
                    skipped_control += 1
                    continue
                failure_class = raw.get("failure_class")
                if failure_class not in FAILURE_CLASSES:
                    failure_class = None
                case = FailureCase(
                    run=run_label,
                    task_id=str(raw.get("task_id") or "?"),
                    bucket=str(raw.get("bucket") or "?"),
                    repetition=int(raw.get("repetition") or 1),
                    harness=harness,
                    failure_class=failure_class,
                    evidence=str(raw.get("failure_evidence") or ""),
                    session=(
                        display_path(Path(str(raw["session_path"])))
                        if raw.get("session_path") is not None
                        else None
                    ),
                )
                cases.append(case)
                if run_label not in runs:
                    runs.append(run_label)
                if harness != "codelotte":
                    non_codelotte += 1
                    continue
                key = failure_class or "unattributed"
                if failure_class is None:
                    unattributed += 1
                else:
                    attributed[failure_class] += 1
                bucket = by_bucket.setdefault(case.bucket, {})
                bucket[key] = bucket.get(key, 0) + 1

    return FailureDistribution(
        runs=tuple(runs),
        cases=tuple(cases),
        attributed=attributed,
        unattributed=unattributed,
        non_codelotte=non_codelotte,
        by_bucket={key: dict(value) for key, value in by_bucket.items()},
        skipped_control=skipped_control,
        skipped_incompatible=skipped_incompatible,
    )


def _environment(evidence: str, *, confidence: str = "high", signals: tuple[str, ...] = ()) -> Attribution:
    return Attribution("environment", confidence, short(evidence, 160), signals)


def _loop(evidence: str, *, confidence: str = "high", signals: tuple[str, ...] = ()) -> Attribution:
    return Attribution("loop", confidence, short(evidence, 160), signals)


def _tool_schema(evidence: str, *, confidence: str = "high", signals: tuple[str, ...] = ()) -> Attribution:
    return Attribution("tool_schema", confidence, short(evidence, 160), signals)


def _context_loss(evidence: str, *, signals: tuple[str, ...] = ()) -> Attribution:
    return Attribution("context_loss", "high", short(evidence, 160), signals)


def _model(evidence: str, *, confidence: str = "low", signals: tuple[str, ...] = ()) -> Attribution:
    return Attribution("model", confidence, short(evidence, 160), signals)


def _entry_type(entry: Mapping[str, Any]) -> str:
    return str(entry.get("type", ""))


def _tool_calls(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [entry for entry in entries if _entry_type(entry) == "tool_call"]


def _tool_results(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [entry for entry in entries if _entry_type(entry) == "tool_result"]


def _is_timeout(text: str) -> bool:
    lowered = text.lower()
    return "timeouterror" in lowered or "timed out" in lowered or "timeout" in lowered


def _infra_error(text: str) -> str | None:
    for marker in _INFRA_MARKERS:
        if marker in text:
            return marker
    return None


def _guardrail_events(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        entry
        for entry in entries
        if _entry_type(entry) == "event" and entry.get("kind") == "guardrail"
    ]


def _schema_signals(
    calls: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    signals: list[str] = []
    for call in calls:
        if call.get("parseError"):
            signals.append(f"parse_error:{call.get('name', '?')}")
    for result in results:
        # 只看失败的工具结果：成功读到的文件正文里出现“缺少必需参数”等字样
        # 是数据，不是工具用错了（审查修正）。
        if result.get("ok") is not False:
            continue
        content = str(result.get("content", ""))
        if "未知工具" in content:
            signals.append(f"unknown_tool:{result.get('name', '?')}")
        elif any(marker in content for marker in _SCHEMA_ERROR_MARKERS):
            signals.append(f"tool_argument:{result.get('name', '?')}")
    return tuple(signals)


def _reread_after_compaction(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[int, tuple[str, ...]]:
    """返回 (压缩次数, 压缩后重新读取的路径)。

    只统计 `read` 工具；只看“压缩前读过、压缩后又读”的路径——普通重复读取不算。
    """
    compactions = 0
    read_before: set[str] = set()
    reread: list[str] = []
    for entry in entries:
        if _entry_type(entry) == "compaction":
            compactions += 1
            continue
        if _entry_type(entry) != "tool_call" or entry.get("name") != "read":
            continue
        arguments = entry.get("arguments")
        if not isinstance(arguments, dict):
            continue
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        if compactions and path in read_before and path not in reread:
            reread.append(path)
        read_before.add(path)
    return compactions, tuple(reread)


def classify_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    error: str | None = None,
    verifier_detail: str = "",
    flagged: bool = False,
) -> Attribution:
    """按文档化的优先级给一次失败归类（纯函数，不读文件、不调模型）。

    Args:
        entries: 会话记录（session JSONL 的行）。
        error: 案例级运行错误（harness 抛出的异常文本）。
        verifier_detail: 确定性验收/ judge 的说明。
        flagged: 是否被标记（保护文件被改动）。

    Returns:
        Attribution：五类之一、证据与置信度。
    """
    error_text = error or ""
    detail = verifier_detail or ""

    # 1) 运行错误里明确的基础设施/预算信号先于轨迹内容判断。
    if "ModelCallBudgetExceeded" in error_text or "max_model_calls" in error_text:
        return _loop(
            f"模型调用超预算：{error_text}",
            signals=("budget",),
        )
    marker = _infra_error(error_text)
    if marker is not None:
        return _environment(
            f"运行错误指向基础设施（{marker}）：{error_text}",
            confidence="medium",
            signals=("infra_error",),
        )
    if _is_timeout(error_text):
        tool_calls = len(_tool_results(entries))
        if tool_calls >= 3:
            return _loop(
                f"任务超时：期间有 {tool_calls} 次工具结果，判定为反复尝试未收敛",
                confidence="medium",
                signals=("timeout",),
            )
        return _environment(
            f"任务超时：期间只有 {tool_calls} 次工具结果，更像外部阻塞",
            confidence="medium",
            signals=("timeout",),
        )
    if detail.startswith("验收异常") or detail.startswith("工作区准备失败"):
        return _environment(
            f"验收设施失败：{detail}",
            confidence="high",
            signals=("verifier_error",),
        )

    # 2) 轨迹本身不可用也是环境问题（没有证据就不能硬断成模型错）。
    if not entries:
        return _environment("没有可读的会话记录，无法看到 agent 的实际行为")

    iteration_limit = [
        entry
        for entry in entries
        if _entry_type(entry) == "event" and entry.get("kind") == "iterationLimit"
    ]
    if iteration_limit:
        return _loop(
            "触发迭代上限（模型/工具循环未在预算内收敛）",
            confidence="high",
            signals=("iteration_limit",),
        )
    guardrails = _guardrail_events(entries)
    if guardrails:
        last = guardrails[-1]
        layer = str(last.get("layer", "?"))
        guard = str(last.get("guard", "?"))
        message = str(last.get("message", "")).strip() or f"{layer} 层拦截 {guard}"
        fatal = guard in _FATAL_GUARDS or layer in {"reasoning", "planning"}
        return _loop(
            message,
            confidence="high" if fatal else "medium",
            signals=tuple(
                f"guardrail:{item.get('layer', '?')}:{item.get('guard', '?')}"
                for item in guardrails
            ),
        )

    calls = _tool_calls(entries)
    results = _tool_results(entries)
    schema_signals = _schema_signals(calls, results)
    if schema_signals:
        parse_errors = [signal for signal in schema_signals if signal.startswith("parse_error:")]
        unknown = [signal for signal in schema_signals if signal.startswith("unknown_tool:")]
        if parse_errors:
            name = parse_errors[-1].split(":", 1)[1]
            return _tool_schema(
                f"工具参数不是合法 JSON（最近一次：{name}）",
                confidence="high",
                signals=schema_signals,
            )
        if unknown:
            name = unknown[-1].split(":", 1)[1]
            return _tool_schema(
                f"调用了未知工具：{name}",
                confidence="medium",
                signals=schema_signals,
            )
        first = next(
            (
                str(result.get("content", ""))
                for result in results
                if result.get("ok") is False
                and any(
                    marker in str(result.get("content", ""))
                    for marker in _SCHEMA_ERROR_MARKERS
                )
            ),
            "工具参数不符合 schema",
        )
        return _tool_schema(
            f"工具参数错误：{first}",
            confidence="high" if len(schema_signals) >= 2 else "medium",
            signals=schema_signals,
        )

    compactions, reread = _reread_after_compaction(entries)
    if compactions and reread:
        return _context_loss(
            f"压缩 {compactions} 次后重新读取 {', '.join(reread)}"
            "（这些内容压缩前已经读过）",
            signals=(f"compaction:{compactions}", *(f"reread:{path}" for path in reread)),
        )

    # 3) 没有别的证据时归为模型判断；置信度明确标低，不冒充确定结论。
    if flagged:
        return _model(
            f"保护文件被改动（模型越界）：{detail}" if detail else "保护文件被改动（模型越界）",
            confidence="medium",
            signals=("flagged",),
        )
    if detail:
        return _model(f"确定性验收失败：{detail}")
    if error_text:
        return _model(f"运行失败但没有可识别的归因信号：{error_text}")
    return _model("没有直接信号，按兜底类别归为模型判断")


def _trajectory_unavailable(
    reason: str,
    *,
    error: str | None,
    verifier_detail: str,
    flagged: bool,
    signals: tuple[str, ...],
) -> Attribution:
    """轨迹缺失时仍先看案例级错误：预算/基础设施信号比“没有轨迹”更具体。"""
    from_error = classify_entries(
        [], error=error, verifier_detail=verifier_detail, flagged=flagged
    )
    if from_error.failure_class != "environment" or from_error.signals:
        return from_error
    return _environment(reason, signals=signals)


def classify_failure(
    session_path: Path | str | None,
    *,
    error: str | None = None,
    verifier_detail: str = "",
    flagged: bool = False,
) -> Attribution:
    """读会话文件后归类；轨迹缺失/损坏时先看案例级错误，再归环境。"""
    if session_path is None:
        return _trajectory_unavailable(
            "没有轨迹文件：无法检查 agent 的实际行为",
            error=error,
            verifier_detail=verifier_detail,
            flagged=flagged,
            signals=("missing_trajectory",),
        )
    path = Path(session_path)
    if not path.is_file():
        return _trajectory_unavailable(
            f"轨迹文件不存在：{path}",
            error=error,
            verifier_detail=verifier_detail,
            flagged=flagged,
            signals=("missing_trajectory",),
        )
    try:
        entries = load_entries(path)
    except (OSError, ValueError) as exc:
        return _trajectory_unavailable(
            f"轨迹不可读（{type(exc).__name__}: {exc}）：{path}",
            error=error,
            verifier_detail=verifier_detail,
            flagged=flagged,
            signals=("unreadable_trajectory",),
        )
    return classify_entries(
        entries, error=error, verifier_detail=verifier_detail, flagged=flagged
    )


def _require_str(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AttributionError(f"{where} 缺少非空字符串字段 {key}")
    return value


def load_attribution_samples(path: Path) -> list[AttributionSample]:
    """读人工标注语料（JSONL）；坏行/未知类别/重复 id 都直接报错。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AttributionError(f"归因样本读不动：{path}（{exc}）") from exc
    samples: list[AttributionSample] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path} 第 {number} 行"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AttributionError(f"{where} 不是合法 JSON：{exc}") from exc
        if not isinstance(raw, dict):
            raise AttributionError(f"{where} 应是 JSON 对象")
        sample_id = _require_str(raw, "id", where)
        if sample_id in seen:
            raise AttributionError(f"{where} 出现重复的样本 id：{sample_id}")
        seen.add(sample_id)
        human_class = _require_str(raw, "human_class", where)
        if human_class not in FAILURE_CLASSES:
            raise AttributionError(
                f"{where} 的 human_class 必须是 {FAILURE_CLASSES} 之一"
                f"（给了 {human_class!r}）"
            )
        labeler = _require_str(raw, "labeler", where)
        error = raw.get("case_error")
        if error is not None and not isinstance(error, str):
            raise AttributionError(f"{where} 的 case_error 要是字符串")
        verifier_detail = raw.get("verifier_detail", "")
        if not isinstance(verifier_detail, str):
            raise AttributionError(f"{where} 的 verifier_detail 要是字符串")
        flagged = raw.get("flagged", False)
        if not isinstance(flagged, bool):
            raise AttributionError(f"{where} 的 flagged 要是布尔值")
        note = raw.get("note", "")
        if not isinstance(note, str):
            raise AttributionError(f"{where} 的 note 要是字符串")
        samples.append(
            AttributionSample(
                id=sample_id,
                session=_require_str(raw, "session", where),
                human_class=human_class,
                labeler=labeler,
                note=note,
                error=error,
                verifier_detail=verifier_detail,
                flagged=flagged,
            )
        )
    if not samples:
        raise AttributionError(f"归因样本为空：{path}")
    return samples


def evaluate_corpus(
    samples: Sequence[AttributionSample], *, base_dir: Path
) -> CorpusRun:
    """逐条跑分类器，算准确率与混淆矩阵（会话路径相对 base_dir）。"""
    results: list[SampleResult] = []
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    for sample in samples:
        attribution = classify_failure(
            base_dir / sample.session,
            error=sample.error,
            verifier_detail=sample.verifier_detail,
            flagged=sample.flagged,
        )
        results.append(SampleResult(sample=sample, attribution=attribution))
        confusion[(sample.human_class, attribution.failure_class)] += 1
    return CorpusRun(results=tuple(results), confusion=dict(confusion))


def _confusion_table(run: CorpusRun) -> list[str]:
    header = "| 人工 \\ 规则 | " + " | ".join(
        FAILURE_LABELS[key] for key in FAILURE_CLASSES
    ) + " | 样本 |"
    divider = "|---|" + "---|" * (len(FAILURE_CLASSES) + 1)
    lines = [header, divider]
    for human in FAILURE_CLASSES:
        counts = [run.confusion.get((human, predicted), 0) for predicted in FAILURE_CLASSES]
        total = sum(counts)
        lines.append(
            f"| {FAILURE_LABELS[human]} | "
            + " | ".join(str(count) for count in counts)
            + f" | {total} |"
        )
    return lines


def _metrics_table(run: CorpusRun) -> list[str]:
    lines = [
        "| 类别 | 精确率 | 召回率 | F1 | 预测数 | 样本数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in run.class_metrics():
        lines.append(
            f"| {FAILURE_LABELS[item.failure_class]} | {item.precision:.3f} | "
            f"{item.recall:.3f} | {item.f1:.3f} | {item.predicted} | {item.support} |"
        )
    lines.append(f"| **宏观 F1** | — | — | **{run.macro_f1:.3f}** | — | — |")
    return lines


def _distribution_section(distribution: FailureDistribution) -> list[str]:
    lines = [
        "## 失败分布",
        "",
        f"> 来源：{len(distribution.runs)} 个 run 的失败案例（扫描全部 `report.json`）；"
        f"控制 agent 跳过 {distribution.skipped_control} 条，"
        f"非通用测评案例跳过 {distribution.skipped_incompatible} 条。",
        "",
    ]
    if distribution.total_failures == 0:
        lines.extend(
            [
                "所选 run 没有 codelotte 失败案例；五类分布为空。"
                "这不代表归因器在真实失败上可靠——该结论需要失败案例才能回答。",
                "",
            ]
        )
        return lines
    lines.extend(
        [
            f"- codelotte 失败：{distribution.codelotte_failures} 条"
            f"（已归因 {sum(distribution.attributed.values())}，"
            f"未归因 {distribution.unattributed}）。",
            f"- 非 codelotte harness 失败：{distribution.non_codelotte} 条"
            "（轨迹格式不同，不进入五类分布）。",
            "",
            "| 类别 | 数量 |",
            "|---|---:|",
        ]
    )
    for failure_class in FAILURE_CLASSES:
        lines.append(
            f"| {FAILURE_LABELS[failure_class]} | {distribution.attributed[failure_class]} |"
        )
    if distribution.unattributed:
        lines.append(f"| 未归因 | {distribution.unattributed} |")
    lines.append("")
    if distribution.by_bucket:
        lines.extend(
            [
                "| 桶 | 失败数 | 类别分布 |",
                "|---|---:|---|",
            ]
        )
        for bucket in sorted(distribution.by_bucket):
            counts = distribution.by_bucket[bucket]
            total = sum(counts.values())
            detail = " · ".join(
                f"{FAILURE_LABELS.get(key, key)} {value}"
                for key, value in sorted(counts.items())
            )
            lines.append(f"| {bucket} | {total} | {detail} |")
        lines.append("")
    lines.extend(
        [
            "| run | 任务 | 重复 | 桶 | harness | 类别 | 证据 |",
            "|---|---|---:|---|---|---|---|",
        ]
    )
    for case in distribution.cases:
        label = (
            FAILURE_LABELS.get(case.failure_class, case.failure_class)
            if case.failure_class
            else "未归因"
        )
        lines.append(
            f"| `{case.run}` | `{case.task_id}` | r{case.repetition} | "
            f"{case.bucket} | {case.harness} | {label} | {short(case.evidence, 80)} |"
        )
    lines.append("")
    return lines


def render_attribution_markdown(
    run: CorpusRun,
    *,
    samples_path: Path,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
    distribution: FailureDistribution | None = None,
) -> str:
    """把语料评测渲染成可提交的报告（含混淆矩阵、逐类指标与失败分布）。"""
    draft = run.has_draft_labels
    passed = run.is_acceptable(min_accuracy)
    per_class = run.per_class_counts()
    lines = [
        "# 失败归因准确率（首版）",
        "",
        f"> 语料：`{display_path(samples_path)}` · {run.total} 条失败样本；"
        f"规则见 `evals/attribution.md`。",
        "",
        "## 结论速览",
        "",
        f"- 准确率：{run.correct}/{run.total}（{run.accuracy:.1%}），"
        f"阈值 {min_accuracy:.0%}；宏观 F1 {run.macro_f1:.3f}",
    ]
    if draft:
        lines.append(
            "- 标注者：包含 `draft`（作者草稿），"
            "⚠ **本轮准确率只证明规则按文档工作，不是人工复核后的泛化结论**。"
        )
    else:
        lines.append("- 标注者：已复核（不含 draft 标记）")
    lines.extend(
        [
            f"- 判定：{'✅ 达标' if passed else '⚠ 未达标/待复核'}",
            "",
            "| 类别 | 命中 / 样本 |",
            "|---|---|",
        ]
    )
    for failure_class in FAILURE_CLASSES:
        hit, total = per_class[failure_class]
        lines.append(f"| {FAILURE_LABELS[failure_class]} | {hit} / {total} |")
    lines.extend(
        [
            "",
            "### 逐类指标",
            "",
            *_metrics_table(run),
            "",
            "读法：精确率的分母是“规则判为该类”的样本数，召回率的分母是"
            "“人工标为该类”的样本数；宏观 F1 只平均有样本的类别。",
            "",
            "## 混淆矩阵",
            "",
            *_confusion_table(run),
            "",
            "读法：行是人工标注，列是规则判定；对角线是命中。"
            "没有样本的类别记 0，不代表规则在该类别上可靠。",
            "",
            "## 逐条结果",
            "",
            "| 样本 | 人工 | 规则 | 置信度 | 证据 |",
            "|---|---|---|---|---|",
        ]
    )
    for result in run.results:
        mark = "✅" if result.match else "❌"
        lines.append(
            f"| `{result.sample.id}` | {FAILURE_LABELS[result.sample.human_class]} | "
            f"{FAILURE_LABELS[result.attribution.failure_class]} {mark} | "
            f"{CONFIDENCE_LABELS.get(result.attribution.confidence, result.attribution.confidence)} | "
            f"{result.attribution.evidence} |"
        )
    lines.append("")
    if distribution is not None:
        lines.extend(_distribution_section(distribution))
    lines.extend(
        [
            "## 口径与局限",
            "",
            "- 分类器是**规则版 v0**：只读会话记录（工具调用/结果、guardrail、压缩、"
            "迭代上限）与案例级错误，不调用模型，不读最终工作区内容。",
            "- 优先级：环境 > 循环 > 工具 schema > 上下文丢失 > 模型兜底；"
            "先命中的规则胜出，置信度随证据强度变化。",
            "- 首版语料是作者按五类构造的失败轨迹（`labeler=author-draft`），"
            "存在天花板效应；真实失败上的准确率需要作者用真实跑数复核。",
            "- 失败分布只统计 `passed=false` 的通用测评案例；控制 agent、压缩回归报表"
            "与非 codelotte harness 不混入五类分布。",
            "- 归因只对 codelotte harness 的轨迹有意义；mini-swe-agent / 裸 API "
            "的轨迹格式不同，报表里不归因。",
            "",
        ]
    )
    return "\n".join(lines)


def _distribution_payload(distribution: FailureDistribution) -> dict[str, Any]:
    return {
        "runs": list(distribution.runs),
        "total_failures": distribution.total_failures,
        "codelotte_failures": distribution.codelotte_failures,
        "attributed": dict(distribution.attributed),
        "unattributed": distribution.unattributed,
        "non_codelotte": distribution.non_codelotte,
        "by_bucket": {
            bucket: dict(counts) for bucket, counts in distribution.by_bucket.items()
        },
        "skipped_control": distribution.skipped_control,
        "skipped_incompatible": distribution.skipped_incompatible,
        "cases": [
            {
                "run": case.run,
                "task_id": case.task_id,
                "bucket": case.bucket,
                "repetition": case.repetition,
                "harness": case.harness,
                "failure_class": case.failure_class,
                "evidence": case.evidence,
                "session": case.session,
            }
            for case in distribution.cases
        ],
    }


def build_attribution_report(
    out_dir: Path,
    run: CorpusRun,
    *,
    samples_path: Path,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
    distribution: FailureDistribution | None = None,
) -> Path:
    """写 attribution-report.md / .json，返回 Markdown 路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_attribution_markdown(
        run,
        samples_path=samples_path,
        min_accuracy=min_accuracy,
        distribution=distribution,
    )
    path = out_dir / "attribution-report.md"
    path.write_text(markdown, encoding="utf-8", newline="\n")
    confusion: dict[str, dict[str, int]] = {
        human: {
            predicted: run.confusion.get((human, predicted), 0)
            for predicted in FAILURE_CLASSES
        }
        for human in FAILURE_CLASSES
    }
    payload = {
        "samples": display_path(samples_path),
        "total": run.total,
        "correct": run.correct,
        "accuracy": run.accuracy,
        "macro_f1": run.macro_f1,
        "min_accuracy": min_accuracy,
        "draft_labels": run.has_draft_labels,
        "confusion": confusion,
        "class_metrics": [
            {
                "failure_class": item.failure_class,
                "support": item.support,
                "predicted": item.predicted,
                "true_positive": item.true_positive,
                "precision": item.precision,
                "recall": item.recall,
                "f1": item.f1,
            }
            for item in run.class_metrics()
        ],
        "failure_distribution": (
            _distribution_payload(distribution)
            if distribution is not None
            else None
        ),
        "results": [
            {
                "id": result.sample.id,
                "session": result.sample.session,
                "human_class": result.sample.human_class,
                "labeler": result.sample.labeler,
                "predicted": result.attribution.failure_class,
                "confidence": result.attribution.confidence,
                "evidence": result.attribution.evidence,
                "signals": list(result.attribution.signals),
            }
            for result in run.results
        ],
    }
    (out_dir / "attribution-report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
