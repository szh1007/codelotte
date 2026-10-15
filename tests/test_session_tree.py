"""会话树与分支（票据 06）：活动分支回溯、fork、可恢复列表、确定性装配、旧文件兼容。

会话文件是 append-only 的单文件树：线性对话＝退化的单链；fork 在同一文件里从某条记录
分岔（写一条 event/fork 标记，后续记录挂到它下面）。本文件只测数据层（store/context），
CLI 与端到端在 test_cli.py / test_roundtrip.py。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codelotte.session.context import messages_from_entries
from codelotte.session.store import (
    SessionStore,
    branch_entries,
    fork_at,
    fork_session,
    leaf_ids,
    list_resumable,
    load_entries,
    open_at,
    open_session,
)


def _seed(cwd: Path, base: Path) -> SessionStore:
    """两问两答的线性会话（票据 05 时代的文件形态）。"""
    store = SessionStore.start(cwd, base_dir=base)
    store.append("message", role="user", content="第一问")
    store.append("message", role="assistant", content="第一答", model="m", stopReason="stop")
    store.append("message", role="user", content="第二问")
    store.append("message", role="assistant", content="第二答", model="m", stopReason="stop")
    return store


def _ids(entries: list[dict]) -> list[str]:
    return [e["id"] for e in entries]


def _contents(messages: list[dict]) -> list[str]:
    return [m["content"] for m in messages]


def test_branch_entries_linear_is_file_order(tmp_path: Path) -> None:
    """旧线性文件兼容：文件本来就是单链，沿 parentId 回溯与文件顺序一致（无需迁移）。"""
    store = _seed(tmp_path / "proj", tmp_path / "sessions")
    entries = load_entries(store.path)
    assert _ids(branch_entries(entries)) == _ids(entries)
    assert branch_entries(entries, leaf_id=entries[1]["id"]) == entries[:2]
    assert branch_entries([]) == []


def test_branch_entries_reports_unknown_leaf_broken_chain_and_cycle() -> None:
    entries = [{"id": "a", "parentId": None}, {"id": "b", "parentId": "a"}]
    with pytest.raises(ValueError, match="没有记录 nope"):
        branch_entries(entries, leaf_id="nope")
    with pytest.raises(ValueError, match="链断了"):
        branch_entries([*entries, {"id": "c", "parentId": "zz"}])
    cyclic = [{"id": "a", "parentId": "b"}, {"id": "b", "parentId": "a"}]
    with pytest.raises(ValueError, match="成环"):
        branch_entries(cyclic)


def test_fork_keeps_both_branches_continuable_and_apart(tmp_path: Path) -> None:
    """验收：fork 后两条分支各自可继续、互不污染。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    first_answer = load_entries(store.path)[2]["id"]  # "第一答"

    store.fork(first_answer)
    store.append("message", role="user", content="换个问法")
    store.append("message", role="assistant", content="换个答法", model="m", stopReason="stop")
    fork_tip = store.leaf_id

    # 各自可继续：--continue 落在最后说话的分支上
    _, branch_messages = open_session(cwd, base_dir=base, resume=True)
    assert _contents(branch_messages) == ["第一问", "第一答", "换个问法", "换个答法"]

    # 回到原分支的老叶子继续：两条链互不看到对方的记录
    entries = load_entries(store.path)
    main_tip = entries[4]["id"]  # "第二答"（原分支叶子）
    resumed, main_messages = open_at(store.path, leaf_id=main_tip)
    assert _contents(main_messages) == ["第一问", "第一答", "第二问", "第二答"]
    resumed.append("message", role="user", content="主线续问")

    after = load_entries(store.path)
    assert _contents(messages_from_entries(branch_entries(after, resumed.leaf_id))) == [
        "第一问",
        "第一答",
        "第二问",
        "第二答",
        "主线续问",
    ]
    assert _contents(messages_from_entries(branch_entries(after, fork_tip))) == [
        "第一问",
        "第一答",
        "换个问法",
        "换个答法",
    ]


def test_fork_writes_marker_so_continue_lands_on_new_branch(tmp_path: Path) -> None:
    """fork 是写进文件的记录：就算新分支一句话没说，--continue 也已落在它上面。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    _, forked = fork_session(cwd, base_dir=base, from_end=2)  # 在"第二问"处分岔

    entries = load_entries(store.path)
    assert entries[-1]["type"] == "event" and entries[-1]["kind"] == "fork"
    assert entries[-1]["parentId"] == entries[3]["id"]  # 挂在分岔点"第二问"之下
    assert _contents(forked) == ["第一问", "第一答", "第二问"]

    resumed, messages = open_session(cwd, base_dir=base, resume=True)
    assert resumed.leaf_id == entries[-1]["id"]
    assert _contents(messages) == ["第一问", "第一答", "第二问"]


def test_fork_session_validates_point_and_session(tmp_path: Path) -> None:
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    with pytest.raises(FileNotFoundError):
        fork_session(cwd, base_dir=base, from_end=1)  # 还没有任何会话

    store = _seed(cwd, base)
    with pytest.raises(ValueError, match="≥ 1"):
        fork_session(cwd, base_dir=base, from_end=0)
    with pytest.raises(ValueError, match="只有 4 条消息"):
        fork_session(cwd, base_dir=base, from_end=5)
    assert len(load_entries(store.path)) == 5  # 失败的 fork 不留下痕迹


def test_assembly_is_byte_identical_across_loads(tmp_path: Path) -> None:
    """验收（确定性序列化）：同一状态两次装配逐字节一致——模型前缀缓存的前提。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    store.fork(load_entries(store.path)[1]["id"])  # 从"第一问"分岔
    store.append("message", role="user", content="新分支的问题")

    _, one = open_at(store.path)
    _, two = open_at(store.path)
    assert json.dumps(one, ensure_ascii=False) == json.dumps(two, ensure_ascii=False)


def test_fork_prefix_matches_original_prefix_byte_for_byte(tmp_path: Path) -> None:
    """验收（确定性序列化）：分叉不改前缀——新分支与原分支在分岔点前逐字节相同。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    _seed(cwd, base)
    _, original = open_session(cwd, base_dir=base, resume=True)
    _, forked = fork_session(cwd, base_dir=base, from_end=2)
    assert json.dumps(forked, ensure_ascii=False) == json.dumps(
        original[:3], ensure_ascii=False
    )


def test_leaf_ids_and_resume_list_mark_branches(tmp_path: Path) -> None:
    """验收：会话列表能选出正确分支，并带分支标注。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    entries = load_entries(store.path)
    assert leaf_ids(entries) == [entries[-1]["id"]]  # 线性会话只有一个叶子

    store.fork(entries[2]["id"])  # 从"第一答"分岔
    store.append("message", role="user", content="分支问")
    entries = load_entries(store.path)
    assert leaf_ids(entries) == [entries[4]["id"], entries[-1]["id"]]  # 主线叶子 + 分支叶子

    items, skipped = list_resumable(cwd, base_dir=base)
    assert skipped == []
    assert len(items) == 2
    assert items[0].leaf_id == entries[-1]["id"]  # 活动更新的排前
    assert items[0].fork_at is not None  # 分支标注：fork 自"第一答"
    assert items[0].messages == 3
    assert items[0].path == store.path
    assert items[1].leaf_id == entries[4]["id"]
    assert items[1].fork_at is None  # 主线没有标注
    assert items[1].messages == 4
    assert items[0].title == items[1].title == "第一问"


def test_resume_list_skips_sessions_without_messages(tmp_path: Path) -> None:
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    SessionStore.start(cwd, base_dir=base)  # 只有头记录的空会话不是可恢复项
    assert list_resumable(cwd, base_dir=base) == ([], [])
    assert list_resumable(tmp_path / "nope", base_dir=base) == ([], [])


def test_resume_list_skips_damaged_file_and_says_so(tmp_path: Path) -> None:
    """回归（审查发现）：一个坏文件不该打死整个列表，但也不能静默吞掉。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    damaged = store.path.with_name("20990101T000000Z_damaged0.jsonl")
    damaged.write_text('{"id": "x", "parentId": "zzz", "type": "session"}\n', encoding="utf-8")

    items, skipped = list_resumable(cwd, base_dir=base)
    assert [item.path for item in items] == [store.path]  # 好的会话照常列出
    assert len(skipped) == 1
    assert "damaged0.jsonl" in skipped[0] and "链断了" in skipped[0]


def test_fork_at_leaf_targets_the_selected_branch(tmp_path: Path) -> None:
    """--resume N --fork M 的底座：fork 可以落在指定分支的活动链上，而不是整份文件的末尾。"""
    base, cwd = tmp_path / "sessions", tmp_path / "proj"
    store = _seed(cwd, base)
    entries = load_entries(store.path)
    main_tip = entries[4]["id"]  # "第二答"

    # 在主线（非文件末尾的活动分支）的"第二答"处分岔
    _, forked = fork_at(store.path, leaf_id=main_tip, from_end=1)
    assert _contents(forked) == ["第一问", "第一答", "第二问", "第二答"]
    marker = load_entries(store.path)[-1]
    assert marker["type"] == "event" and marker["parentId"] == main_tip
