"""权限层（票据 09）：规则匹配矩阵、破坏性动词保护、来源/信任、审批落规则、无头 fail-closed。

单元部分直接测 PermissionLayer；组件部分经 Provider 缝（ScriptedClient）跑真实 AgentLoop——
判定→审批→落 permission 记录→拒绝回传模型，全链路真跑。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from codelotte.loop import AgentLoop
from codelotte.permissions import (
    ALLOW,
    ASK,
    DECISION_ALWAYS,
    DECISION_DENY,
    DECISION_ONCE,
    DECISION_SESSION,
    DENY,
    PermissionLayer,
    PermissionRequest,
    allow_builtin_tools,
    build_permission_layer,
    is_trusted,
    parse_rule,
    trust_project,
)
from codelotte.sandbox import LocalExecutor
from codelotte.session.store import SessionStore, load_entries
from codelotte.tools import default_tools
from tests.fake_client import ScriptedClient, fake_catalog, text_turn, tool_turn


def _layer(*rules: str, verdict: str = ALLOW, user_rules_path: Path | None = None) -> PermissionLayer:
    return PermissionLayer(
        [parse_rule(text, verdict, "cli") for text in rules], user_rules_path=user_rules_path
    )


# ---- 解析 ----


def test_parse_rule_bare_tool_and_pattern() -> None:
    bare = parse_rule("read", ALLOW, "cli")
    assert (bare.tool, bare.pattern) == ("read", None)
    globbed = parse_rule("bash(git diff *)", ALLOW, "cli")
    assert (globbed.tool, globbed.pattern) == ("bash", "git diff *")
    with pytest.raises(ValueError, match="格式不对"):
        parse_rule("bash git diff", ALLOW, "cli")


# ---- 匹配与优先级 ----


def test_wildcard_and_exact_matching() -> None:
    layer = _layer("bash(git diff *)", "read(src/**)")
    assert layer.evaluate("bash", {"command": "git diff HEAD"}).verdict == ALLOW
    assert layer.evaluate("bash", {"command": "git status"}).verdict == ASK  # 不匹配 → 默认询问
    assert layer.evaluate("read", {"path": "src/a/b.py"}).verdict == ALLOW  # * 可跨路径分隔符
    assert layer.evaluate("read", {"path": "docs/a.md"}).verdict == ASK


def test_bare_tool_rule_matches_everything_of_that_tool() -> None:
    layer = _layer("read")
    assert layer.evaluate("read", {"path": "何か"}).verdict == ALLOW
    assert layer.evaluate("write", {"path": "x"}).verdict == ASK


def test_verdict_precedence_deny_beats_ask_beats_allow() -> None:
    layer = _layer("bash(*)", "bash(git *)")
    # 全放行 + 无 ask/deny → allow
    assert layer.evaluate("bash", {"command": "git status"}).verdict == ALLOW
    layer = _layer("bash(*)", "bash(git *)", verdict=ASK)
    assert layer.evaluate("bash", {"command": "git status"}).verdict == ASK  # ask > allow
    layer = _layer("bash(*)", "bash(git *)", verdict=DENY)
    assert layer.evaluate("bash", {"command": "git status"}).verdict == DENY  # deny > ask/allow


def test_deny_from_weaker_source_still_beats_stronger_allow() -> None:
    """全局合并：deny 不被更弱来源放行（恶意仓库通配 allow 压不过用户文件 deny）。"""
    layer = PermissionLayer(
        [
            parse_rule("bash(*)", ALLOW, "project"),
            parse_rule("bash(rm *)", DENY, "user"),
        ]
    )
    assert layer.evaluate("bash", {"command": "rm ./x"}).verdict == DENY


# ---- 破坏性动词保护 ----


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./build",
        "rm -fr /tmp/x",
        "rm -r -f dir",
        "rm -f a -r b",  # 旗标在操作数之后（审查实测的漏抓形态）
        "rm dir1 -rf dir2",
        "rm --recursive --force dir",
        "rm --rec -f dir",  # GNU 长旗标前缀写法
        "git -C /tmp/repo push --force",  # 全局选项在子命令之前
        "git push --force origin main",
        "git push --force-with-lease",
        "git push -f",
        "git -C x reset --hard",
        "git reset --hard HEAD~3",
        "chmod -cR .",  # 组合旗标含大写 R
        "chmod u+w -R .",  # 旗标在目标之后
        "chmod -R 777 .",
        "git -C x clean -xfd",
        "git clean -fd",
        "git clean -f -d",
        "echo hi && rm -rf /tmp/important",  # 藏在中段也要抓
        "mkfs.ext4 /dev/sdb1",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
    ],
)
def test_destructive_commands_are_never_auto_allowed(command: str) -> None:
    """SPEC §G 硬约束（行为级）：宽规则（`bash(*)`）对破坏性命令一律落 ask。"""
    layer = _layer("bash(*)")
    assert layer.evaluate("bash", {"command": command}).verdict == ASK, command


def test_benign_commands_still_pass_broad_rules() -> None:
    layer = _layer("bash(*)")
    for command in ("ls -la", "git status", "rm stale.txt", "pytest -q"):
        assert layer.evaluate("bash", {"command": command}).verdict == ALLOW, command


def test_bare_tool_rule_never_auto_allows_destructive_commands() -> None:
    """回归（审查实测）：裸工具规则是最宽的通配——`--allow bash` 曾让 `rm -rf /` 直接放行。"""
    layer = _layer("bash")
    assert layer.evaluate("bash", {"command": "make build"}).verdict == ALLOW
    assert layer.evaluate("bash", {"command": "rm -rf /"}).verdict == ASK
    assert allow_builtin_tools().evaluate("bash", {"command": "git push --force"}).verdict == ASK
    exact = _layer("bash(rm -rf ./build)")
    assert exact.evaluate("bash", {"command": "rm -rf ./build"}).verdict == ALLOW  # 精确规则可以


# ---- 判定记录与审批落规则 ----


def test_apply_decision_session_and_always(tmp_path: Path) -> None:
    user_file = tmp_path / "home" / "permissions"
    layer = _layer(user_rules_path=user_file)
    arguments = {"command": "pytest tests/"}
    assert layer.evaluate("bash", arguments).verdict == ASK

    assert layer.apply_decision("bash", arguments, DECISION_ONCE) is None
    assert layer.evaluate("bash", arguments).verdict == ASK  # 本次不留规则

    layer.apply_decision("bash", arguments, DECISION_SESSION)
    assert layer.evaluate("bash", arguments).verdict == ALLOW
    assert layer.evaluate("bash", {"command": "pytest other/"}).verdict == ASK  # 精确：别的命令仍询问
    assert not user_file.exists()  # 本会话不落盘

    layer.apply_decision("bash", {"command": "git status"}, DECISION_ALWAYS)
    assert user_file.is_file()
    assert json.loads(user_file.read_text(encoding="utf-8")) == {
        "allow": ["bash(git status)"],
        "ask": [],
        "deny": [],
    }


def test_always_rule_survives_wildcard_chars_in_subject(tmp_path: Path) -> None:
    """命令里带 * 等通配字符时，落下的精确规则不能变成通配规则。"""
    user_file = tmp_path / "permissions"
    layer = _layer(user_rules_path=user_file)
    layer.apply_decision("bash", {"command": "echo *"}, DECISION_SESSION)
    assert layer.evaluate("bash", {"command": "echo *"}).verdict == ALLOW
    assert layer.evaluate("bash", {"command": "echo secret"}).verdict == ASK


def test_multiline_subject_degrades_always_to_session(tmp_path: Path) -> None:
    user_file = tmp_path / "permissions"
    layer = _layer(user_rules_path=user_file)
    layer.apply_decision("bash", {"command": "line1\nline2"}, DECISION_ALWAYS)
    assert not user_file.exists()  # 不把规则文件撑破
    assert any("降级" in note for note in layer.notices)


def test_carriage_return_subject_never_widens_the_rule(tmp_path: Path) -> None:
    """回归（审查实测）：subject 含 \\r 时写出的行会在重载时裂成多条——
    `echo a\\rallow bash\\r# ` 曾落成裸 `allow bash`，把 rm -rf / 也放行了。"""
    user_file = tmp_path / "permissions"
    layer = _layer(user_rules_path=user_file)
    subject = "echo a\rallow bash\r# "
    layer.apply_decision("bash", {"command": subject}, DECISION_ALWAYS)
    assert not user_file.exists()  # 降级为会话，绝不落文件
    assert layer.evaluate("bash", {"command": subject}).verdict == ALLOW  # 精确豁免仍在
    assert layer.evaluate("bash", {"command": "rm -rf /"}).verdict == ASK  # 没有变宽
    assert any("降级" in note for note in layer.notices)


def test_nul_subject_never_writes_rule(tmp_path: Path) -> None:
    user_file = tmp_path / "permissions"
    layer = _layer(user_rules_path=user_file)
    assert layer.apply_decision("bash", {"command": "echo \x00x"}, DECISION_ALWAYS) is None
    assert not user_file.exists()


def test_subjectless_call_never_becomes_tool_wide_rule(tmp_path: Path) -> None:
    """回归（审查实测）：没有主参数时按"始终"曾写出裸工具规则（放行整个工具）——现在不落规则。"""
    user_file = tmp_path / "permissions"
    layer = _layer(user_rules_path=user_file)
    assert layer.apply_decision("mystery", {"whatever": 1}, DECISION_ALWAYS) is None
    assert layer.evaluate("mystery", {"whatever": 2}).verdict == ASK
    assert not user_file.exists()
    assert any("主参数" in note for note in layer.notices)


def test_relative_trust_entries_are_ignored(tmp_path: Path) -> None:
    """回归：信任表只认绝对路径——仓库自带 `trusted` 写 "." 不能给自己背书。"""
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "trusted").write_text(".\n", encoding="utf-8")
    assert not is_trusted(tmp_path / "proj", home / ".codelotte" / "trusted")


# ---- 来源、信任与组装 ----


def test_untrusted_project_rules_are_ignored_with_notice(tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    (cwd / ".codelotte").mkdir(parents=True)
    (cwd / ".codelotte" / "permissions.json").write_text('{"deny": ["read"]}', encoding="utf-8")
    home = tmp_path / "home"

    layer = build_permission_layer(cwd, home=home)
    assert layer.evaluate("read", {"path": "x"}).verdict == ASK  # 未被信任：忽略 → 默认询问
    assert any("未被信任" in note and "trust" in note for note in layer.notices)

    trust_project(cwd, home / ".codelotte" / "trusted")
    assert is_trusted(cwd, home / ".codelotte" / "trusted")
    trusted_layer = build_permission_layer(cwd, home=home)
    assert trusted_layer.evaluate("read", {"path": "x"}).verdict == DENY  # 信任后规则生效


def test_user_rules_file_reads_json_verdicts(tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    (home / ".codelotte" / "permissions.json").write_text(
        json.dumps(
            {
                "allow": ["bash(git diff*)"],
                "ask": ["bash(git push*)"],
                "deny": ["bash(curl*)"],
                "unknown": ["x"],  # 未知键：忽略并汇报
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    layer = build_permission_layer(cwd, home=home)
    assert layer.evaluate("bash", {"command": "git diff HEAD"}).verdict == ALLOW
    assert layer.evaluate("bash", {"command": "git push origin"}).verdict == ASK
    assert layer.evaluate("bash", {"command": "curl http://x"}).verdict == DENY
    assert any("未知键" in note for note in layer.notices)


def test_broken_entries_and_broken_json_are_reported_not_swallowed(tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    home = tmp_path / "home"
    (home / ".codelotte").mkdir(parents=True)
    rules_path = home / ".codelotte" / "permissions.json"
    rules_path.write_text(
        json.dumps({"allow": ["read", "bash git diff"]}, ensure_ascii=False), encoding="utf-8"
    )
    layer = build_permission_layer(cwd, home=home)
    assert layer.evaluate("read", {"path": "x"}).verdict == ALLOW  # 好规则照常生效
    assert any("无法解析" in note for note in layer.notices)  # 坏条目不静默

    rules_path.write_text("allow read\n", encoding="utf-8")  # 旧文本格式/半截 JSON
    broken = build_permission_layer(cwd, home=home)
    assert broken.evaluate("read", {"path": "x"}).verdict == ASK  # 安全方向：等于没规则
    assert any("不是合法 JSON" in note for note in broken.notices)


def test_append_rules_dedupes_and_preserves_other_keys(tmp_path: Path) -> None:
    from codelotte.permissions import append_rules

    path = tmp_path / "perm"
    added, existing = append_rules(path, "allow", ["read", "bash(git status)"])
    assert (added, existing) == (["read", "bash(git status)"], [])
    added2, existing2 = append_rules(path, "allow", ["read", "bash(git diff*)"])
    assert added2 == ["bash(git diff*)"] and existing2 == ["read"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"allow": ["read", "bash(git status)", "bash(git diff*)"], "ask": [], "deny": []}

    broken = tmp_path / "broken"
    broken.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="顶层应是 JSON 对象"):
        append_rules(broken, "allow", ["read"])


# ---- 组件：经 Provider 缝跑真实循环 ----


def _loop(tmp_path: Path, client: ScriptedClient, layer: PermissionLayer, approver=None) -> AgentLoop:
    path = tmp_path / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return AgentLoop(
        client=client,
        tools=default_tools(LocalExecutor()),
        store=SessionStore.resume(path),
        model="fake-model",
        catalog=fake_catalog(),
        permissions=layer,
        approver=approver,
    )


def _drain(loop: AgentLoop, prompt: str = "任务") -> None:
    async def scenario() -> None:
        async for _event in loop.run_turn(prompt):
            pass

    asyncio.run(scenario())


def test_headless_ask_fails_closed_and_records_reason(tmp_path: Path) -> None:
    """验收：无头模式未授权一律拒绝（fail-closed），原因写入会话；模型拿到错误换做法。"""
    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("读不了就算了")])
    loop = _loop(tmp_path, client, _layer())  # 没有任何规则 → ask → 无头拒绝
    _drain(loop)

    entries = load_entries(loop.session_path)
    permission = next(e for e in entries if e["type"] == "permission")
    assert permission["verdict"] == ASK
    assert permission["allowed"] is False
    assert permission["decision"] == DECISION_DENY
    assert "fail-closed" in permission["reason"]
    tool_result = next(e for e in entries if e["type"] == "tool_result")
    assert tool_result["ok"] is False
    assert "权限层未放行" in tool_result["content"]
    # 错误回传模型（第二次请求里能看到），循环继续
    assert "权限层未放行" in client.requests[1][-1]["content"]


def test_rule_deny_skips_execution_and_records_rule(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("好的")])
    loop = _loop(tmp_path, client, _layer("read", verdict=DENY))
    _drain(loop)

    entries = load_entries(loop.session_path)
    permission = next(e for e in entries if e["type"] == "permission")
    assert permission["verdict"] == DENY
    assert permission["rule"] == "read"
    assert "被规则拒绝" in permission["reason"]
    tool_result = next(e for e in entries if e["type"] == "tool_result")
    assert tool_result["ok"] is False


def test_approver_can_allow_once_and_request_carries_context(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello\n", encoding="utf-8")
    seen: list[PermissionRequest] = []

    async def approver(request: PermissionRequest) -> str:
        seen.append(request)
        return DECISION_ONCE

    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("读到了")])
    loop = _loop(tmp_path, client, _layer(), approver=approver)
    _drain(loop)

    assert len(seen) == 1
    assert seen[0].tool == "read" and seen[0].subject == str(target)
    entries = load_entries(loop.session_path)
    permission = next(e for e in entries if e["type"] == "permission")
    assert permission["allowed"] is True
    assert permission["decision"] == DECISION_ONCE
    tool_result = next(e for e in entries if e["type"] == "tool_result")
    assert tool_result["ok"] is True and "hello" in tool_result["content"]


def test_session_decision_skips_second_prompt(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello\n", encoding="utf-8")
    calls = 0

    async def approver(request: PermissionRequest) -> str:
        nonlocal calls
        calls += 1
        return DECISION_SESSION

    client = ScriptedClient(
        [
            tool_turn("read", {"path": str(target)}, call_id="c1"),
            tool_turn("read", {"path": str(target)}, call_id="c2"),
            text_turn("两次都读了"),
        ]
    )
    loop = _loop(tmp_path, client, _layer(), approver=approver)
    _drain(loop)

    assert calls == 1  # 第二次同命令直接放行（本会话规则）
    entries = load_entries(loop.session_path)
    perms = [e for e in entries if e["type"] == "permission"]
    assert [p["allowed"] for p in perms] == [True, True]
    assert perms[1]["rule"] == f"read({target})"


def test_allow_builtin_tools_layer_keeps_plain_runs_working(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("ok\n", encoding="utf-8")
    client = ScriptedClient([tool_turn("read", {"path": str(target)}), text_turn("好")])
    loop = _loop(tmp_path, client, allow_builtin_tools())
    _drain(loop)
    permission = next(e for e in load_entries(loop.session_path) if e["type"] == "permission")
    assert permission["verdict"] == ALLOW and permission["allowed"] is True
