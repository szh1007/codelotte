"""专用测评 - 压缩回归 v0 的任务定义（票据 13）：TOML 加载与校验。

任务文件是实验的输入，坏输入必须当场报错——静默跳过会让"3 条任务"变成 2 条
却仍然出报表，数字就不可信了。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codelotte.evals.judge import load_calibration, load_samples
from codelotte.evals.tasks import TaskFileError, load_task, load_tasks

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "evals" / "tasks"
JUDGE_TASKS_DIR = REPO_ROOT / "evals" / "judge-tasks"


def test_shipped_suite_covers_the_required_buckets() -> None:
    """票据 15：A 桶 ≥2、B 桶 ≥3；压缩回归需要的 checkpoint 仍然齐备。"""
    tasks = load_tasks(TASKS_DIR)

    assert len(tasks) >= 9
    assert len({task.id for task in tasks}) == len(tasks)
    assert {
        "006-multi-bug-pipeline",
        "007-refactor-tokenizer",
        "008-settlement-policy",
        "009-buffer-edge-cases",
    } <= {task.id for task in tasks}
    buckets = {task.bucket for task in tasks}
    assert {"A", "B"} <= buckets
    assert sum(1 for task in tasks if task.bucket == "A") >= 2
    assert sum(1 for task in tasks if task.bucket == "B") >= 3
    for task in tasks:
        assert task.instruction.strip()
        assert task.setup or task.snapshot
        assert task.verifier.files or task.verifier.python or task.verifier.command
        assert len(task.checkpoints) >= 3
        for checkpoint in task.checkpoints:
            assert checkpoint.question.strip()
            assert checkpoint.facts
            assert all(fact for fact in checkpoint.facts)
        # 票据 16：每条任务都有控制 agent 的参考解，oracle 才能做到 100%
        assert task.oracle_files
        # 每条任务至少有一个只读保护文件，cheating 才有可检测的篡改目标
        assert any(expectation.unchanged for expectation in task.verifier.files)


def test_checkpoints_are_optional_for_the_general_runner(tmp_path: Path) -> None:
    path = tmp_path / "general.toml"
    path.write_text(
        """
id = "general"
bucket = "A"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
python = "pass"
""",
        encoding="utf-8",
    )

    task = load_task(path)

    assert task.checkpoints == ()
    assert task.setup == {"a.txt": "a"}


def test_parses_a_repo_snapshot_and_command_verifier(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.toml"
    path.write_text(
        """
id = "snapshot"
bucket = "B"
instruction = "x"
[setup.snapshot]
ref = "HEAD"
repo = "."
script = "echo init > init.txt"
timeout_seconds = 30
[verifier]
command = ["python", "check.py"]
command_timeout = 5
""",
        encoding="utf-8",
    )

    task = load_task(path)

    assert task.snapshot is not None
    assert task.snapshot.ref == "HEAD"
    assert task.snapshot.repo == "."
    assert task.snapshot.script == "echo init > init.txt"
    assert task.snapshot.timeout_seconds == 30
    assert task.verifier.command == ("python", "check.py")
    assert task.verifier.command_timeout == 5
    assert task.setup == {}


def test_parses_a_judge_only_verifier(tmp_path: Path) -> None:
    path = tmp_path / "judge.toml"
    path.write_text(
        """
id = "judge"
bucket = "A"
instruction = "写 review.md"
[setup.files]
"bug.py" = "x"
[verifier.judge]
dimensions = ["correctness", "clarity"]
rubric = "correctness: 指出 bug；clarity: 结构清晰"
pass_threshold = 0.7
kappa_threshold = 0.6
calibration = "evals/judges/judge/calibration.json"
samples = "evals/judges/judge/samples.jsonl"
""",
        encoding="utf-8",
    )

    task = load_task(path)

    assert task.verifier.files == ()
    assert task.verifier.judge is not None
    assert task.verifier.judge.dimensions == ("correctness", "clarity")
    assert task.verifier.judge.pass_threshold == 0.7
    assert task.verifier.judge.kappa_threshold == 0.6
    assert task.verifier.judge.calibration == "evals/judges/judge/calibration.json"
    assert task.verifier.judge.samples == "evals/judges/judge/samples.jsonl"


def test_rejects_a_judge_without_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "judge.toml"
    path.write_text(
        """
id = "judge"
bucket = "A"
instruction = "x"
[setup.files]
"a.txt" = "a"
[verifier.judge]
rubric = "x"
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="dimensions"):
        load_task(path)


def test_rejects_a_judge_calibration_path_that_escapes_the_repo(tmp_path: Path) -> None:
    path = tmp_path / "judge.toml"
    path.write_text(
        """
id = "judge"
bucket = "A"
instruction = "x"
[setup.files]
"a.txt" = "a"
[verifier.judge]
dimensions = ["correctness"]
rubric = "x"
calibration = "../escape.json"
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="相对路径"):
        load_task(path)


def test_parses_control_oracle_files(tmp_path: Path) -> None:
    path = tmp_path / "oracle.toml"
    path.write_text(
        """
id = "oracle"
bucket = "A"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
python = "pass"
[control.oracle.files]
"a.txt" = "fixed"
"out.txt" = "done"
""",
        encoding="utf-8",
    )

    task = load_task(path)

    assert task.oracle_files == {"a.txt": "fixed", "out.txt": "done"}


def test_rejects_oracle_paths_that_escape_the_workspace(tmp_path: Path) -> None:
    path = tmp_path / "oracle-escape.toml"
    path.write_text(
        """
id = "oracle-escape"
bucket = "A"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
python = "pass"
[control.oracle.files]
"../evil.txt" = "boom"
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="相对路径"):
        load_task(path)


def test_rejects_snapshot_repo_paths_that_escape_the_repo(tmp_path: Path) -> None:
    path = tmp_path / "snapshot-escape.toml"
    path.write_text(
        """
id = "snapshot-escape"
bucket = "B"
instruction = "x"
[setup.snapshot]
ref = "HEAD"
repo = "../other"
[verifier]
python = "pass"
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="相对路径"):
        load_task(path)


def test_rejects_a_command_verifier_that_is_not_a_string_array(tmp_path: Path) -> None:
    path = tmp_path / "bad-command.toml"
    path.write_text(
        """
id = "bad-command"
bucket = "B"
instruction = "x"
[setup]
files = { "a.txt" = "a" }
[verifier]
command = "python check.py"
""",
        encoding="utf-8",
    )

    with pytest.raises(TaskFileError, match="command"):
        load_task(path)


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


def test_shipped_judge_tasks_have_samples_and_calibration() -> None:
    """judge 任务必须有可复现的样本与校准文件（票据 19 扩充后仍成立）。"""
    tasks = load_tasks(JUDGE_TASKS_DIR)

    assert tasks
    for task in tasks:
        judge = task.verifier.judge
        assert judge is not None
        assert judge.samples is not None and judge.calibration is not None
        samples_path = REPO_ROOT / judge.samples
        calibration_path = REPO_ROOT / judge.calibration
        assert samples_path.is_file(), samples_path
        assert calibration_path.is_file(), calibration_path
        samples = load_samples(samples_path)
        calibration = load_calibration(calibration_path)
        assert len(samples) >= 20, f"{task.id} 只有 {len(samples)} 条样本"
        assert calibration.samples == len(samples)
        assert calibration.task_id == task.id
