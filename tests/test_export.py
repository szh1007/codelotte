"""HTML 会话导出（票据 08）：内容完整 + 转义安全 + 纯函数 + CLI 可用 + 与 TUI 数字一致。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from codelotte.cost import Ledger, call_record_from_entry, format_money, load_catalog
from codelotte.export import render_session_html, render_session_markdown
from tests.support import home_env, run_cli, sessions_dir, write_user_config


def _entries() -> list[dict]:
    return [
        {"type": "session", "schema": "session/v1", "cwd": "D:/proj", "version": "0.1.0"},
        {"type": "message", "role": "user", "content": "读一下 note.txt"},
        {
            "type": "message",
            "role": "assistant",
            "content": "",
            "reasoningContent": "先读文件",
            "stopReason": "tool_calls",
            "toolCalls": [{"id": "c1", "name": "read", "arguments": '{"path": "note.txt"}'}],
        },
        {
            "type": "tool_call",
            "toolCallId": "c1",
            "name": "read",
            "arguments": {"path": "note.txt"},
            "env": "local",
        },
        {
            "type": "tool_result",
            "toolCallId": "c1",
            "name": "read",
            "ok": True,
            "content": "hello\n",
            "durationMs": 3,
            "env": "local",
        },
        {"type": "message", "role": "assistant", "content": "读到了 hello", "stopReason": "stop"},
        {
            "type": "usage",
            "model": "deepseek-flash",
            "inputTokens": 100,
            "outputTokens": 10,
            "cacheHitTokens": 80,
            "cacheMissTokens": 20,
            "period": "peak",
            "cost": 0.0002,
            "currency": "CNY",
            "timestamp": "2026-10-16T01:00:00+00:00",
        },
        {"type": "event", "kind": "fork", "timestamp": "2026-10-16T01:01:00+00:00"},
        {"type": "message", "role": "assistant", "content": "说到一半", "stopReason": "interrupted"},
    ]


def _render(entries: list[dict] | None = None) -> str:
    return render_session_html(entries or _entries(), load_catalog(), session_name="s.jsonl")


def test_renders_timeline_with_messages_reasoning_and_tool_calls() -> None:
    html = _render()
    assert '<div class="user">' in html and "读一下 note.txt" in html
    assert "读到了 hello" in html
    assert "思考过程" in html and "先读文件" in html  # 思考过程可折叠展示
    assert "⚙ read" in html
    assert "&quot;path&quot;: &quot;note.txt&quot;" in html  # 参数（转义后的原样 JSON）
    assert "（3ms）" in html and "hello" in html  # 工具结果（含耗时）
    assert "本回合在此中断" in html  # 中断标注
    assert "分支点" in html  # 标记层：fork
    assert "D:/proj" in html  # 页头元信息


def test_renders_cost_panel_with_totals_and_price_notes() -> None:
    html = _render()
    assert "成本面板" in html
    assert "<td>deepseek-flash</td>" in html
    assert '<td class="peak">峰值</td>' in html
    assert "<td>80 / 20</td>" in html  # 输入 命中/未命中
    assert "¥0.000200" in html
    assert "合计 1 次调用（人民币元）" in html
    assert "80%" in html  # 命中率
    assert "2026-10-16 01:00 UTC" in html
    assert "命中 0.04 · 未命中 2.0 · 输出 8.0" in html  # 价目脚注


def test_escapes_everything_that_enters_html() -> None:
    """验收：防注入——所有文本都转义，任何语境都逃不出去。"""
    hostile = '</div><script>alert("x")</script>`&<img src=x onerror=y>`'
    entries = [
        {"type": "session", "schema": "session/v1", "cwd": f"proj{hostile}"},
        {"type": "message", "role": "user", "content": hostile},
        {
            "type": "tool_call",
            "toolCallId": "c1",
            "name": hostile,
            "arguments": {"<b>": hostile},
            "parseError": hostile,
        },
        {"type": "tool_result", "toolCallId": "c1", "name": "x", "ok": False, "content": hostile},
        {"type": "usage", "model": hostile, "inputTokens": 1, "outputTokens": 0,
         "cacheHitTokens": 0, "cacheMissTokens": 1, "period": "offpeak", "cost": None},
    ]
    html = render_session_html(entries, load_catalog(), session_name=hostile)
    # 结构性检查：任何原始标签都造不出来（"onerror=" 作为纯文本出现是转义后的正常内容，无害）
    assert "<script" not in html and "<img" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x onerror=y&gt;" in html
    assert "&amp;`" in html or "&amp;" in html


def test_has_no_external_references_or_scripts() -> None:
    """验收：零外链、零脚本——断网可开、随处分发。"""
    html = _render()
    for forbidden in ("<script", "<link", "src=", "href=", "http://", "https://", "@import", "url("):
        assert forbidden not in html, forbidden


def test_pure_function_renders_identical_bytes_twice() -> None:
    """验收：同一会话文件两次导出结果一致（无时间戳、无哈希序）。"""
    assert _render() == _render()


def test_long_tool_result_is_clipped_with_marker() -> None:
    entries = _entries()
    entries[4]["content"] = "x" * 3000
    html = _render(entries)
    assert "共 3000 字符，已截断" in html
    assert "x" * 3000 not in html


def test_legacy_usage_without_cost_shows_dashes() -> None:
    entries = [
        {"type": "usage", "model": "deepseek-flash", "inputTokens": 10, "outputTokens": 3,
         "cacheHitTokens": 4, "cacheMissTokens": 6},
    ]
    html = _render(entries)
    assert "<td>—</td>" in html  # 费用列
    assert "合计 1 次调用（人民币元）" in html
    assert "没有它的价目" not in html  # 模型在目录里：脚注照常给价目，只是这条记录没有估价
    assert "价目出处" in html  # 随包目录的 priceNote 进了脚注（账单能自证按哪天的表算）


def test_orphan_tool_result_is_shown_not_hidden() -> None:
    entries = [{"type": "tool_result", "toolCallId": "gone", "name": "x", "ok": True, "content": "孤儿结果"}]
    assert "无对应调用" in _render(entries)


def test_unknown_entry_types_are_annotated() -> None:
    entries = [{"type": "compaction", "summary": "以后会有的类型"}]
    html = _render(entries)
    assert "记录：compaction" in html


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """export 冒烟（不需要密钥）：配置写进临时 home 的用户级文件，环境走共享助手。"""
    home = write_user_config(cwd / "home", api_key=None)
    return run_cli(*args, cwd=cwd, env=home_env(home))


def _make_session(tmp_path: Path, *, fork: bool = False) -> Path:
    """在临时项目目录里造一份会话（会话目录固定为 home 下的 .codelotte/sessions）；返回项目目录。"""
    from codelotte.session.store import SessionStore, load_entries

    project = tmp_path / "proj"
    project.mkdir()
    sessions = sessions_dir(project / "home")
    store = SessionStore.start(project, base_dir=sessions)
    store.append("message", role="user", content="主线的问题")
    store.append("message", role="assistant", content="主线的回答", model="m", stopReason="stop")
    if fork:
        store.fork(load_entries(store.path)[1]["id"])
        store.append("message", role="user", content="分支的问题")
        store.append("message", role="assistant", content="分支的回答", model="m", stopReason="stop")
    return project


def test_cli_export_writes_selfcontained_file_without_key(tmp_path: Path) -> None:
    project = _make_session(tmp_path)
    result = _run_cli("export", "--html", cwd=project)
    assert result.returncode == 0, result.stderr
    assert "已导出：" in result.stdout
    output = project / result.stdout.split("已导出：", 1)[1].split("（", 1)[0]
    assert output.is_file() and output.parent == project
    text = output.read_text(encoding="utf-8")
    assert "主线的问题" in text and "主线的回答" in text
    assert "<script" not in text


def test_cli_export_selected_branch_and_purity(tmp_path: Path) -> None:
    project = _make_session(tmp_path, fork=True)
    # 列表：1 = 分支叶子（活动更新），2 = 主线叶子
    first = _run_cli("export", "--html", "2", "-o", "main.html", cwd=project)
    assert first.returncode == 0, first.stderr
    text = (project / "main.html").read_text(encoding="utf-8")
    assert "主线的问题" in text and "分支的问题" not in text

    again = _run_cli("export", "--html", "2", "-o", "main2.html", cwd=project)
    assert again.returncode == 0, again.stderr
    assert (project / "main.html").read_bytes() == (project / "main2.html").read_bytes()


def test_cli_export_error_paths_are_readable(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    # 两条选择路径的"查无此物"同码（审查修正）：无序号与越界序号都是 2
    missing = _run_cli("export", "--html", cwd=project)
    assert missing.returncode == 2
    assert "没有可导出的会话" in missing.stderr
    assert "Traceback" not in missing.stderr

    without = _run_cli("export", cwd=project)
    assert without.returncode == 2
    assert "需要 --html 或 --md" in without.stderr

    both = _run_cli("export", "--html", "--md", cwd=project)
    assert both.returncode == 2  # 两种格式互斥（argparse 组）

    bad_index = _run_cli("export", "--html", "3", cwd=project)
    assert bad_index.returncode == 2
    assert "没有第 3 个可恢复的会话" in bad_index.stderr


def test_cli_export_corrupt_latest_file_fails_readably(tmp_path: Path) -> None:
    """回归（审查发现）：无序号路径上最新文件损坏时给可读错误，不裸 traceback。"""
    project = _make_session(tmp_path)
    corrupt = sessions_dir(project / "home").rglob("*.jsonl")
    target = next(iter(corrupt))
    target.write_text("{ 这不是 JSON\n", encoding="utf-8")

    result = _run_cli("export", "--html", cwd=project)
    assert result.returncode == 1
    assert "坏行" in result.stderr
    assert "Traceback" not in result.stderr


def test_export_matches_tui_visible_content_and_ledger_numbers(tmp_path: Path) -> None:
    """验收：导出内容与 TUI 所见逐项一致（用同一份真实运行记录抽查）。"""
    import asyncio

    from codelotte.loop import AgentLoop
    from codelotte.permissions import allow_builtin_tools
    from codelotte.sandbox import LocalExecutor
    from codelotte.session.store import SessionStore, load_entries
    from codelotte.tools import default_tools
    from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn

    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    path = tmp_path / "run.jsonl"
    path.write_text("", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("读到了 hello")])
    loop = AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=SessionStore.resume(path),
        model="fake-model",
        catalog=fake_catalog(),
        permissions=allow_builtin_tools(),
    )

    async def drain() -> None:
        async for _event in loop.run_turn("读一下 note.txt"):
            pass

    asyncio.run(drain())
    entries = load_entries(loop.session_path)
    html = render_session_html(entries, loop.catalog, session_name=loop.session_path.name)

    # TUI 里能看到的每一项（用户消息 / 工具块标题与结果 / 回答）在导出里都能看到
    assert "读一下 note.txt" in html
    assert "⚙ read" in html and "hello" in html
    assert "读到了 hello" in html

    # 成本数字与同一份记录喂给 Ledger 的结果一致（导出与 TUI 同源）
    ledger = Ledger()
    for entry in entries:
        if entry.get("type") == "usage":
            ledger.record(call_record_from_entry(entry))
    assert len(ledger.calls) == 2
    assert format_money(ledger.cost, "CNY") in html
    assert ledger.hit_rate_text in html


# ---- Markdown 格式（终端/编辑器直接读）----


def _render_md(entries: list[dict] | None = None) -> str:
    return render_session_markdown(entries or _entries(), load_catalog(), session_name="s.jsonl")


def test_markdown_renders_timeline_and_cost_panel() -> None:
    text = _render_md()
    assert "# codelotte 会话回放" in text
    assert "### ❯ 用户" in text and "读一下 note.txt" in text
    assert "### 🤖 助手" in text and "读到了 hello" in text
    assert "**🧠 思考过程**" in text and "先读文件" in text
    assert "⚙ read  note.txt  ✓" in text  # 与 TUI 同一句话（display.tool_title 共用）
    assert '"path": "note.txt"' in text  # 展开的参数（json 围栏）
    assert "（3ms）" in text and "hello" in text  # 工具结果含耗时
    assert "本回合在此中断" in text
    assert "分支点" in text
    assert "| 1 | 2026-10-16 01:00 UTC | deepseek-flash | 峰值 | 80 / 20 | 10 | 80% | ¥0.000200 |" in text
    assert "**合计**" in text and "1 次调用（人民币元）" in text
    assert "命中 0.04 · 未命中 2.0 · 输出 8.0" in text  # 价目脚注
    assert "价目出处" in text  # 随包目录的 priceNote 出处


def test_markdown_is_pure() -> None:
    assert _render_md() == _render_md()


def test_markdown_fence_outgrows_content_backticks() -> None:
    """结构安全：内容里的 ``` 冲不出围栏（围栏按内容最长反引号串 +1）——后续结构不被吞。"""
    entries = _entries()
    entries[4]["content"] = "前 ``` 中 ````` 后"
    text = _render_md(entries)
    assert "``````text" in text  # 内容里最长 5 个反引号 → 围栏 6 个
    assert "前 ``` 中 ````` 后" in text  # 内容逐字保留
    assert text.count("## 成本面板") == 1  # 后面的结构没有被吞掉


def test_markdown_table_escapes_pipes() -> None:
    entries = [
        {"type": "usage", "model": "mod|el", "inputTokens": 1, "outputTokens": 0,
         "cacheHitTokens": 1, "cacheMissTokens": 0, "period": "peak", "cost": 0.001},
    ]
    assert "mod\\|el" in _render_md(entries)


def test_cli_md_writes_markdown_by_default_and_selects_branch(tmp_path: Path) -> None:
    project = _make_session(tmp_path, fork=True)
    result = _run_cli("export", "--md", "2", cwd=project)
    assert result.returncode == 0, result.stderr
    output = project / result.stdout.split("已导出：", 1)[1].split("（", 1)[0]
    assert output.suffix == ".md"
    text = output.read_text(encoding="utf-8")
    assert "主线的问题" in text and "分支的问题" not in text
    assert "<html" not in text.lower()

    again = _run_cli("export", "--md", "2", "-o", "again.md", cwd=project)
    assert again.returncode == 0, again.stderr
    assert (project / "again.md").read_bytes() == output.read_bytes()


def test_permission_entries_render_as_markers() -> None:
    """票据 09 验收：判定落会话后，导出的 HTML 里可见（允许与拒绝都画出来）。"""
    denied = {
        "type": "permission",
        "toolCallId": "c1",
        "tool": "bash",
        "subject": "rm -rf ./build",
        "verdict": "ask",
        "rule": None,
        "source": None,
        "decision": "deny",
        "allowed": False,
        "reason": "无头模式未授权（fail-closed）",
    }
    allowed = {
        "type": "permission",
        "toolCallId": "c1",
        "tool": "bash",
        "subject": "git status",
        "verdict": "allow",
        "rule": "bash(git *)",
        "source": "user",
        "decision": None,
        "allowed": True,
        "reason": "规则放行（bash(git *)）",
    }
    entries = [denied, allowed]
    html = _render(entries)
    assert "⛔ 权限拒绝" in html and "fail-closed" in html
    assert "🔓 权限放行" in html and "bash(git *)" in html
    md = render_session_markdown(entries, load_catalog(), session_name="s.jsonl")
    assert "> ⛔ 权限拒绝：bash(rm -rf ./build)" in md
    assert "> 🔓 权限放行：bash(git status)" in md


def _guardrail_entries() -> list[dict]:
    return [
        {"type": "session", "schema": "session/v1", "cwd": "D:/proj", "version": "0.1.0"},
        {"type": "message", "role": "user", "content": "修 bug"},
        {
            "type": "event",
            "kind": "guardrail",
            "layer": "tool",
            "guard": "repeat",
            "message": "连续 3 次调用 bash 且参数相同",
            "count": 3,
            "threshold": 3,
        },
        {
            "type": "event",
            "kind": "guardrail",
            "layer": "reasoning",
            "guard": "circuitBreaker",
            "message": "连续 3 次工具调用失败，熔断当前回合（工具已禁用，请模型总结现状）",
            "injected": "[codelotte 推理层熔断] 请总结现状",
        },
    ]


def test_guardrail_markers_are_highlighted_in_html_and_markdown() -> None:
    """票据 11：拦截/熔断在导出里高亮（marker warn），并写明是哪一层。"""
    entries = _guardrail_entries()
    html = render_session_html(entries, load_catalog(), session_name="s.jsonl")
    assert 'class="marker warn"' in html
    assert "🛡 守护拦截（工具层）" in html
    assert "连续 3 次调用 bash 且参数相同" in html
    assert "🛡 守护拦截（推理层）" in html and "熔断" in html

    markdown = render_session_markdown(entries, load_catalog(), session_name="s.jsonl")
    assert "> 🛡 守护拦截（工具层）：连续 3 次调用 bash 且参数相同" in markdown
    assert "> 🛡 守护拦截（推理层）" in markdown


def test_guardrail_marker_escapes_model_text() -> None:
    entries = [
        {"type": "event", "kind": "guardrail", "layer": "tool", "message": "<script>alert(1)</script>"}
    ]
    html = render_session_html(entries, load_catalog(), session_name="s.jsonl")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
