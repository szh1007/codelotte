"""失败轨迹 → 可跑回归任务（票据 18）。

转换保留原任务的定义（setup / verifier / checkpoints / 预算 / 参考解），只换 `id`
并在文件头写明来源与归因。这样“修过的坑”能作为一条独立任务再次跑 `eval run`，
而不会混进原任务的历史跑数指纹。

生成器不做任何 TOML 重排：直接在原文上替换 `id` 行，避免手写序列化丢失字段或
改写字符串转义。写盘前调用方会再用 `load_task` 校验（CLI 负责）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from codelotte.config import ConfigError
from codelotte.evals.attribution import CONFIDENCE_LABELS, FAILURE_LABELS, Attribution
from codelotte.evals.report_utils import short

_ID_LINE = re.compile(r'(?m)^[ \t]*id[ \t]*=[ \t]*(["\'])(.*?)\1[ \t]*(?:#.*)?$')


class RegressionTaskError(ConfigError):
    """回归任务生成失败（源文件没有 id、目标已存在等）——给实验者直接看。"""


def next_regression_id(source_id: str, existing_ids: set[str]) -> str:
    """生成不与现有任务冲突的 id：`regression-<源 id>`，冲突时追加 -2、-3…"""
    candidate = f"regression-{source_id}"
    if candidate not in existing_ids:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in existing_ids:
        suffix += 1
    return f"{candidate}-{suffix}"


def build_regression_task(
    source_path: Path,
    *,
    source_id: str,
    new_id: str,
    run_id: str,
    repetition: int,
    attribution: Attribution | None,
    detail: str,
    generated_at: str,
) -> str:
    """读原任务文本，替换 id 并加来源头；返回新 TOML 文本（不写盘）。"""
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegressionTaskError(f"原任务文件读不动：{source_path}（{exc}）") from exc
    matches = list(_ID_LINE.finditer(text))
    if len(matches) != 1:
        raise RegressionTaskError(
            f"{source_path} 里找不到唯一的 id 行（找到 {len(matches)} 处），"
            "无法安全生成回归任务"
        )
    match = matches[0]
    replaced = (
        text[: match.start()]
        + f"id = {json.dumps(new_id, ensure_ascii=False)}"
        + text[match.end() :]
    )
    if attribution is None:
        attribution_line = "# 归因：不可用（该失败案例没有 codelotte 轨迹）"
    else:
        label = FAILURE_LABELS.get(
            attribution.failure_class, attribution.failure_class
        )
        confidence = CONFIDENCE_LABELS.get(
            attribution.confidence, attribution.confidence
        )
        attribution_line = (
            f"# 归因：{label}（{confidence}）—— {short(attribution.evidence, 160)}"
        )
    header = [
        "# 失败回归任务（票据 18）：由 `codelotte eval regression` 生成。",
        f"# 来源：run {run_id} / {source_id} r{repetition}",
        attribution_line,
    ]
    if detail:
        header.append(f"# 失败详情：{short(detail, 160)}")
    header.append(f"# 生成时间：{generated_at}")
    return "\n".join(header) + "\n\n" + replaced


def write_regression_task(path: Path, text: str) -> Path:
    """写新任务文件；绝不覆盖已有文件（回归任务是证据，不能被静默改写）。"""
    if path.exists():
        raise RegressionTaskError(f"目标文件已存在，不覆盖：{path}；用 --out 指定新路径")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
