"""复现元数据（票据 13）：工作树指纹必须锁住未跟踪文件的**内容**。

只把文件名拼进哈希等于没锁：基线跑在提交前，整个套件源码都是未跟踪文件。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codelotte.evals.meta import worktree_fingerprint

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="需要 git 可执行文件"
)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_untracked_file_content_changes_the_fingerprint(tmp_path: Path) -> None:
    _git_init(tmp_path)
    source = tmp_path / "a.txt"
    source.write_text("one", encoding="utf-8")
    dirty_one, sha_one = worktree_fingerprint(tmp_path, exclude=None)
    assert dirty_one is True and sha_one is not None

    source.write_text("two", encoding="utf-8")
    dirty_two, sha_two = worktree_fingerprint(tmp_path, exclude=None)

    assert dirty_two is True
    assert sha_two != sha_one  # 文件名没变、内容变了：指纹必须变


def test_run_directory_is_excluded_from_the_fingerprint(tmp_path: Path) -> None:
    _git_init(tmp_path)
    run_dir = tmp_path / "evals" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    artifact = run_dir / "session.jsonl"
    artifact.write_text("v1", encoding="utf-8")
    _dirty, sha_one = worktree_fingerprint(tmp_path, exclude=run_dir)

    artifact.write_text("v2", encoding="utf-8")
    _dirty, sha_two = worktree_fingerprint(tmp_path, exclude=run_dir)

    assert sha_one == sha_two  # 跑数产物不参与代码指纹


def test_outside_a_git_work_tree_is_unknown_not_clean(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    dirty, sha = worktree_fingerprint(plain, exclude=None)

    assert dirty is None and sha is None
