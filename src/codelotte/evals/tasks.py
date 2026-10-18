"""评测任务定义（票据 13 v0 → 票据 15 通用格式）：TOML → Task。

任务字段：id / bucket / instruction / setup（初始文件或仓库快照）/ verifier / 预算。
checkpoints 是压缩回归的选配项（票据 13），通用测评 不需要；`eval compaction`
会显式拒绝没有 checkpoint 的任务。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codelotte.config import ConfigError

DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_MODEL_CALLS = 40
DEFAULT_SNAPSHOT_TIMEOUT_SECONDS = 120.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 60.0


class TaskFileError(ConfigError):
    """任务文件不可用（缺字段、类型不对、路径越界等）——直接给实验者看。

    继承 ConfigError：任务文件是实验配置，CLI 统一按"用法/配置错"返回退出码 2。
    """


@dataclass(frozen=True)
class FileExpectation:
    """验收器对工作区文件的一条期望：三种模式只能选一种。"""

    path: str
    equals: str | None = None
    contains: str | None = None
    unchanged: bool = False


@dataclass(frozen=True)
class Checkpoint:
    """一个 checkpoint 问题与它的确定性事实组。

    facts 是"事实组"列表：每组是一组可接受的替代表述（任一命中即可），
    所有组都命中才算这个问题通过。例如：
    [["report.txt"], ["TODO", "待办"], ["次数", "计数"]]。
    """

    question: str
    facts: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Snapshot:
    """任务的可复现起点：从 git ref 抽出仓库快照，再跑可选初始化脚本。

    repo 是相对评测仓库根的路径（默认就是评测仓库本身）；ref 可以是 commit/tag/
    branch，runner 在开跑前会解析成 commit SHA 并记进 meta。
    """

    ref: str
    repo: str | None = None
    script: str | None = None
    timeout_seconds: float = DEFAULT_SNAPSHOT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Judge:
    """LLM 阅卷兜底：显式声明的评分卡 + 校准结果。

    只在任务写了 `[verifier.judge]` 时启用。确定性检查仍然先跑：确定性失败不会
    调用 judge；确定性通过（或没有确定性检查）才让 judge 做最终判定。
    `calibration` 是预先跑好的 κ 结果（仓库内相对路径）；`samples` 是人工标注
    样本，供 `codelotte eval judge` 重新校准。
    """

    dimensions: tuple[str, ...]
    rubric: str
    pass_threshold: float = 0.6
    kappa_threshold: float = 0.6
    calibration: str | None = None
    samples: str | None = None
    timeout_seconds: float = 60.0
    max_submission_chars: int = 20_000


@dataclass(frozen=True)
class Verifier:
    """验收器：确定性检查优先，可选的 LLM judge 兜底。"""

    files: tuple[FileExpectation, ...] = ()
    python: str | None = None
    command: tuple[str, ...] = ()
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    judge: Judge | None = None


@dataclass(frozen=True)
class Task:
    """一条可确定性验收的评测任务。"""

    id: str
    bucket: str
    instruction: str
    setup: dict[str, str]
    verifier: Verifier
    checkpoints: tuple[Checkpoint, ...] = ()
    snapshot: Snapshot | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS
    # 控制 agent 的参考解（[control.oracle.files]）：只给 oracle 自检用，真实 agent 看不到。
    # 它不进 task_fingerprint——改参考解不应该让历史模型跑数失去可比性。
    oracle_files: dict[str, str] = field(default_factory=dict)


def _require(raw: dict[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise TaskFileError(f"{where} 缺少字段 {key}")
    return raw[key]


def _nonempty_str(value: Any, field: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskFileError(f"{where} 的 {field} 要是非空字符串（给了 {value!r}）")
    return value


def _relative_path(value: Any, field: str, where: str) -> str:
    """任务里的文件路径必须留在临时工作区内（`..` 与绝对路径一律拒绝）。"""
    text = _nonempty_str(value, field, where)
    path = Path(text)
    # Windows 的 "C:foo" 既不是 is_absolute()，也会解析到工作区之外——必须看 drive。
    if path.drive or path.is_absolute() or any(part == ".." for part in path.parts):
        raise TaskFileError(f"{where} 的 {field} 必须是工作区内的相对路径（给了 {text!r}）")
    return text


def _positive_number(value: Any, field: str, where: str, default: float) -> float:
    number = default if value is None else value
    if not isinstance(number, (int, float)) or isinstance(number, bool) or number <= 0:
        raise TaskFileError(f"{where} 的 {field} 要是正数（给了 {number!r}）")
    return float(number)


def _snapshot(raw: Any, where: str) -> Snapshot:
    label = f"{where} 的 setup.snapshot"
    if not isinstance(raw, dict):
        raise TaskFileError(f"{label} 应是对象")
    ref = _nonempty_str(_require(raw, "ref", label), "ref", label)
    repo_raw = raw.get("repo")
    repo = None
    if repo_raw is not None:
        repo = _relative_path(repo_raw, "repo", label)
    script = raw.get("script")
    if script is not None and (not isinstance(script, str) or not script.strip()):
        raise TaskFileError(f"{label} 的 script 要是非空字符串")
    timeout = _positive_number(
        raw.get("timeout_seconds"),
        "timeout_seconds",
        label,
        DEFAULT_SNAPSHOT_TIMEOUT_SECONDS,
    )
    return Snapshot(ref=ref, repo=repo, script=script, timeout_seconds=timeout)


def _setup(raw: Any, where: str) -> tuple[dict[str, str], Snapshot | None]:
    if not isinstance(raw, dict):
        raise TaskFileError(f"{where} 的 setup 应是对象（含 files 或 snapshot）")
    files_raw = raw.get("files")
    files: dict[str, str] = {}
    if files_raw is not None:
        if not isinstance(files_raw, dict):
            raise TaskFileError(f"{where} 的 setup.files 应是对象")
        for path, content in files_raw.items():
            key = _relative_path(path, "setup.files 的路径", where)
            if not isinstance(content, str):
                raise TaskFileError(f"{where} 的 setup.files[{key!r}] 要是字符串")
            files[key] = content
    snapshot_raw = raw.get("snapshot")
    snapshot = _snapshot(snapshot_raw, where) if snapshot_raw is not None else None
    if not files and snapshot is None:
        raise TaskFileError(f"{where} 的 setup 至少要给 files 或 snapshot")
    return files, snapshot


def _repo_relative_path(
    value: Any, field: str, where: str, *, suffix: str
) -> str:
    """judge 的校准/样本路径是仓库内相对路径（不是工作区文件）。"""
    text = _nonempty_str(value, field, where)
    path = Path(text)
    if path.drive or path.is_absolute() or any(part == ".." for part in path.parts):
        raise TaskFileError(f"{where} 的 {field} 必须是相对路径（给了 {text!r}）")
    if path.suffix.lower() != suffix:
        raise TaskFileError(f"{where} 的 {field} 必须是 {suffix} 文件（给了 {text!r}）")
    return text


def _threshold(value: Any, field: str, where: str, default: float) -> float:
    number = default if value is None else value
    if (
        not isinstance(number, (int, float))
        or isinstance(number, bool)
        or not 0 <= float(number) <= 1
    ):
        raise TaskFileError(f"{where} 的 {field} 要在 0–1 之间（给了 {number!r}）")
    return float(number)


def _judge(raw: Any, where: str) -> Judge | None:
    if raw is None:
        return None
    label = f"{where} 的 verifier.judge"
    if not isinstance(raw, dict):
        raise TaskFileError(f"{label} 应是对象")
    dimensions_raw = _require(raw, "dimensions", label)
    if not isinstance(dimensions_raw, list) or not dimensions_raw:
        raise TaskFileError(f"{label} 的 dimensions 必须是非空数组")
    dimensions: list[str] = []
    for item in dimensions_raw:
        dimension = _nonempty_str(item, "dimensions 的维度", label)
        if dimension in dimensions:
            raise TaskFileError(f"{label} 的 dimensions 不能重复：{dimension!r}")
        dimensions.append(dimension)
    rubric = _nonempty_str(_require(raw, "rubric", label), "rubric", label)
    pass_threshold = _threshold(
        raw.get("pass_threshold"), "pass_threshold", label, 0.6
    )
    kappa_threshold = _threshold(
        raw.get("kappa_threshold"), "kappa_threshold", label, 0.6
    )
    calibration_raw = raw.get("calibration")
    calibration = (
        _repo_relative_path(calibration_raw, "calibration", label, suffix=".json")
        if calibration_raw is not None
        else None
    )
    samples_raw = raw.get("samples")
    samples = (
        _repo_relative_path(samples_raw, "samples", label, suffix=".jsonl")
        if samples_raw is not None
        else None
    )
    timeout = _positive_number(
        raw.get("timeout_seconds"), "timeout_seconds", label, 60.0
    )
    max_chars = raw.get("max_submission_chars", 20_000)
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise TaskFileError(
            f"{label} 的 max_submission_chars 要是正整数（给了 {max_chars!r}）"
        )
    return Judge(
        dimensions=tuple(dimensions),
        rubric=rubric,
        pass_threshold=pass_threshold,
        kappa_threshold=kappa_threshold,
        calibration=calibration,
        samples=samples,
        timeout_seconds=timeout,
        max_submission_chars=max_chars,
    )


def _file_expectation(raw: Any, where: str) -> FileExpectation:
    if not isinstance(raw, dict):
        raise TaskFileError(f"{where} 的 verifier.files 条目应是对象")
    path = _relative_path(_require(raw, "path", where), "path", where)
    modes = [name for name in ("equals", "contains", "unchanged") if name in raw]
    if len(modes) != 1:
        raise TaskFileError(
            f"{where} 对 {path} 的验收要且只要 equals / contains / unchanged 之一"
            f"（给了 {modes or '空'}）"
        )
    mode = modes[0]
    if mode == "unchanged":
        if raw[mode] is not True:
            raise TaskFileError(f"{where} 的 unchanged 只能是 true")
        return FileExpectation(path=path, unchanged=True)
    value = raw[mode]
    if not isinstance(value, str):
        raise TaskFileError(f"{where} 的 {mode} 要是字符串")
    if mode == "equals":
        return FileExpectation(path=path, equals=value)
    return FileExpectation(path=path, contains=value)


def _verifier(raw: Any, where: str) -> Verifier:
    if not isinstance(raw, dict):
        raise TaskFileError(f"{where} 缺少 [verifier] 表")
    entries = raw.get("files")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise TaskFileError(f"{where} 的 verifier.files 应是数组")
    python = raw.get("python")
    if python is not None and (not isinstance(python, str) or not python.strip()):
        raise TaskFileError(f"{where} 的 verifier.python 要是非空字符串")
    command_raw = raw.get("command")
    command: tuple[str, ...] = ()
    if command_raw is not None:
        if not isinstance(command_raw, list) or not command_raw:
            raise TaskFileError(
                f"{where} 的 verifier.command 要是非空字符串数组"
                "（如 [\"python\", \"check.py\"]）"
            )
        command = tuple(
            _nonempty_str(item, "verifier.command 的参数", where) for item in command_raw
        )
    command_timeout = _positive_number(
        raw.get("command_timeout"),
        "command_timeout",
        where,
        DEFAULT_COMMAND_TIMEOUT_SECONDS,
    )
    files = tuple(_file_expectation(item, where) for item in entries)
    judge = _judge(raw.get("judge"), where)
    if not files and python is None and not command and judge is None:
        raise TaskFileError(
            f"{where} 缺少 verifier：至少给 files 期望、python 检查、command 命令"
            " 或 [verifier.judge] 评分卡"
        )
    return Verifier(
        files=files,
        python=python,
        command=command,
        command_timeout=command_timeout,
        judge=judge,
    )


def _oracle_files(raw: Any, where: str) -> dict[str, str]:
    """控制 agent 的参考解；缺省为空（oracle 会尝试从文件验收期望推导）。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TaskFileError(f"{where} 的 control 应是对象")
    oracle = raw.get("oracle")
    if oracle is None:
        return {}
    if not isinstance(oracle, dict):
        raise TaskFileError(f"{where} 的 control.oracle 应是对象")
    files_raw = oracle.get("files")
    if files_raw is None:
        return {}
    if not isinstance(files_raw, dict):
        raise TaskFileError(f"{where} 的 control.oracle.files 应是对象")
    files: dict[str, str] = {}
    for path, content in files_raw.items():
        key = _relative_path(path, "control.oracle.files 的路径", where)
        if not isinstance(content, str):
            raise TaskFileError(
                f"{where} 的 control.oracle.files[{key!r}] 要是字符串"
            )
        files[key] = content
    return files


def _checkpoints(raw: Any, where: str) -> tuple[Checkpoint, ...]:
    """压缩回归的问题集；通用测评 的任务可以完全不写。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TaskFileError(f"{where} 的 checkpoints 应是数组")
    result: list[Checkpoint] = []
    for index, item in enumerate(raw, start=1):
        label = f"{where} 的第 {index} 个 checkpoint"
        if not isinstance(item, dict):
            raise TaskFileError(f"{label} 应是对象")
        question = _nonempty_str(_require(item, "question", label), "question", label)
        facts_raw = _require(item, "facts", label)
        if not isinstance(facts_raw, list) or not facts_raw:
            raise TaskFileError(f"{label} 的 facts 不能为空")
        facts: list[tuple[str, ...]] = []
        for group in facts_raw:
            if not isinstance(group, list) or not group:
                raise TaskFileError(f"{label} 的每个事实组必须是非空数组")
            alternatives = tuple(
                _nonempty_str(value, "facts 的替代表述", label) for value in group
            )
            facts.append(alternatives)
        result.append(Checkpoint(question=question, facts=tuple(facts)))
    return tuple(result)


def load_task(path: Path) -> Task:
    """读一个任务文件；任何结构问题都以 TaskFileError 报出（不猜、不跳过）。"""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TaskFileError(f"任务文件读不动：{path}（{exc}）") from exc
    except tomllib.TOMLDecodeError as exc:
        raise TaskFileError(f"任务文件不是合法 TOML：{path}（{exc}）") from exc
    where = str(path)
    task_id = _nonempty_str(_require(raw, "id", where), "id", where)
    bucket = _nonempty_str(_require(raw, "bucket", where), "bucket", where)
    if bucket not in {"A", "B", "C"}:
        raise TaskFileError(f"{where} 的 bucket 只能是 A/B/C（给了 {bucket!r}）")
    instruction = _nonempty_str(
        _require(raw, "instruction", where), "instruction", where
    )
    setup, snapshot = _setup(_require(raw, "setup", where), where)
    verifier = _verifier(_require(raw, "verifier", where), where)
    checkpoints = _checkpoints(raw.get("checkpoints"), where)
    oracle_files = _oracle_files(raw.get("control"), where)
    timeout = _positive_number(
        raw.get("timeout_seconds"),
        "timeout_seconds",
        where,
        DEFAULT_TIMEOUT_SECONDS,
    )
    max_calls = raw.get("max_model_calls", DEFAULT_MAX_MODEL_CALLS)
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls <= 0:
        raise TaskFileError(f"{where} 的 max_model_calls 要是正整数（给了 {max_calls!r}）")
    return Task(
        id=task_id,
        bucket=bucket,
        instruction=instruction,
        setup=setup,
        verifier=verifier,
        checkpoints=checkpoints,
        snapshot=snapshot,
        timeout_seconds=timeout,
        max_model_calls=max_calls,
        oracle_files=oracle_files,
    )


def load_tasks(directory: Path) -> list[Task]:
    """读目录下全部 *.toml（按文件名排序）；空目录与重复 id 都是错误。"""
    if not directory.is_dir():
        raise TaskFileError(f"任务目录不存在：{directory}")
    paths = sorted(directory.glob("*.toml"))
    if not paths:
        raise TaskFileError(f"任务目录里没有 *.toml 任务：{directory}")
    tasks = [load_task(path) for path in paths]
    seen: dict[str, Path] = {}
    for path, task in zip(paths, tasks):
        if task.id in seen:
            raise TaskFileError(
                f"重复的任务 id {task.id!r}：{seen[task.id]} 与 {path}"
            )
        seen[task.id] = path
    return tasks
