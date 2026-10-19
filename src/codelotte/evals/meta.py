"""实验元数据与复现凭证（票据 13/15）。

单独成模块是为了打断 report ↔ suite 的循环依赖：报表只读元数据，
编排器同时依赖元数据与报表。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from codelotte.evals.tasks import Task, TaskFileError


@dataclass(frozen=True)
class TaskMeta:
    """任务指纹：按语义字段哈希（缩进/注释变化不改指纹）。"""

    id: str
    bucket: str
    sha256: str
    snapshot_ref: str | None = None  # 开跑前解析出的 commit SHA（任务自带仓库快照时）


@dataclass(frozen=True)
class RunMeta:
    """一轮压缩实验的复现凭证。"""

    run_id: str
    started_at: str
    finished_at: str
    git_ref: str
    git_dirty: bool | None  # None = git 命令失败，状态未知（不冒充干净）
    git_diff_sha: str | None
    python: str
    codelotte_version: str
    uv_lock_sha: str | None
    model: str
    reasoning_effort: str
    context_window: int
    soft: float
    hard: float
    k_values: tuple[int, ...]
    repetitions: int
    seed: int
    tasks: tuple[TaskMeta, ...]
    command: str
    currency: str = "CNY"
    # E1：本轮压测的策略/模板组合（老报表缺省为空，按默认 minimal/seven 理解）
    combos: tuple[tuple[str, str], ...] = ()


def task_fingerprint(task: Task) -> str:
    """任务语义指纹：指令/初始文件/验收器/问题集/快照逐字段序列化后取 SHA-256。"""
    payload = {
        "id": task.id,
        "bucket": task.bucket,
        "instruction": task.instruction,
        "setup": task.setup,
        "snapshot": asdict(task.snapshot) if task.snapshot is not None else None,
        "verifier": asdict(task.verifier),
        "checkpoints": [asdict(checkpoint) for checkpoint in task.checkpoints],
        "timeout_seconds": task.timeout_seconds,
        "max_model_calls": task.max_model_calls,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class RunContext:
    """一轮跑数的目录与开跑前锁定的复现凭证（两类 runner 共用）。"""

    repo_root: Path
    run_dir: Path
    workspace_root: Path
    session_root: Path
    git_ref: str
    git_dirty: bool | None
    git_diff_sha: str | None
    uv_lock_sha: str | None
    snapshot_refs: dict[str, str]
    task_metas: tuple[TaskMeta, ...]


@dataclass(frozen=True)
class EvalRunMeta:
    """一轮通用测评的复现凭证（票据 15）：不含压缩实验的 soft/hard/k。"""

    run_id: str
    started_at: str
    finished_at: str
    git_ref: str
    git_dirty: bool | None
    git_diff_sha: str | None
    python: str
    codelotte_version: str
    uv_lock_sha: str | None
    model: str
    reasoning_effort: str
    context_window: int
    repetitions: int
    seed: int
    tasks: tuple[TaskMeta, ...]
    command: str
    currency: str = "CNY"
    # 票据 16：这一轮跑的是哪个 harness（codelotte / raw / mini-swe-agent / 控制 agent）
    harness: str = "codelotte"
    harness_kind: str = "agent"
    harness_version: str | None = None
    isolation: str = "unknown"


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def current_git_ref(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD") or "unknown"


def resolve_git_ref(repo: Path, ref: str) -> str | None:
    """把 branch/tag/HEAD 解析成 commit SHA；git 不可用或 ref 无效返回 None。"""
    return _git(repo, "rev-parse", f"{ref}^{{commit}}")


def resolve_task_snapshots(tasks: Sequence[Task], repo_root: Path) -> dict[str, str]:
    """开跑前把所有任务的仓库快照 ref 解析成 SHA（同一轮所有重复共用一个 commit）。"""
    refs: dict[str, str] = {}
    for task in tasks:
        if task.snapshot is None:
            continue
        repo = repo_root / task.snapshot.repo if task.snapshot.repo else repo_root
        resolved = resolve_git_ref(repo.resolve(), task.snapshot.ref)
        if resolved is None:
            raise TaskFileError(
                f"任务 {task.id} 的仓库快照 ref 解析失败：{repo} @ {task.snapshot.ref}"
            )
        refs[task.id] = resolved
    return refs


def find_repo_root(start: Path) -> Path:
    """从任意子目录找到仓库根（uv.lock / evals 默认路径以它为准）；非仓库则用 start。"""
    found = _git(start, "rev-parse", "--show-toplevel")
    return Path(found) if found else start


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _untracked_paths(repo: Path) -> list[bytes] | None:
    """未跟踪文件（`-z` 避免空格/换行文件名歧义）；git 不可用返回 None。"""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return [item for item in result.stdout.split(b"\0") if item]


def _content_sha(path: Path) -> str:
    """未跟踪文件的内容哈希：只记文件名等于没锁住产生数字的代码。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return f"unreadable:{type(exc).__name__}:{exc}"


def worktree_fingerprint(
    repo: Path, exclude: Path | None
) -> tuple[bool | None, str | None]:
    """dirty 标记 + 工作树指纹：git diff（含已暂存）与未跟踪文件**内容**一起哈希。

    本轮 run 目录本身要排除：它每跑一次都变，算进去会让指纹失去可比性。
    git 不可用（非仓库、命令失败）返回 (None, None)——不把"不知道"冒充成"干净"。
    """
    untracked_paths = _untracked_paths(repo)
    if untracked_paths is None:
        return None, None
    diff = _git(repo, "diff", "HEAD")
    diff_text = diff if diff is not None else "<no-head-or-diff-error>"
    prefix: str | None = None
    if exclude is not None:
        try:
            prefix = exclude.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            prefix = None
    entries: list[str] = []
    for raw_path in untracked_paths:
        relative = os.fsdecode(raw_path)
        if prefix and (relative == prefix or relative.startswith(prefix + "/")):
            continue
        entries.append(f"{relative}\0{_content_sha(repo / relative)}")
    if not diff and not entries:
        return False, None
    raw = f"{diff_text}\n--untracked--\n" + "\n".join(entries)
    return True, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_run_id(git_ref: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = git_ref[:7] if git_ref and git_ref != "unknown" else "nogit"
    return f"{stamp}-{short}"


def create_run_dir(base: Path, run_id: str) -> Path:
    """新建 run 目录；同名已存在时加序号（绝不覆盖历史跑数）。"""
    base.mkdir(parents=True, exist_ok=True)
    candidate = base / run_id
    suffix = 2
    while candidate.exists():
        candidate = base / f"{run_id}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def uv_lock_sha(repo: Path) -> str | None:
    return _sha256_file(repo / "uv.lock")


def prepare_run_dir(
    tasks: Sequence[Task],
    *,
    run_dir: Path,
    repo_root: Path,
    exclude: Path | None = None,
) -> RunContext:
    """在已确定的 run 目录里锁定复现凭证并建 workspaces/sessions。

    `exclude` 是工作树指纹要排除的目录：对照跑数的各组落在同一个父目录下，
    必须排除父目录（而不是组子目录），否则前一组产物会把后一组的指纹弄脏。
    """
    repo_root = repo_root.resolve()
    run_dir = run_dir.resolve()
    snapshot_refs = resolve_task_snapshots(tasks, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = run_dir / "workspaces"
    session_root = run_dir / "sessions"
    workspace_root.mkdir(exist_ok=True)
    session_root.mkdir(exist_ok=True)
    # 跑数期间工作区/会话目录会增长，凭证必须在开跑前取
    git_ref = current_git_ref(repo_root)
    dirty, diff_sha = worktree_fingerprint(repo_root, exclude=exclude or run_dir)
    lock_sha = uv_lock_sha(repo_root)
    task_metas = tuple(
        TaskMeta(
            id=task.id,
            bucket=task.bucket,
            sha256=task_fingerprint(task),
            snapshot_ref=snapshot_refs.get(task.id),
        )
        for task in tasks
    )
    return RunContext(
        repo_root=repo_root,
        run_dir=run_dir,
        workspace_root=workspace_root,
        session_root=session_root,
        git_ref=git_ref,
        git_dirty=dirty,
        git_diff_sha=diff_sha,
        uv_lock_sha=lock_sha,
        snapshot_refs=snapshot_refs,
        task_metas=task_metas,
    )


def prepare_run(
    tasks: Sequence[Task], *, runs_root: Path, repo_root: Path, run_id: str
) -> RunContext:
    """建 run 目录并在开跑前锁定 git ref/工作树/依赖/任务指纹/快照 SHA。

    快照 ref 先解析：ref 无效属于配置错，不能留下一个空 run 目录。
    """
    runs_root = runs_root.resolve()
    run_dir = create_run_dir(runs_root, run_id)
    return prepare_run_dir(tasks, run_dir=run_dir, repo_root=repo_root)
