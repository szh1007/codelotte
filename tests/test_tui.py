"""TUI（票据 05）：事件 → widget 渲染、Ctrl+C 中断后会话完好、--continue 回放与续写。

组件测试走 Textual 的 pilot（无头驱动）；模型走 Provider 缝的脚本化假客户端，
工具是真实实现——覆盖"事件流 → 界面"与"中断恢复"两条验收。
渲染快照（snap_compare）见文件末尾四例：空会话 / 流式文本 / 工具块 / 中断态。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from textual.pilot import Pilot
from textual.widgets import Input, Markdown, Static

from codelotte.cost import Catalog
from codelotte.loop import AgentLoop
from codelotte.permissions import (
    PermissionLayer,
    PermissionRequest,
    Rule,
    allow_builtin_tools,
    build_permission_layer,
)
from codelotte.providers.base import ProviderError, ReasoningDelta, TextDelta
from codelotte.sandbox import LocalExecutor
from codelotte.session.context import messages_from_entries
from codelotte.session.store import SessionStore, load_entries
from codelotte.tools import default_tools
from codelotte.tui import TuiApp
from codelotte.tui.app import ApprovalScreen, ToolCallBlock
from tests.fake_client import PAUSE, ScriptedClient, fake_catalog, text_turn, tool_turn

SESSION_NAME = "20260101T000000Z_testtest.jsonl"


def _make(
    tmp_path: Path,
    turns: Sequence[Sequence[object]],
    *,
    history: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    model: str = "fake-model",
    catalog: Catalog | None = None,
    permissions: PermissionLayer | None = None,
    context_window: int | None = None,
    startup_notices: Sequence[str] = (),
) -> tuple[TuiApp, ScriptedClient, SessionStore]:
    path = tmp_path / SESSION_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    store = SessionStore.resume(path)
    client = ScriptedClient(turns)
    loop = AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=store,
        model=model,
        catalog=catalog if catalog is not None else fake_catalog(model),
        permissions=permissions if permissions is not None else allow_builtin_tools(),
        messages=messages,
    )
    return (
        TuiApp(
            agent=loop,
            model=model,
            context_window=context_window,
            startup_notices=startup_notices,
            history=history or [],
        ),
        client,
        store,
    )


def _as_tui(pilot: Pilot) -> TuiApp:
    """pilot.app 的静态类型是 App[Any]（Pilot 的泛型参数是 App 的返回类型）：断言收窄。"""
    app = pilot.app
    assert isinstance(app, TuiApp)
    return app


async def _submit(pilot: Pilot, text: str) -> None:
    _as_tui(pilot).query_one(Input).value = text
    await pilot.press("enter")


async def _wait_idle(pilot: Pilot) -> None:
    for _ in range(500):
        if not _as_tui(pilot).turn_running:
            return
        await pilot.pause(0.02)
    raise AssertionError("回合没有在预期时间内结束")


def _texts(app: TuiApp) -> list[str]:
    return [str(widget.content) for widget in app.query(Static)]


def test_turn_renders_user_tool_block_and_answer(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")

    async def scenario() -> None:
        app, _client, store = _make(
            tmp_path, [tool_turn("read", {"path": str(target)}), text_turn("读到了 hello")]
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await _submit(pilot, "读一下 note.txt")
            await _wait_idle(pilot)

            assert any("读一下 note.txt" in t for t in _texts(app))
            block = app.query_one(ToolCallBlock)
            assert block.collapsed is True  # 验收：默认收起
            assert "read" in block.title and block.title.endswith("✓")
            assert "hello" in str(block.query_one(".tool-result", Static).content)
            args_text = str(block.query_one(".tool-args", Static).content)
            assert '"path"' in args_text and "note.txt" in args_text  # 完整参数在展开体里
            assert any("读到了 hello" in md.source for md in app.query(Markdown))

            entries = load_entries(store.path)
            assert [e["type"] for e in entries].count("tool_call") == 1
            assert [e["type"] for e in entries].count("tool_result") == 1

    asyncio.run(scenario())


def test_ctrl_c_interrupts_turn_and_session_survives(tmp_path: Path) -> None:
    async def scenario() -> None:
        app, client, store = _make(
            tmp_path, [[TextDelta("先说一半"), PAUSE], text_turn("第二答")]
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await _submit(pilot, "第一问")
            await asyncio.wait_for(client.paused.wait(), 5)  # 已卡在流中间
            await pilot.press("ctrl+c")
            for _ in range(200):
                if not app.turn_running:
                    break
                await pilot.pause(0.02)
            assert app.is_running  # 验收：中断不退出会话
            assert not app.turn_running
            assert any("已中断" in t for t in _texts(app))

            entries = load_entries(store.path)
            assistants = [e for e in entries if e.get("role") == "assistant"]
            assert assistants[-1]["stopReason"] == "interrupted"  # 记录是事实源
            assert assistants[-1]["content"] == "先说一半"

            # 会话完好：接着提问能完成，同一文件不重不漏
            await _submit(pilot, "第二问")
            await _wait_idle(pilot)

        entries = load_entries(store.path)
        users = [e["content"] for e in entries if e.get("role") == "user"]
        assistants = [e["content"] for e in entries if e.get("role") == "assistant"]
        assert users == ["第一问", "第二问"]
        assert assistants == ["先说一半", "第二答"]

    asyncio.run(scenario())


def test_ctrl_c_during_tool_execution_keeps_context_valid(tmp_path: Path) -> None:
    """回归（审查发现）：取消落在工具执行中时，assistant 声明的 tool_call 仍必须有一条 tool 应答，
    否则同一进程里继续提问，下一次请求整个 400（deepseek 协议要求）。"""
    sleep_cmd = f'"{sys.executable}" -c "import time; time.sleep(30)"'

    async def scenario() -> None:
        app, client, store = _make(
            tmp_path,
            [tool_turn("bash", {"command": sleep_cmd}, call_id="c1"), text_turn("收尾完成")],
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await _submit(pilot, "跑个长命令")
            for _ in range(200):  # 等工具块出现（ToolRequested 已广播、执行已开始）
                if app.query(ToolCallBlock):
                    break
                await pilot.pause(0.02)
            assert app.query(ToolCallBlock), "工具块没有出现"
            await pilot.pause(0.2)
            await pilot.press("ctrl+c")
            for _ in range(500):
                if not _as_tui(pilot).turn_running:
                    break
                await pilot.pause(0.02)
            assert app.is_running
            block = app.query_one(ToolCallBlock)
            assert "已中断" in block.title  # 块有明确收尾，不骗人地停在"运行中…"

            # 会话还活着：继续提问；重建的请求里 c1 有 tool 应答（协议有效即可正常发出）
            await _submit(pilot, "继续")
            await _wait_idle(pilot)
            assert len(client.requests) == 2
            roles = [m["role"] for m in client.requests[1]]
            assert roles == ["user", "assistant", "tool", "user"]
            assert client.requests[1][2]["tool_call_id"] == "c1"
            assert "中断" in client.requests[1][2]["content"]
            assert not any("模型调用失败" in t for t in _texts(app))

            entries = load_entries(store.path)
            assert [e["type"] for e in entries].count("tool_call") == 1
            assert [e["type"] for e in entries].count("tool_result") == 0  # 中断落在结果之前

    asyncio.run(scenario())


def test_resume_replays_usage_into_status_bar(tmp_path: Path) -> None:
    """--continue 后状态栏带上记录里的 token 用量（记录里有的，界面也要有）。"""

    async def scenario() -> None:
        history = [
            {"type": "message", "role": "user", "content": "上一问"},
            {"type": "message", "role": "assistant", "content": "上一答", "stopReason": "stop"},
            {"type": "usage", "inputTokens": 12, "outputTokens": 7, "cacheHitTokens": 8, "cacheMissTokens": 4},
        ]
        app, _client, _store = _make(
            tmp_path, [text_turn("x")], history=history, messages=messages_from_entries(history)
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.05)
            status = str(app.query_one("#status", Static).content)
            assert "tokens in=12 out=7" in status
            assert "缓存命中 67%" in status  # 8/(8+4)
            assert "≈" not in status  # 票据 05 时代的老记录没有估价：不显示金额、不回算

    asyncio.run(scenario())


def test_status_bar_shows_cost_after_turn(tmp_path: Path) -> None:
    """票据 07 验收：状态栏实时显示累计花费（连同 token 与缓存命中率）。"""

    async def scenario() -> None:
        app, _client, _store = _make(
            tmp_path,
            [text_turn("答案", usage=(100_000, 500, 80_000, 20_000))],
            model="deepseek-flash",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "问题")
            await _wait_idle(pilot)
            status = str(app.query_one("#status", Static).content)
            assert "tokens in=100000 out=500" in status
            assert "缓存命中 80%" in status  # 80000/(80000+20000)
            # (80000×0.04 + 20000×2.0 + 500×8.0)/1M ≈ 0.00708，谷时五折
            assert "¥0.047200" in status or "¥0.023600" in status

    asyncio.run(scenario())


def test_resume_replays_recorded_cost_into_status_bar(tmp_path: Path) -> None:
    """--continue 回放：记录里带 cost 的调用（票据 07 起）要把金额带回状态栏。"""

    async def scenario() -> None:
        history = [
            {
                "type": "usage",
                "model": "deepseek-flash",
                "inputTokens": 1_000_000,
                "outputTokens": 0,
                "cacheHitTokens": 1_000_000,
                "cacheMissTokens": 0,
                "period": "peak",
                "cost": 0.04,
            },
        ]
        app, _client, _store = _make(
            tmp_path, [text_turn("x")], history=history, messages=messages_from_entries(history)
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.05)
            status = str(app.query_one("#status", Static).content)
            assert "≈¥0.040000" in status

    asyncio.run(scenario())


def test_continue_renders_history_and_appends(tmp_path: Path) -> None:
    async def scenario() -> None:
        # 1) 先真实制造一段"被中断的上一轮"
        path = tmp_path / SESSION_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        store = SessionStore.resume(path)
        client1 = ScriptedClient([[TextDelta("上回说到一半"), PAUSE]])
        loop1 = AgentLoop(
            client=client1,
            tools=default_tools(LocalExecutor()),
            store=store,
            model="fake-model",
            catalog=fake_catalog(),
            permissions=allow_builtin_tools(),
        )

        async def drain() -> None:
            async for _event in loop1.run_turn("上回的问题"):
                pass

        task = asyncio.create_task(drain())
        await asyncio.wait_for(client1.paused.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # 2) --continue 语义：同一文件重建上下文 + 回放历史
        history = load_entries(path)
        messages = messages_from_entries(history)
        app, client2, _ = _make(tmp_path, [text_turn("这回接上了")], history=history, messages=messages)
        async with app.run_test(size=(100, 30)) as pilot:
            assert any("上回的问题" in t for t in _texts(app))  # 历史被回放
            assert any("上回说到一半" in md.source for md in app.query(Markdown))
            assert any("中断" in t for t in _texts(app))
            await _submit(pilot, "新问题")
            await _wait_idle(pilot)

        # 重建的上下文真的发给了模型：中断的 assistant 被跳过、新问题在最后
        assert [m["role"] for m in client2.requests[0]] == ["user", "user"]
        assert client2.requests[0][0]["content"] == "上回的问题"
        assert client2.requests[0][1]["content"] == "新问题"

        entries = load_entries(path)
        assert [e["content"] for e in entries if e.get("role") == "user"] == ["上回的问题", "新问题"]

    asyncio.run(scenario())


# ---- 渲染快照（首批四例，票据 05 验收）----


def test_snapshot_empty_session(snap_compare: Any, tmp_path: Path) -> None:
    app, _client, _store = _make(tmp_path, [text_turn("不会用到")])
    assert snap_compare(app, terminal_size=(92, 24))


def test_snapshot_streaming_text(snap_compare: Any, tmp_path: Path) -> None:
    app, _client, _store = _make(
        tmp_path, [text_turn("我先看一下项目说明，然后给你结论。\n\n- 第一步：读取\n- 第二步：总结")]
    )

    async def before(pilot: Pilot) -> None:
        await _submit(pilot, "读一下说明并总结")
        await _wait_idle(pilot)

    assert snap_compare(app, terminal_size=(92, 24), run_before=before)


def test_snapshot_tool_block(snap_compare: Any, tmp_path: Path) -> None:
    app, _client, _store = _make(
        tmp_path, [tool_turn("bash", {"command": "echo 42 passed"}), text_turn("测试全部通过。")]
    )

    async def before(pilot: Pilot) -> None:
        await _submit(pilot, "跑一下测试")
        await _wait_idle(pilot)

    assert snap_compare(app, terminal_size=(92, 24), run_before=before)


def test_snapshot_interrupted_turn(snap_compare: Any, tmp_path: Path) -> None:
    app, client, _store = _make(tmp_path, [[TextDelta("我正在整理思路，先写下第一段……"), PAUSE]])

    async def before(pilot: Pilot) -> None:
        await _submit(pilot, "想一个复杂的问题")
        await asyncio.wait_for(client.paused.wait(), 5)
        await pilot.press("ctrl+c")
        for _ in range(200):
            if not _as_tui(pilot).turn_running:
                break
            await pilot.pause(0.02)

    assert snap_compare(app, terminal_size=(92, 24), run_before=before)


def test_snapshot_approval_modal(snap_compare: Any, tmp_path: Path) -> None:
    """审批弹层（票据 09）：四个单行色块按钮的行状观感锁在这里。

    真机曾报按钮色块错位——根因是默认按钮靠 ▔/▁ 字形边条显形（部分终端字体下错位/缺字），
    现改为 compact 单行色块（无边框、等宽平分）。快照防回归。
    """
    app, _client, _store = _make(tmp_path, [text_turn("不会用到")])

    async def before(pilot: Pilot) -> None:
        app.push_screen(
            ApprovalScreen(
                PermissionRequest(
                    tool="bash",
                    subject="pwd && ls -la",
                    arguments={"command": "pwd && ls -la"},
                    rule=Rule(
                        tool="bash",
                        pattern="git push*",
                        verdict="ask",
                        source="user",
                        text="bash(git push*)",
                    ),
                )
            )
        )
        await pilot.pause()

    assert snap_compare(app, terminal_size=(92, 24), run_before=before)


# ---- 权限审批弹层（票据 09）----



async def _wait_for_approval(pilot: Pilot) -> None:
    app = _as_tui(pilot)
    for _ in range(300):
        if isinstance(app.screen, ApprovalScreen):
            return
        await pilot.pause(0.02)
    raise AssertionError("审批弹层没有出现")


def test_approval_modal_allows_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        target = tmp_path / "f.txt"
        target.write_text("hello\n", encoding="utf-8")
        app, _client, store = _make(
            tmp_path,
            [tool_turn("read", {"path": str(target)}), text_turn("读到了")],
            permissions=PermissionLayer(),  # 没有规则 → 默认询问
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "读文件")
            await _wait_for_approval(pilot)
            await pilot.press("y")  # 本次允许
            await _wait_idle(pilot)
        entries = load_entries(store.path)
        permission = next(e for e in entries if e["type"] == "permission")
        assert permission["allowed"] is True and permission["decision"] == "once"
        tool_result = next(e for e in entries if e["type"] == "tool_result")
        assert tool_result["ok"] is True and "hello" in tool_result["content"]

    asyncio.run(scenario())


def test_approval_always_writes_user_file_never_project(tmp_path: Path) -> None:
    """验收：『始终允许』写用户级规则文件——有测试证明不写项目文件。"""

    async def scenario() -> None:
        project = tmp_path / "proj"
        project.mkdir()
        home = tmp_path / "home"
        target = tmp_path / "f.txt"
        target.write_text("x\n", encoding="utf-8")
        layer = build_permission_layer(project, home=home)  # user_rules_path = home 下
        app, _client, _store = _make(
            tmp_path,
            [tool_turn("read", {"path": str(target)}), text_turn("好")],
            permissions=layer,
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "读")
            await _wait_for_approval(pilot)
            await pilot.press("a")  # 始终允许
            await _wait_idle(pilot)

        user_file = home / ".codelotte" / "permissions.json"
        assert json.loads(user_file.read_text(encoding="utf-8")) == {
            "allow": [f"read({target})"],
            "ask": [],
            "deny": [],
        }
        assert not (project / ".codelotte" / "permissions.json").exists()  # 绝不写项目文件

    asyncio.run(scenario())


def test_approval_deny_feeds_error_back_and_turn_continues(tmp_path: Path) -> None:
    async def scenario() -> None:
        target = tmp_path / "f.txt"
        target.write_text("x\n", encoding="utf-8")
        app, client, store = _make(
            tmp_path,
            [tool_turn("read", {"path": str(target)}), text_turn("好的，不读")],
            permissions=PermissionLayer(),
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "读文件")
            await _wait_for_approval(pilot)
            await pilot.press("n")  # 拒绝
            await _wait_idle(pilot)
            block = app.query_one(ToolCallBlock)
            assert block.title.endswith("✗")

        entries = load_entries(store.path)
        permission = next(e for e in entries if e["type"] == "permission")
        assert permission["allowed"] is False
        tool_result = next(e for e in entries if e["type"] == "tool_result")
        assert tool_result["ok"] is False and "权限层未放行" in tool_result["content"]
        # 拒绝回传模型后循环继续：第二次请求里能看到错误文本
        assert "权限层未放行" in client.requests[1][-1]["content"]

    asyncio.run(scenario())


def test_approval_session_decision_stays_in_memory(tmp_path: Path) -> None:
    """『本会话允许』只加内存规则：不写任何文件，同命令再次调用不再询问。"""

    async def scenario() -> None:
        project = tmp_path / "proj"
        project.mkdir()
        home = tmp_path / "home"
        target = tmp_path / "f.txt"
        target.write_text("hello\n", encoding="utf-8")
        layer = build_permission_layer(project, home=home)
        app, _client, store = _make(
            tmp_path,
            [
                tool_turn("read", {"path": str(target)}, call_id="c1"),
                tool_turn("read", {"path": str(target)}, call_id="c2"),
                text_turn("两次都读了"),
            ],
            permissions=layer,
        )
        approvals = 0
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "读两次")
            await _wait_for_approval(pilot)
            approvals += 1
            await pilot.press("s")  # 本会话允许
            await _wait_idle(pilot)
        assert approvals == 1  # 第二次同命令直接放行，没有再弹
        assert not (home / ".codelotte" / "permissions.json").exists()  # 本会话不落盘
        assert not (project / ".codelotte" / "permissions.json").exists()

        entries = load_entries(store.path)
        perms = [e for e in entries if e["type"] == "permission"]
        assert [p["decision"] for p in perms] == ["session", None]
        assert [p["allowed"] for p in perms] == [True, True]

    asyncio.run(scenario())


def test_ctrl_c_during_approval_cancels_cleanly(tmp_path: Path) -> None:
    async def scenario() -> None:
        target = tmp_path / "f.txt"
        target.write_text("x\n", encoding="utf-8")
        app, _client, store = _make(
            tmp_path,
            [tool_turn("read", {"path": str(target)}), text_turn("不该走到这里")],
            permissions=PermissionLayer(),
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "读文件")
            await _wait_for_approval(pilot)
            await pilot.press("ctrl+c")  # 弹层里 Ctrl+C：该调用按拒绝，回合取消
            for _ in range(300):
                if not app.turn_running:
                    break
                await pilot.pause(0.02)
            assert app.is_running  # 界面还在
            assert not isinstance(app.screen, ApprovalScreen)  # 弹层已关
            assert any("已中断" in t for t in _texts(app))

        entries = load_entries(store.path)
        assert not [e for e in entries if e["type"] == "tool_result"]  # 没执行
        # 审查修正：取消也不能留审计断链——判定已发生，permission 记录要有
        permission = next(e for e in entries if e["type"] == "permission")
        assert permission["allowed"] is False
        assert "取消" in permission["reason"]

    asyncio.run(scenario())


def test_permission_notices_are_shown_in_transcript(tmp_path: Path) -> None:
    async def scenario() -> None:
        layer = PermissionLayer(notices=["检测到项目级权限规则但此仓库未被信任，已忽略；运行 `codelotte trust` 确认"])
        app, _client, _store = _make(tmp_path, [text_turn("x")], permissions=layer)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.05)
            assert any("未被信任" in t for t in _texts(app))

    asyncio.run(scenario())


def test_status_bar_shows_name_and_context_percentage(tmp_path: Path) -> None:
    """状态栏：展示名 + 上下文占用（最近一次请求的输入 token / 窗口）。"""

    async def scenario() -> None:
        app, _client, _store = _make(
            tmp_path, [text_turn("答")], model="DeepSeek Flash", context_window=100
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.05)
            before = str(app.query_one("#status", Static).content)
            assert "DeepSeek Flash" in before  # 展示名（不是裸 id）
            assert "上下文" not in before  # 还没有调用：没有占用可言

            await _submit(pilot, "问")
            await _wait_idle(pilot)
            status = str(app.query_one("#status", Static).content)
            # text_turn 用量 (10, 5, 0, 0)：最近一次请求输入 10 tokens / 窗口 100
            assert "上下文 10.0%" in status

    asyncio.run(scenario())


def test_status_bar_clamps_context_percentage(tmp_path: Path) -> None:
    """超窗显示 >100%（回归：审查发现原来会渲染 500.0% 这种怪数字）。"""

    async def scenario() -> None:
        app, _client, _store = _make(
            tmp_path, [text_turn("答", usage=(500, 5, 0, 0))], context_window=100
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "问")
            await _wait_idle(pilot)
            status = str(app.query_one("#status", Static).content)
            assert "上下文 >100%" in status

    asyncio.run(scenario())


def test_reasoning_deltas_are_rendered_when_they_arrive(tmp_path: Path) -> None:
    """思考事件来了就展示（暗色块进对话流）：展示跟随开关，没有单独的展示配置——
    reasoning_effort 为 none 时接口根本不产生思考事件，TUI 也就没有可显示的内容。"""
    turn = [ReasoningDelta("先想一步"), *text_turn("答案")]

    async def scenario() -> None:
        app, _client, _store = _make(tmp_path, [turn])
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "问")
            await _wait_idle(pilot)
            assert any("先想一步" in t for t in _texts(app))
            assert any("答案" in md.source for md in app.query(Markdown))

    asyncio.run(scenario())


def test_reasoning_blocks_do_not_merge_across_failed_turns(tmp_path: Path) -> None:
    """回归（审查发现）：失败回合的思考块必须收尾——下一回合的思考不能被拼进旧块。"""
    turns = [
        [ReasoningDelta("第一回合想一点"), ProviderError("boom")],
        [ReasoningDelta("第二回合才想的"), *text_turn("答案")],
    ]

    async def scenario() -> None:
        app, _client, _store = _make(tmp_path, turns)
        async with app.run_test(size=(120, 30)) as pilot:
            await _submit(pilot, "第一问")
            await _wait_idle(pilot)
            assert any("第一回合想一点" in t for t in _texts(app))
            await _submit(pilot, "第二问")
            await _wait_idle(pilot)
            joined = "".join(_texts(app))
            assert "第二回合才想的" in joined
            assert "第一回合想一点第二回合才想的" not in joined  # 两块分开，不合并

    asyncio.run(scenario())


def test_startup_notices_are_mounted(tmp_path: Path) -> None:
    """启动提示（如更新内容）：完整文本挂进对话流。"""

    async def scenario() -> None:
        app, _client, _store = _make(
            tmp_path,
            [text_turn("x")],
            startup_notices=["更新内容（0.0.1 → 0.1.0）：\n【0.1.0】\n- 首个版本"],
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.05)
            assert any("更新内容" in t and "首个版本" in t for t in _texts(app))

    asyncio.run(scenario())
