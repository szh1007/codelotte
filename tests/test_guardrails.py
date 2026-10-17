"""死循环三层防御的状态机（票据 11）：工具层重复/无进展、推理层熔断、规划层重注入与终止。

这里只测纯状态机（无会话、无网络）：阈值语义、连续计数、误报边界、提醒文本内容。
端到端行为（事件落盘、TUI/导出、-p 退出码）在 test_loop_guardrails / test_tui / test_export。
"""

from __future__ import annotations

from dataclasses import replace

from codelotte.guardrails import (
    GUARD_CIRCUIT,
    GUARD_REINJECT,
    GUARD_REPEAT,
    GUARD_STAGNATION,
    GUARD_TERMINATE,
    GuardrailLimits,
    GuardrailTracker,
    circuit_reminder,
    planning_reminder,
    planning_terminate_message,
)


def _tracker(**limits: int) -> GuardrailTracker:
    """默认值只从生产代码取（GuardrailLimits），测试只覆盖要变的字段。"""
    return GuardrailTracker(replace(GuardrailLimits(), **limits))


def test_repeated_identical_call_is_blocked_at_the_limit() -> None:
    """连续第 N 次同名同参调用被拦截；前 N-1 次正常执行。"""
    tracker = _tracker(repeat=3, stagnation=2, failure=99)
    args = {"command": "echo hi"}

    assert tracker.check_call("bash", args) is None
    tracker.record_result("bash", args, "out 1", ok=True)
    assert tracker.check_call("bash", args) is None  # 结果不同：无进展检测不触发
    tracker.record_result("bash", args, "out 2", ok=True)

    block = tracker.check_call("bash", args)
    assert block is not None
    assert block.guard == GUARD_REPEAT
    assert block.count == 3 and block.threshold == 3
    assert "重复" in block.message and "bash" in block.message


def test_a_different_call_resets_the_repeat_streak() -> None:
    tracker = _tracker(repeat=3, failure=99)
    args = {"command": "ls"}

    for _ in range(2):
        assert tracker.check_call("bash", args) is None
        tracker.record_result("bash", args, "same", ok=True)
    assert tracker.check_call("read", {"path": "x"}) is None  # 换了动作：连续中断
    tracker.record_result("read", {"path": "x"}, "file", ok=True)
    assert tracker.check_call("bash", args) is None  # 重新从 1 计数


def test_identical_results_block_earlier_as_stagnation() -> None:
    """结果连续不变是更强的信号：stagnation 阈值可以先于 repeat 阈值触发。"""
    tracker = _tracker(repeat=5, stagnation=2, failure=99)
    args = {"path": "a.txt"}

    assert tracker.check_call("read", args) is None
    tracker.record_result("read", args, "same\n", ok=True)
    assert tracker.check_call("read", args) is None
    tracker.record_result("read", args, "same\n", ok=True)

    block = tracker.check_call("read", args)
    assert block is not None
    assert block.guard == GUARD_STAGNATION
    assert block.count == 2 and block.threshold == 2
    assert "没有进展" in block.message


def test_changing_results_do_not_count_as_stagnation() -> None:
    """结果每次都在变 → 无进展检测不触发；只有 repeat 阈值（第 4 次）才拦。"""
    tracker = _tracker(repeat=4, stagnation=2, failure=99)
    args = {"path": "log.txt"}
    for index in range(3):
        assert tracker.check_call("read", args) is None
        tracker.record_result("read", args, f"line {index}", ok=True)
    block = tracker.check_call("read", args)
    assert block is not None and block.guard == GUARD_REPEAT


def test_result_comparison_ignores_line_endings_and_trailing_spaces() -> None:
    tracker = _tracker(repeat=99, stagnation=2, failure=99)
    args = {"command": "cat x"}
    tracker.record_result("bash", args, "hello  \r\nworld", ok=True)
    tracker.record_result("bash", args, "hello\nworld\n", ok=True)
    assert tracker.check_call("bash", args) is not None


def test_arguments_key_order_does_not_matter_for_repeat_detection() -> None:
    tracker = _tracker(repeat=2, stagnation=99, failure=99)
    assert tracker.check_call("custom", {"a": 1, "b": 2}) is None
    tracker.record_result("custom", {"a": 1, "b": 2}, "one", ok=True)
    block = tracker.check_call("custom", {"b": 2, "a": 1})
    assert block is not None and block.guard == GUARD_REPEAT


def test_failure_streak_circuit_breaks_only_after_the_limit_and_resets_on_success() -> None:
    tracker = _tracker(failure=3)
    for _ in range(2):
        tracker.record_result("bash", {"command": "false"}, "错误", ok=False)
    assert tracker.should_break() is False
    tracker.record_result("bash", {"command": "true"}, "ok", ok=True)
    assert tracker.should_break() is False  # 成功清零
    for _ in range(3):
        tracker.record_result("bash", {"command": "false"}, "错误", ok=False)
    assert tracker.should_break() is True


def test_malformed_calls_count_as_failures() -> None:
    tracker = _tracker(failure=2)
    tracker.record_malformed()
    assert tracker.should_break() is False
    tracker.record_malformed()
    assert tracker.should_break() is True


def test_planning_reinjects_once_then_terminates_at_the_limit() -> None:
    """第一次拦截：重注入目标与约束；累计到 planning 阈值：温和终止。"""
    tracker = _tracker(repeat=2, stagnation=99, failure=99, planning=2)
    args = {"command": "ls"}

    tracker.begin_batch()
    assert tracker.check_call("bash", args) is None
    tracker.record_result("bash", args, "one", ok=True)
    assert tracker.check_call("bash", args) is not None
    first = tracker.planning_after_batch()
    assert first is not None and first.kind == GUARD_REINJECT
    assert first.blocks == 1 and first.threshold == 2

    tracker.begin_batch()
    assert tracker.check_call("bash", args) is not None
    second = tracker.planning_after_batch()
    assert second is not None and second.kind == GUARD_TERMINATE
    assert second.blocks == 2


def test_planning_limit_three_allows_one_more_batch_before_terminating() -> None:
    tracker = _tracker(repeat=2, stagnation=99, failure=99, planning=3)
    args = {"command": "ls"}
    assert tracker.check_call("bash", args) is None  # 先放行一次，后续才到 repeat=2
    tracker.record_result("bash", args, "prime", ok=True)
    actions = []
    for _ in range(3):
        tracker.begin_batch()
        assert tracker.check_call("bash", args) is not None
        actions.append(tracker.planning_after_batch())
    assert [a.kind if a else None for a in actions] == [
        GUARD_REINJECT,
        None,
        GUARD_TERMINATE,
    ]


def test_a_long_varied_task_never_triggers_the_tool_layer() -> None:
    """误报保护：几十轮工具调用、参数与结果都在变化 → 不拦截、不熔断。"""
    tracker = _tracker()
    for index in range(60):
        args = {"path": f"file-{index}.txt"}
        tracker.begin_batch()
        assert tracker.check_call("read", args) is None
        tracker.record_result("read", args, f"content {index}", ok=True)
        assert tracker.planning_after_batch() is None
    assert tracker.should_break() is False


def test_planning_reminder_carries_goal_and_hard_constraints() -> None:
    text = planning_reminder("修复登录 bug", "连续 3 次调用 bash 且参数相同")
    assert "修复登录 bug" in text
    assert "硬约束" in text and "工作区之外" in text
    assert "修复登录 bug" in text and "换一种做法" in text


def test_circuit_reminder_carries_goal_and_forbids_more_tools() -> None:
    text = circuit_reminder("修复登录 bug", 3)
    assert "连续 3 次" in text and "熔断" in text
    assert "修复登录 bug" in text
    assert "不要再调用工具" in text and "总结" in text


def test_very_long_goal_is_clipped_and_annotated() -> None:
    text = planning_reminder("x" * 5000, "重复")
    assert "…" in text
    assert "硬约束" in text  # 截断目标不能吃掉约束段


def test_planning_terminate_message_states_the_reason() -> None:
    text = planning_terminate_message(2, 2, "连续 2 次调用 bash 且参数相同")
    assert "2 次" in text and "温和终止" in text
    assert "连续 2 次调用 bash" in text


def test_circuit_guard_name_is_exposed_for_event_records() -> None:
    assert GUARD_CIRCUIT == "circuitBreaker"
