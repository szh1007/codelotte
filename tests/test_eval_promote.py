"""失败轨迹 → 回归任务（票据 18）：生成的文件必须能被 eval run 直接读取。"""

from __future__ import annotations

from pathlib import Path

import pytest

from codelotte.evals.attribution import Attribution
from codelotte.evals.promote import (
    RegressionTaskError,
    build_regression_task,
    next_regression_id,
    write_regression_task,
)
from codelotte.evals.tasks import Task, load_task

TASK = '''# 一条测试任务
id = "002-fix-off-by-one"
bucket = "A"
timeout_seconds = 300
max_model_calls = 30

instruction = "修复 bug"

[setup.files]
"calc.py" = "def f():\\n    return 1\\n"

[verifier]
python = "assert True"

[[verifier.files]]
path = "notes.txt"
contains = "range(n)"

[control.oracle.files]
"calc.py" = "def f():\\n    return 0\\n"
'''


def _source(tmp_path: Path) -> tuple[Path, Task]:
    path = tmp_path / "002.toml"
    path.write_text(TASK, encoding="utf-8", newline="\n")
    return path, load_task(path)


def test_build_regression_task_keeps_setup_and_verifier(tmp_path: Path) -> None:
    path, source = _source(tmp_path)
    text = build_regression_task(
        path,
        source_id=source.id,
        new_id="regression-002-fix-off-by-one",
        run_id="run-1",
        repetition=2,
        attribution=Attribution(
            failure_class="loop",
            confidence="high",
            evidence="工具层拦截：重复调用 read",
        ),
        detail="内容不符",
        generated_at="2026-10-18T00:00:00Z",
    )
    out = tmp_path / "regression.toml"
    out.write_text(text, encoding="utf-8", newline="\n")

    promoted = load_task(out)
    assert promoted.id == "regression-002-fix-off-by-one"
    assert promoted.bucket == source.bucket
    assert promoted.instruction == source.instruction
    assert promoted.setup == source.setup
    assert promoted.verifier == source.verifier
    assert promoted.oracle_files == source.oracle_files
    assert "# 来源：run run-1 / 002-fix-off-by-one r2" in text
    assert "# 归因：循环（高）—— 工具层拦截：重复调用 read" in text


def test_next_regression_id_avoids_collisions() -> None:
    assert next_regression_id("002-fix", set()) == "regression-002-fix"
    assert (
        next_regression_id("002-fix", {"regression-002-fix"})
        == "regression-002-fix-2"
    )
    assert (
        next_regression_id(
            "002-fix", {"regression-002-fix", "regression-002-fix-2"}
        )
        == "regression-002-fix-3"
    )


def test_write_regression_task_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "exists.toml"
    out.write_text("id = \"old\"\n", encoding="utf-8")
    with pytest.raises(RegressionTaskError, match="已存在"):
        write_regression_task(out, "id = \"new\"\n")


def test_build_regression_task_rejects_source_without_id_line(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[verifier]\npython = \"pass\"\n", encoding="utf-8")
    # 不经过 load_task（它本身就会拒绝），直接测生成器的防御
    with pytest.raises(RegressionTaskError, match="id"):
        build_regression_task(
            path,
            source_id="broken",
            new_id="regression-x",
            run_id="run-1",
            repetition=1,
            attribution=None,
            detail="",
            generated_at="now",
        )
