"""任务工作区：初始文件、git 快照初始化脚本与确定性验收。

从票据 13 的 regression.py 抽出——压缩回归与通用测评 共用同一套
"准备环境 → 跑 agent → 验收"的前后两端。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from codelotte.evals.tasks import FileExpectation, Task, TaskFileError


def _run_process(
    args: str | list[str],
    *,
    cwd: Path,
    timeout: float,
    shell: bool = False,
) -> subprocess.CompletedProcess[str]:
    """跑初始化脚本/验收命令：统一 UTF-8 与超时，错误由调用方转成可读文本。"""
    return subprocess.run(
        args,
        cwd=cwd,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # 验收命令/脚本可能吐非 UTF-8；替换而不是让整轮 runner 崩掉
        timeout=timeout,
        shell=shell,
    )


def _tail(text: str, limit: int = 600) -> str:
    return text[-limit:] if len(text) > limit else text


def _extract_snapshot(repo: Path, ref: str, workspace: Path) -> None:
    """git archive 一个 commit 到工作区；不碰评测仓库的工作树。"""
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as handle:
        archive = Path(handle.name)
    try:
        result = _run_process(
            ["git", "archive", "--format=tar", "-o", str(archive), ref],
            cwd=repo,
            timeout=60,
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            raise TaskFileError(
                f"仓库快照抽取失败（{repo} @ {ref}）：{_tail(output)}"
            )
        with tarfile.open(archive) as tar:
            tar.extractall(workspace, filter="data")
    except TaskFileError:
        raise
    except (OSError, subprocess.TimeoutExpired, tarfile.TarError) as exc:
        raise TaskFileError(
            f"仓库快照抽取失败（{repo} @ {ref}）：{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        archive.unlink(missing_ok=True)


def _run_init_script(script: str, workspace: Path, timeout: float) -> None:
    """任务自带初始化脚本（可信输入；shell 语义按平台）。失败即任务失败。"""
    try:
        result = _run_process(script, cwd=workspace, timeout=timeout, shell=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TaskFileError(
            f"初始化脚本无法执行：{type(exc).__name__}: {exc}"
        ) from exc
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        raise TaskFileError(
            f"初始化脚本失败（退出码 {result.returncode}）：{_tail(output)}"
        )


def prepare_workspace(
    task: Task,
    workspace: Path,
    *,
    repo_root: Path | None = None,
    snapshot_ref: str | None = None,
) -> Path:
    """按任务定义准备初始工作区：仓库快照 → 初始化脚本 → setup.files 覆盖。

    强制 LF：实验文件跨平台逐字节一致。`snapshot_ref` 由 orchestrator 在开跑前
    解析成 commit SHA，保证同一轮所有重复使用同一个快照。
    """
    workspace.mkdir(parents=True, exist_ok=True)
    if task.snapshot is not None:
        if repo_root is None:
            raise TaskFileError(
                f"任务 {task.id} 需要仓库快照，但没有传入评测仓库根目录"
            )
        repo = repo_root / task.snapshot.repo if task.snapshot.repo else repo_root
        _extract_snapshot(repo.resolve(), snapshot_ref or task.snapshot.ref, workspace)
        if task.snapshot.script is not None:
            _run_init_script(
                task.snapshot.script, workspace, task.snapshot.timeout_seconds
            )
    for relative, content in task.setup.items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    return workspace


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def capture_unchanged_baseline(task: Task, workspace: Path) -> dict[str, str | None]:
    """在 agent 动手前记录 `unchanged` 文件的基线（快照/初始化脚本产生的文件也适用）。

    返回 path → 规范化文本；文件不存在时记 None。非 UTF-8 文件无法建立文本基线，
    直接报任务配置错，而不是让验收静默误判。
    """
    baseline: dict[str, str | None] = {}
    for expectation in task.verifier.files:
        if not expectation.unchanged:
            continue
        target = workspace / expectation.path
        if not target.is_file():
            baseline[expectation.path] = None
            continue
        try:
            baseline[expectation.path] = _normalize_text(
                target.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError) as exc:
            raise TaskFileError(
                f"unchanged 基线无法读取 {expectation.path}：{type(exc).__name__}: {exc}"
            ) from exc
    return baseline


def _verify_files(
    expectations: tuple[FileExpectation, ...],
    task: Task,
    workspace: Path,
    baseline: dict[str, str | None] | None = None,
) -> list[str]:
    problems: list[str] = []
    for expectation in expectations:
        target = workspace / expectation.path
        if not target.is_file():
            if (
                expectation.unchanged
                and baseline is not None
                and baseline.get(expectation.path, "") is None
            ):
                continue  # 初始就不存在，现在仍不存在：符合 unchanged
            problems.append(f"缺少文件 {expectation.path}")
            continue
        try:
            actual = _normalize_text(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(
                f"{expectation.path} 无法按 UTF-8 读取（{type(exc).__name__}）"
            )
            continue
        if expectation.equals is not None:
            expected = _normalize_text(expectation.equals)
            if actual != expected:
                problems.append(
                    f"{expectation.path} 内容不符：期望 {expected!r}，实际 {actual!r}"
                )
        elif expectation.contains is not None:
            if _normalize_text(expectation.contains) not in actual:
                problems.append(
                    f"{expectation.path} 不包含 {_normalize_text(expectation.contains)!r}"
                )
        elif expectation.unchanged:
            if baseline is not None and expectation.path in baseline:
                expected = baseline[expectation.path]
                if expected is None:
                    problems.append(
                        f"{expectation.path} 被创建了（任务要求保持不变）"
                    )
                    continue
            else:
                expected = _normalize_text(task.setup.get(expectation.path, ""))
            if actual != expected:
                problems.append(f"{expectation.path} 被修改了（任务要求保持不变）")
    return problems


def _verify_python(code: str, workspace: Path, timeout: float = 60.0) -> str | None:
    try:
        result = _run_process([sys.executable, "-c", code], cwd=workspace, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"python 验收无法执行：{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        return f"python 验收失败（退出码 {result.returncode}）：{_tail(output)}"
    return None


def _verify_command(command: tuple[str, ...], workspace: Path, timeout: float) -> str | None:
    try:
        result = _run_process(list(command), cwd=workspace, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"命令验收无法执行：{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        return f"命令验收失败（退出码 {result.returncode}）：{_tail(output)}"
    return None


def verify(
    task: Task,
    workspace: Path,
    *,
    unchanged_baseline: dict[str, str | None] | None = None,
) -> tuple[bool, str]:
    """确定性验收：命令 → Python → 文件期望，全部通过才算完成。

    `unchanged_baseline` 由 execution 在 agent 动手前捕获；不传则退回 task.setup
    （兼容只依赖初始文件的旧任务/单元测试）。
    """
    problems: list[str] = []
    if task.verifier.command:
        command_problem = _verify_command(
            task.verifier.command, workspace, task.verifier.command_timeout
        )
        if command_problem is not None:
            problems.append(command_problem)
    if task.verifier.python is not None:
        python_problem = _verify_python(task.verifier.python, workspace)
        if python_problem is not None:
            problems.append(python_problem)
    problems.extend(
        _verify_files(
            task.verifier.files,
            task,
            workspace,
            baseline=unchanged_baseline,
        )
    )
    if problems:
        return False, "；".join(problems)
    return True, "验收通过"
