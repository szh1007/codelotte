"""SSE 解码器单元测试（票据 02）。

覆盖：任意字节切分、CRLF、注释行（keep-alive）、[DONE]、
跨分片的多字节 UTF-8、多行 data、空流。
"""

from __future__ import annotations

from codelotte.providers.sse import SSEEvent, decode_sse


def _collect(data: bytes, chunk_size: int = 1_000_000) -> list[SSEEvent]:
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    return list(decode_sse(chunks))


def test_single_event_split_into_single_byte_chunks() -> None:
    events = _collect(b"data: hello\n\n", chunk_size=1)
    assert events == [SSEEvent(event=None, data="hello")]


def test_multiple_events_in_one_chunk() -> None:
    events = _collect(b"data: a\n\ndata: b\n\ndata: [DONE]\n\n")
    assert [e.data for e in events] == ["a", "b", "[DONE]"]


def test_crlf_line_endings() -> None:
    events = _collect(b"event: delta\r\ndata: x\r\n\r\n")
    assert events == [SSEEvent(event="delta", data="x")]


def test_comment_lines_are_ignored() -> None:
    events = _collect(b": keep-alive\n\ndata: real\n\n")
    assert [e.data for e in events] == ["real"]


def test_multiline_data_is_joined_with_newline() -> None:
    events = _collect(b"data: line1\ndata: line2\n\n")
    assert events == [SSEEvent(event=None, data="line1\nline2")]


def test_utf8_multibyte_split_across_chunks() -> None:
    payload = "递归就是函数调用自身。".encode("utf-8")
    events = _collect(b"data: " + payload + b"\n\n", chunk_size=1)
    assert [e.data for e in events] == ["递归就是函数调用自身。"]


def test_empty_stream_yields_nothing() -> None:
    assert _collect(b"") == []
    assert _collect(b": only comment\n\n") == []


def test_leading_space_after_colon_is_stripped_once() -> None:
    events = _collect(b"data:  two spaces\n\n")
    assert [e.data for e in events] == [" two spaces"]


def test_bom_prefix_is_stripped() -> None:
    events = _collect(b"\xef\xbb\xbfdata: x\n\n", chunk_size=1)
    assert events == [SSEEvent(event=None, data="x")]


def test_invalid_utf8_bytes_do_not_crash() -> None:
    events = _collect(b"data: \xff\xfe bad\n\n")
    assert len(events) == 1
    assert "bad" in events[0].data


def test_unterminated_tail_event_is_flushed_at_eof() -> None:
    events = _collect(b"data: tail")
    assert events == [SSEEvent(event=None, data="tail")]
