"""任务工作区（票据 15）：仓库快照、初始化脚本与命令验收器。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from codelotte.evals.meta import resolve_git_ref
from codelotte.evals.tasks import FileExpectation, Snapshot, Task, TaskFileError, Verifier
from codelotte.evals.workspace import (
    capture_unchanged_baseline,
    prepare_workspace,
    verify,
)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=eval-test",
            "-c",
            "user.email=eval-test@example.invalid",
            "commit",
            "-qm",
            "snapshot",
        ],
        cwd=repo,
        check=True,
    )
    return repo


def _task(*, snapshot: Snapshot | None = None, setup: dict[str, str] | None = None) -> Task:
    return Task(
        id="workspace-test",
        bucket="A",
        instruction="x",
        setup=setup or {},
        verifier=Verifier(python="pass"),
        snapshot=snapshot,
    )


def test_extracts_a_git_snapshot_and_overlays_setup_files(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    ref = resolve_git_ref(repo, "HEAD")
    assert ref is not None
    task = _task(
        snapshot=Snapshot(ref="HEAD", repo="."),
        setup={"overlay.txt": "overlay\n"},
    )

    workspace = prepare_workspace(
        task, tmp_path / "workspace", repo_root=repo, snapshot_ref=ref
    )

    assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "tracked\n"
    assert (workspace / "overlay.txt").read_text(encoding="utf-8") == "overlay\n"


def test_runs_the_snapshot_init_script_after_extraction(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    ref = resolve_git_ref(repo, "HEAD")
    assert ref is not None
    task = _task(
        snapshot=Snapshot(ref="HEAD", repo=".", script="echo init > init.txt")
    )

    workspace = prepare_workspace(
        task, tmp_path / "workspace", repo_root=repo, snapshot_ref=ref
    )

    assert (workspace / "init.txt").read_text(encoding="utf-8").strip() == "init"


def test_rejects_a_snapshot_without_a_repo_root(tmp_path: Path) -> None:
    task = _task(snapshot=Snapshot(ref="HEAD"))

    with pytest.raises(TaskFileError, match="仓库根目录"):
        prepare_workspace(task, tmp_path / "workspace")


def test_command_verifier_runs_in_the_workspace(tmp_path: Path) -> None:
    task = Task(
        id="command",
        bucket="A",
        instruction="x",
        setup={"check.py": "print('ok')\n"},
        verifier=Verifier(command=(sys.executable, "check.py")),
    )
    workspace = prepare_workspace(task, tmp_path / "workspace")

    passed, detail = verify(task, workspace)

    assert passed is True
    assert detail == "验收通过"


def test_reports_command_verifier_failure(tmp_path: Path) -> None:
    task = Task(
        id="command-fail",
        bucket="A",
        instruction="x",
        setup={},
        verifier=Verifier(command=(sys.executable, "-c", "raise SystemExit(3)")),
    )
    workspace = prepare_workspace(task, tmp_path / "workspace")

    passed, detail = verify(task, workspace)

    assert passed is False
    assert "退出码 3" in detail


def test_unchanged_uses_the_pre_agent_baseline_for_snapshot_files(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    (repo / "keep.txt").write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=eval-test",
            "-c",
            "user.email=eval-test@example.invalid",
            "commit",
            "-qm",
            "keep",
        ],
        cwd=repo,
        check=True,
    )
    ref = resolve_git_ref(repo, "HEAD")
    assert ref is not None
    task = Task(
        id="unchanged",
        bucket="A",
        instruction="x",
        setup={},
        snapshot=Snapshot(ref="HEAD", repo="."),
        verifier=Verifier(
            files=(FileExpectation(path="keep.txt", unchanged=True),)
        ),
    )
    workspace = prepare_workspace(
        task, tmp_path / "workspace", repo_root=repo, snapshot_ref=ref
    )
    baseline = capture_unchanged_baseline(task, workspace)

    (workspace / "keep.txt").write_text("changed\n", encoding="utf-8")
    passed, detail = verify(task, workspace, unchanged_baseline=baseline)
    assert passed is False
    assert "被修改了" in detail

    (workspace / "keep.txt").write_text("original\n", encoding="utf-8")
    passed, detail = verify(task, workspace, unchanged_baseline=baseline)
    assert passed is True


def test_non_utf8_file_is_a_verifier_failure_not_a_crash(tmp_path: Path) -> None:
    task = Task(
        id="binary",
        bucket="A",
        instruction="x",
        setup={},
        verifier=Verifier(
            files=(FileExpectation(path="bad.bin", contains="x"),)
        ),
    )
    workspace = prepare_workspace(task, tmp_path / "workspace")
    (workspace / "bad.bin").write_bytes(b"\xff\xfe\x00")

    passed, detail = verify(task, workspace)

    assert passed is False
    assert "UTF-8" in detail
