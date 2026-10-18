"""LLM judge 兜底与 κ 校准（票据 17）。

职责边界：
- judge 是 verifier 的可选兜底，只在任务写了 `[verifier.judge]` 时启用；
- 确定性检查先跑；确定性失败不调用 judge；确定性通过（或没有确定性检查）才让
  judge 做最终判定；
- 校准是独立命令（`codelotte eval judge`）：用 ≥20 条人工标注样本算 Cohen's κ，
  把结果写成 JSON；评测运行时只读结果，κ 低就在报表里标警告。

judge 的请求/计价复用 `StreamingClient` 与项目价目表；judge 的 usage 计入案例总成本。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codelotte import __version__
from codelotte.config import ConfigError
from codelotte.cost import Catalog, format_money, price_call
from codelotte.evals.report_utils import short
from codelotte.evals.tasks import Judge
from codelotte.loop import StreamingClient
from codelotte.providers.base import StreamUsage, TextDelta, UsageEvent

logger = logging.getLogger(__name__)

MIN_CALIBRATION_SAMPLES = 20
CALIBRATION_SCHEMA = "judge-calibration/v1"


class JudgeError(ConfigError):
    """judge 配置/校准/解析失败（给调用方一个可读错误）。"""


@dataclass(frozen=True)
class JudgeContext:
    """judge 调用所需的模型资源（由 CLI 装配，评测核心只消费）。"""

    client_factory: Callable[[], StreamingClient]
    model: str
    catalog: Catalog


@dataclass(frozen=True)
class ParsedJudge:
    scores: tuple[tuple[str, float], ...]
    reasons: tuple[tuple[str, str], ...]
    overall: float


@dataclass(frozen=True)
class JudgeRun:
    """一次 judge 调用的结果（含成本；失败时 passed/overall 为 None）。"""

    passed: bool | None
    overall: float | None
    scores: tuple[tuple[str, float], ...]
    reasons: tuple[tuple[str, str], ...]
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    period: str | None
    error: str | None = None


@dataclass(frozen=True)
class Calibration:
    kappa: float | None
    agreement: float | None
    samples: int
    kappa_threshold: float
    pass_threshold: float
    labeler: str
    generated_at: str
    # 绑定字段：校准时锁定的任务/模型/样本指纹；缺失时运行时只能按 κ 粗判
    task_id: str = ""
    model: str = ""
    labels_sha256: str | None = None
    judge_fingerprint: str | None = None


@dataclass(frozen=True)
class JudgeSample:
    id: str
    submission: str
    human_pass: bool
    labeler: str


@dataclass(frozen=True)
class CalibrationSampleResult:
    sample_id: str
    human_pass: bool
    judge_passed: bool | None
    overall: float | None
    scores: tuple[tuple[str, float], ...]
    reasons: tuple[tuple[str, str], ...]
    error: str | None


@dataclass(frozen=True)
class CalibrationRun:
    model: str
    samples: int
    labeler: str
    kappa: float | None
    agreement: float
    results: tuple[CalibrationSampleResult, ...]
    cost: float
    periods: tuple[tuple[str, int], ...]


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except ValueError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise JudgeError(f"judge 输出不是 JSON：{short(stripped, 300)}")
        try:
            return json.loads(stripped[start : end + 1])
        except ValueError as exc:
            raise JudgeError(
                f"judge 输出不是合法 JSON：{exc}；原文 {short(stripped, 300)}"
            ) from exc


def parse_judge_payload(text: str, dimensions: tuple[str, ...]) -> ParsedJudge:
    """严格解析评分卡：每个维度都要有 0–1 分数和非空理由。"""
    payload = _extract_json(text)
    if not isinstance(payload, dict):
        raise JudgeError("judge 输出顶层应是 JSON 对象")
    scores_raw = payload.get("scores")
    reasons_raw = payload.get("reasons")
    if not isinstance(scores_raw, dict) or not isinstance(reasons_raw, dict):
        raise JudgeError("judge 输出缺少 scores/reasons 对象")
    scores: list[tuple[str, float]] = []
    reasons: list[tuple[str, str]] = []
    for dimension in dimensions:
        score = scores_raw.get(dimension)
        reason = reasons_raw.get(dimension)
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0 <= float(score) <= 1
        ):
            raise JudgeError(f"judge 维度 {dimension!r} 的分数不在 0–1：{score!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise JudgeError(f"judge 维度 {dimension!r} 缺少理由")
        scores.append((dimension, float(score)))
        reasons.append((dimension, reason.strip()))
    overall = sum(score for _, score in scores) / len(scores)
    return ParsedJudge(
        scores=tuple(scores), reasons=tuple(reasons), overall=overall
    )


def judge_fingerprint(task_id: str, instruction: str, judge: Judge) -> str:
    """锁定一份 judge 评分卡：任务/指令/维度/rubric/阈值任一变化都应重跑校准。"""
    payload = {
        "task_id": task_id,
        "instruction": instruction,
        "dimensions": list(judge.dimensions),
        "rubric": judge.rubric,
        "pass_threshold": judge.pass_threshold,
        "kappa_threshold": judge.kappa_threshold,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        logger.warning("文件哈希读不动：%s（%s: %s）", path, type(exc).__name__, exc)
        return None


def build_submission(workspace: Path, *, max_chars: int) -> str:
    """把最终工作区压成给 judge 看的文本（有总长度上限，二进制只记元信息）。"""
    parts: list[str] = []
    used = 0
    omitted = 0
    files = sorted(path for path in workspace.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(workspace).as_posix()
        try:
            size = path.stat().st_size
            data = path.read_bytes()
        except OSError as exc:
            parts.append(f"### {relative}\n[unreadable: {type(exc).__name__}]")
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            parts.append(f"### {relative} ({size} bytes, binary)\n[binary omitted]")
            continue
        remaining = max_chars - used
        if remaining <= 0:
            omitted += 1
            continue
        chunk = text[:remaining]
        header = f"### {relative} ({size} bytes)"
        if len(chunk) < len(text):
            chunk += "\n… (file truncated)"
        parts.append(f"{header}\n{chunk}")
        used += len(chunk)
    if omitted:
        parts.append(f"… (submission truncated; {omitted} more files omitted)")
    if not parts:
        return "(empty workspace)"
    return "\n\n".join(parts)


def build_judge_messages(
    *,
    instruction: str,
    judge: Judge,
    submission: str,
    deterministic_detail: str,
) -> list[dict[str, str]]:
    system = (
        "You are a strict, consistent evaluator for a coding-agent benchmark. "
        "Score only against the rubric and the submission. "
        "Return a single JSON object with exactly this shape:\n"
        '{"scores": {"<dimension>": <number 0..1>, ...}, '
        '"reasons": {"<dimension>": "<short reason>", ...}}\n'
        "No markdown fences, no extra keys."
    )
    dimensions = "\n".join(f"- {dimension}" for dimension in judge.dimensions)
    user = (
        f"# Task instruction\n{instruction}\n\n"
        f"# Rubric\n{judge.rubric}\n\n"
        f"# Dimensions\n{dimensions}\n\n"
        f"# Deterministic checks\n{deterministic_detail or '无'}\n\n"
        f"# Submission\n{submission}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def run_judge_submission(
    context: JudgeContext,
    *,
    instruction: str,
    judge: Judge,
    submission: str,
    deterministic_detail: str,
) -> JudgeRun:
    """一次无工具 judge 调用；任何失败都返回 error，不抛给 runner。"""
    messages = build_judge_messages(
        instruction=instruction,
        judge=judge,
        submission=submission,
        deterministic_detail=deterministic_detail,
    )
    text_parts: list[str] = []
    usage: StreamUsage | None = None
    error: str | None = None
    attempted = False
    try:
        client = context.client_factory()
        attempted = True
        async with asyncio.timeout(judge.timeout_seconds):
            async for event in client.stream_chat(messages, tools=None):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                elif isinstance(event, UsageEvent):
                    usage = event.usage
    except Exception as exc:  # provider/网络/超时统一落成 error；不掀翻整轮
        logger.warning("judge 调用失败：%s: %s", type(exc).__name__, exc)
        error = f"{type(exc).__name__}: {exc}"

    at = datetime.now(timezone.utc)
    priced = (
        price_call(context.catalog, context.model, usage, at=at)
        if usage is not None
        else None
    )
    raw = "".join(text_parts)
    parsed: ParsedJudge | None = None
    if error is None:
        try:
            parsed = parse_judge_payload(raw, judge.dimensions)
        except JudgeError as exc:
            error = str(exc)
    return JudgeRun(
        passed=(parsed.overall >= judge.pass_threshold) if parsed else None,
        overall=parsed.overall if parsed else None,
        scores=parsed.scores if parsed else (),
        reasons=parsed.reasons if parsed else (),
        calls=1 if attempted else 0,
        input_tokens=usage.input_tokens if usage is not None else 0,
        output_tokens=usage.output_tokens if usage is not None else 0,
        cost=(priced.cost or 0.0) if priced is not None else 0.0,
        period=priced.period if priced is not None else None,
        error=error,
    )


def cohen_kappa(
    judge_passes: Sequence[bool], human_passes: Sequence[bool]
) -> tuple[float | None, float]:
    """二分类 Cohen's κ；单一类别导致 pe=1 时 κ 无定义，返回 (None, agreement)。"""
    if len(judge_passes) != len(human_passes):
        raise ValueError("judge/human 标签数量不一致")
    total = len(judge_passes)
    if total == 0:
        return None, 0.0
    agreement = sum(a == b for a, b in zip(judge_passes, human_passes)) / total
    judge_true = sum(judge_passes) / total
    human_true = sum(human_passes) / total
    expected = judge_true * human_true + (1 - judge_true) * (1 - human_true)
    if expected >= 1.0:
        return None, agreement
    return (agreement - expected) / (1 - expected), agreement


def load_samples(path: Path) -> list[JudgeSample]:
    """读校准样本 JSONL；每行都要有 id / submission / human_pass / labeler。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise JudgeError(f"校准样本读不动：{path}（{exc}）") from exc
    samples: list[JudgeSample] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise JudgeError(f"{path} 第 {number} 行不是 JSON：{exc}") from exc
        if not isinstance(raw, dict):
            raise JudgeError(f"{path} 第 {number} 行应是对象")
        sample_id = raw.get("id")
        submission = raw.get("submission")
        human_pass = raw.get("human_pass")
        labeler = raw.get("labeler")
        if not isinstance(sample_id, str) or not sample_id.strip():
            raise JudgeError(f"{path} 第 {number} 行缺少 id")
        if sample_id in seen:
            raise JudgeError(f"{path} 的 id 重复：{sample_id!r}")
        if not isinstance(submission, str) or not submission.strip():
            raise JudgeError(f"{path} 的 {sample_id!r} 缺少 submission")
        if not isinstance(human_pass, bool):
            raise JudgeError(f"{path} 的 {sample_id!r} 的 human_pass 要是布尔值")
        if not isinstance(labeler, str) or not labeler.strip():
            raise JudgeError(f"{path} 的 {sample_id!r} 缺少 labeler")
        seen.add(sample_id)
        samples.append(
            JudgeSample(
                id=sample_id,
                submission=submission,
                human_pass=human_pass,
                labeler=labeler,
            )
        )
    return samples


async def calibrate(
    context: JudgeContext,
    *,
    instruction: str,
    judge: Judge,
    samples: Sequence[JudgeSample],
    progress: Callable[[str], None] | None = None,
) -> CalibrationRun:
    """逐条跑 judge，和人工标签算 κ；少于 20 条直接拒绝。"""
    if len(samples) < MIN_CALIBRATION_SAMPLES:
        raise JudgeError(
            f"校准需要 ≥{MIN_CALIBRATION_SAMPLES} 条样本（当前 {len(samples)} 条）"
        )
    results: list[CalibrationSampleResult] = []
    judge_passes: list[bool] = []
    human_passes: list[bool] = []
    cost = 0.0
    periods: dict[str, int] = {}
    for index, sample in enumerate(samples, start=1):
        if progress is not None:
            progress(f"[{index}/{len(samples)}] {sample.id} …")
        run = await run_judge_submission(
            context,
            instruction=instruction,
            judge=judge,
            submission=sample.submission,
            deterministic_detail="（校准样本，无确定性检查）",
        )
        cost += run.cost
        if run.period is not None:
            periods[run.period] = periods.get(run.period, 0) + 1
        results.append(
            CalibrationSampleResult(
                sample_id=sample.id,
                human_pass=sample.human_pass,
                judge_passed=run.passed,
                overall=run.overall,
                scores=run.scores,
                reasons=run.reasons,
                error=run.error,
            )
        )
        if run.error is not None or run.passed is None:
            raise JudgeError(f"样本 {sample.id} judge 失败：{run.error or '没有判定'}")
        judge_passes.append(run.passed)
        human_passes.append(sample.human_pass)
    kappa, agreement = cohen_kappa(judge_passes, human_passes)
    labelers = {sample.labeler for sample in samples}
    labeler = labelers.pop() if len(labelers) == 1 else "mixed"
    return CalibrationRun(
        model=context.model,
        samples=len(samples),
        labeler=labeler,
        kappa=kappa,
        agreement=agreement,
        results=tuple(results),
        cost=cost,
        periods=tuple(sorted(periods.items())),
    )


def judge_reliability(
    judge: Judge,
    calibration: Calibration | None,
    *,
    task_id: str | None = None,
    instruction: str | None = None,
    model: str | None = None,
    labels_sha256: str | None = None,
) -> tuple[bool, str | None]:
    """κ 可靠性判定；返回 (reliable, warning)。

    除了样本数/κ 阈值，还检查校准是否仍绑定当前 judge：
    task_id / 指令+rubric 指纹 / 模型 / 样本文件哈希任一变化都不再采信旧 κ。
    `labeler` 带 `draft` 的校准只算草稿值：κ 可以展示，但不能当“人工已复核”用。
    """
    if calibration is None:
        return False, "未配置校准文件，judge 结果不可靠"
    warnings: list[str] = []
    if task_id is not None and calibration.task_id:
        if calibration.task_id != task_id:
            warnings.append(
                f"校准绑定任务 {calibration.task_id!r}，不是 {task_id!r}；重跑 eval judge"
            )
    if instruction is not None:
        expected = judge_fingerprint(task_id or calibration.task_id, instruction, judge)
        if calibration.judge_fingerprint and calibration.judge_fingerprint != expected:
            warnings.append("任务指令/rubric/阈值已变，校准已过期；重跑 eval judge")
    if model is not None and calibration.model and calibration.model != model:
        warnings.append(
            f"校准绑定模型 {calibration.model!r}，不是 {model!r}；重跑 eval judge"
        )
    if (
        labels_sha256 is not None
        and calibration.labels_sha256
        and calibration.labels_sha256 != labels_sha256
    ):
        warnings.append("校准样本文件已变，校准已过期；重跑 eval judge")
    if calibration.kappa_threshold != judge.kappa_threshold:
        warnings.append(
            f"校准 κ 阈值 {calibration.kappa_threshold:.2f} 与任务 "
            f"{judge.kappa_threshold:.2f} 不一致；重跑 eval judge"
        )
    if calibration.pass_threshold != judge.pass_threshold:
        warnings.append(
            f"校准通过阈值 {calibration.pass_threshold:.2f} 与任务 "
            f"{judge.pass_threshold:.2f} 不一致；重跑 eval judge"
        )
    if calibration.samples < MIN_CALIBRATION_SAMPLES:
        warnings.append(
            f"校准样本 {calibration.samples} < {MIN_CALIBRATION_SAMPLES}"
        )
    if calibration.kappa is None:
        warnings.append("κ 无法计算（人工标签只有单一类别）")
    elif calibration.kappa < judge.kappa_threshold:
        warnings.append(
            f"κ={calibration.kappa:.2f} < 阈值 {judge.kappa_threshold:.2f}，"
            "judge 验收器不可靠"
        )
    if "draft" in calibration.labeler.lower():
        warnings.append(
            f"标注者 {calibration.labeler} 尚未复核，κ 是草稿值"
        )
    if warnings:
        return False, "；".join(warnings)
    return True, None


def load_calibration(path: Path) -> Calibration:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise JudgeError(f"校准文件读不动：{path}（{exc}）") from exc
    except ValueError as exc:
        raise JudgeError(f"校准文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise JudgeError(f"校准文件顶层应是对象：{path}")
    if raw.get("schema") != CALIBRATION_SCHEMA:
        raise JudgeError(
            f"校准文件 schema 不是 {CALIBRATION_SCHEMA}：{path}"
        )
    samples = raw.get("samples")
    kappa = raw.get("kappa")
    agreement = raw.get("agreement")
    kappa_threshold = raw.get("kappa_threshold")
    pass_threshold = raw.get("pass_threshold")
    labeler = raw.get("labeler")
    generated_at = raw.get("generated_at")
    if not isinstance(samples, int) or isinstance(samples, bool) or samples < 0:
        raise JudgeError(f"校准文件 samples 不合法：{path}")
    if kappa is not None and not isinstance(kappa, (int, float)):
        raise JudgeError(f"校准文件 kappa 不合法：{path}")
    if not isinstance(agreement, (int, float)):
        raise JudgeError(f"校准文件 agreement 不合法：{path}")
    if not isinstance(kappa_threshold, (int, float)):
        raise JudgeError(f"校准文件 kappa_threshold 不合法：{path}")
    if not isinstance(pass_threshold, (int, float)):
        raise JudgeError(f"校准文件 pass_threshold 不合法：{path}")
    if not isinstance(labeler, str) or not labeler.strip():
        raise JudgeError(f"校准文件缺少 labeler：{path}")
    if not isinstance(generated_at, str) or not generated_at:
        raise JudgeError(f"校准文件缺少 generated_at：{path}")
    task_id = raw.get("task_id")
    model = raw.get("model")
    labels_sha256 = raw.get("labels_sha256")
    fingerprint = raw.get("judge_fingerprint")
    return Calibration(
        kappa=float(kappa) if kappa is not None else None,
        agreement=float(agreement),
        samples=samples,
        kappa_threshold=float(kappa_threshold),
        pass_threshold=float(pass_threshold),
        labeler=labeler,
        generated_at=generated_at,
        task_id=task_id if isinstance(task_id, str) else "",
        model=model if isinstance(model, str) else "",
        labels_sha256=labels_sha256 if isinstance(labels_sha256, str) else None,
        judge_fingerprint=fingerprint if isinstance(fingerprint, str) else None,
    )


def render_calibration_markdown(
    *, task_id: str, model: str, judge: Judge, run: CalibrationRun
) -> str:
    reliable, warning = judge_reliability(
        judge,
        Calibration(
            kappa=run.kappa,
            agreement=run.agreement,
            samples=run.samples,
            kappa_threshold=judge.kappa_threshold,
            pass_threshold=judge.pass_threshold,
            labeler=run.labeler,
            generated_at="",
        ),
    )
    lines = [
        f"# LLM judge 校准：{task_id}",
        "",
        f"- 模型：`{model}`",
        f"- 样本：{run.samples}（标注者：{run.labeler}）",
        f"- 一致率：{run.agreement:.1%}",
        (
            f"- Cohen's κ：{run.kappa:.3f}" if run.kappa is not None else "- Cohen's κ：无法计算"
        ),
        f"- κ 阈值：{judge.kappa_threshold:.2f}；通过阈值：{judge.pass_threshold:.2f}",
        f"- 结论：{'✅ 可靠' if reliable else '⚠ 不可靠'}"
        + (f"（{warning}）" if warning else ""),
        f"- 校准成本：{format_money(run.cost, 'CNY')}",
        "",
        "| 样本 | 人工 | judge | overall | 维度分数 | 理由 |",
        "|---|---|---|---|---|---|",
    ]
    for result in run.results:
        judge_mark = "✅" if result.judge_passed else "❌"
        human_mark = "✅" if result.human_pass else "❌"
        scores = " · ".join(f"{name}={score:.2f}" for name, score in result.scores)
        reasons = "；".join(
            f"{name}: {short(reason, 80)}" for name, reason in result.reasons
        )
        overall_text = (
            f"{result.overall:.2f}" if result.overall is not None else "—"
        )
        lines.append(
            f"| {result.sample_id} | {human_mark} | {judge_mark} | "
            f"{overall_text} | {scores} | {short(reasons, 160)} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_calibration(
    path: Path,
    *,
    task_id: str,
    instruction: str,
    judge: Judge,
    run: CalibrationRun,
    labels_path: Path,
) -> Path:
    """写 calibration.json 与同名 .md；返回 JSON 路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": CALIBRATION_SCHEMA,
        "task_id": task_id,
        "model": run.model,
        "samples": run.samples,
        "labeler": run.labeler,
        "kappa": run.kappa,
        "agreement": run.agreement,
        "kappa_threshold": judge.kappa_threshold,
        "pass_threshold": judge.pass_threshold,
        "generated_at": generated_at,
        "codelotte_version": __version__,
        "judge_fingerprint": judge_fingerprint(task_id, instruction, judge),
        "labels_sha256": file_sha256(labels_path),
        "total_cost": run.cost,
        "periods": run.periods,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    path.with_suffix(".md").write_text(
        render_calibration_markdown(
            task_id=task_id, model=run.model, judge=judge, run=run
        ),
        encoding="utf-8",
        newline="\n",
    )
    return path
