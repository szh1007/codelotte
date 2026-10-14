"""工具调用分片装配的单元测试（票据 03）：多分片、并行多工具、畸形 JSON。"""

from __future__ import annotations

import pytest

from codelotte.providers.base import ToolCall
from codelotte.providers.tool_calls import ToolCallAssembler, ToolCallAssemblyError


def test_single_call_assembled_from_fragments() -> None:
    """id/name 只在首个分片出现，arguments 分多片到达——拼装后原样保留 JSON 文本。"""
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="call_1", name="read", arguments='{"pa')
    assembler.add_fragment(0, arguments='th": "a.txt"')
    assembler.add_fragment(0, arguments="}")
    assert assembler.finish() == (
        ToolCall(id="call_1", name="read", arguments='{"path": "a.txt"}'),
    )


def test_parallel_calls_with_interleaved_fragments() -> None:
    """并行多工具：不同 index 的分片交错到达，各自独立拼装。"""
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", name="read", arguments='{"path": "a"')
    assembler.add_fragment(1, id="c1", name="read", arguments='{"path": "b"')
    assembler.add_fragment(0, arguments="}")
    assembler.add_fragment(1, arguments="}")
    assert assembler.finish() == (
        ToolCall(id="c0", name="read", arguments='{"path": "a"}'),
        ToolCall(id="c1", name="read", arguments='{"path": "b"}'),
    )


def test_out_of_order_indexes_are_sorted() -> None:
    """index 乱序到达也按 index 排序输出（执行顺序与会话顺序确定）。"""
    assembler = ToolCallAssembler()
    assembler.add_fragment(1, id="c1", name="read", arguments="{}")
    assembler.add_fragment(0, id="c0", name="read", arguments="{}")
    assert [c.id for c in assembler.finish()] == ["c0", "c1"]


def test_malformed_json_is_reported_on_the_call() -> None:
    """畸形 JSON 不算装配失败：记入 parse_error（回传模型自纠），原始文本保留。"""
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", name="read", arguments='{"path": ')
    (call,) = assembler.finish()
    assert call.parse_error is not None
    assert "JSON" in call.parse_error
    assert '{"path": ' in call.parse_error  # 报错信息带收到的片段，便于排查
    assert call.arguments == '{"path": '  # 原始文本逐字节保留（回传模型用）


def test_non_object_json_is_reported() -> None:
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", name="read", arguments='["a"]')
    (call,) = assembler.finish()
    assert call.parse_error is not None
    assert "JSON 对象" in call.parse_error


def test_parallel_malformed_call_does_not_affect_sibling() -> None:
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", name="read", arguments='{"path": ')
    assembler.add_fragment(1, id="c1", name="read", arguments='{"path": "ok.txt"}')
    calls = assembler.finish()
    assert calls[0].parse_error is not None
    assert calls[1].parse_error is None


def test_missing_name_raises() -> None:
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", arguments="{}")
    with pytest.raises(ToolCallAssemblyError) as excinfo:
        assembler.finish()
    assert "工具名" in str(excinfo.value)


def test_empty_arguments_normalized_to_empty_object() -> None:
    """模型对无参数工具可能给空串——按 {} 规范化，不算畸形。"""
    assembler = ToolCallAssembler()
    assembler.add_fragment(0, id="c0", name="read")
    assert assembler.finish() == (ToolCall(id="c0", name="read", arguments="{}"),)


def test_missing_id_is_synthesized_and_unique_across_rounds() -> None:
    """模型漏 id 时补 id：tool 结果消息靠它配对；带随机后缀，避免多轮之间撞车。"""

    def finish_once() -> str:
        assembler = ToolCallAssembler()
        assembler.add_fragment(0, name="read", arguments="{}")
        (call,) = assembler.finish()
        return call.id

    first, second = finish_once(), finish_once()
    assert first.startswith("call_0_")
    assert first != second


def test_finish_on_empty_assembler_returns_nothing() -> None:
    assert ToolCallAssembler().finish() == ()
