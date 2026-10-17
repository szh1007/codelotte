"""压缩回归套件的任务定义（票据 13）：TOML 加载与校验。

任务文件是实验的输入，坏输入必须当场报错——静默跳过会让"3 条任务"变成 2 条
却仍然出报表，数字就不可信了。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codelotte.evals.tasks import TaskFileError, load_task, load_tasks

TASKS_DIR = Path(__file__).resolve().parents[1] / "evals" / "tasks"


def test_shipped_suite_has_three_complete_tasks() -> None:
    tasks = load_tasks(TASKS_DIR)

    assert len(tasks) == 3
    assert len({task.id for task in tasks}) == 3
    for task in tasks:
        assert task.bucket in {"A", "B", "C"}
        assert task.instruction.strip()
        assert task.setup  # 每条任务自带确定性初始文件
        assert task.verifier.files or task.verifier.python
        assert len(task.checkpoints) >= 3
        for checkpoint in task.checkpoints:
            assert checkpoint.question.strip()
            assert checkpoint.facts
            assert all(fact for fact in checkpoint.facts)


def test_rejects_setup_paths_that_escape_the_workspace(tmp_path: Path) -> None:
    path = tmp_path / "escape.toml"
    path.write_text(
        """
id = "escape"
bucket = "B"
instruction = "x"
[setup]
files = { "../evil.txt" = "boom" }
[verifier]
python = "pass"
[[checkpoints]]
question = "目标？"
facts = [["x"]]
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="相对路径"):
        load_task(path)


@pytest.mark.skipif(not Path("C:evil.txt").drive, reason="Windows 盘符相对路径")
def test_rejects_windows_drive_relative_paths(tmp_path: Path) -> None:
    """`C:evil.txt` 不是绝对路径，却会解析到工作区之外——按路径越界拒绝。"""
    path = tmp_path / "drive.toml"
    path.write_text(
        """
id = "drive"
bucket = "B"
instruction = "x"
[setup]
files = { "C:evil.txt" = "boom" }
[verifier]
python = "pass"
[[checkpoints]]
question = "目标？"
facts = [["x"]]
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="相对路径"):
        load_task(path)


def test_rejects_a_task_without_a_verifier(tmp_path: Path) -> None:
    path = tmp_path / "no-verifier.toml"
    path.write_text(
        """
id = "no-verifier"
bucket = "B"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[[checkpoints]]
question = "目标？"
facts = [["x"]]
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="verifier"):
        load_task(path)


def test_rejects_duplicate_task_ids(tmp_path: Path) -> None:
    body = """
id = "same"
bucket = "A"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
python = "pass"
[[checkpoints]]
question = "目标？"
facts = [["x"]]
"""
    (tmp_path / "a.toml").write_text(body, encoding="utf-8")
    (tmp_path / "b.toml").write_text(body, encoding="utf-8")

    with pytest.raises(TaskFileError, match="重复"):
        load_tasks(tmp_path)


def test_rejects_a_file_expectation_with_two_modes(tmp_path: Path) -> None:
    path = tmp_path / "two-modes.toml"
    path.write_text(
        """
id = "two-modes"
bucket = "A"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
[[verifier.files]]
path = "a.txt"
equals = "a"
contains = "a"
[[checkpoints]]
question = "目标？"
facts = [["x"]]
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="equals"):
        load_task(path)
