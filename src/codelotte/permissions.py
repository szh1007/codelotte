"""权限层（票据 09，SPEC §G）：模型"想跑"与"真的跑"之间的规则闸门。

- 规则语法 `tool(pattern)`（如 `bash(git diff *)`、`read(src/**)`）或裸 `tool`（匹配该工具全部
  调用）；pattern 是 shell 风格通配（`*` 匹配任意字符，含路径分隔符）；
- 判定三档 allow / ask / deny；**全局合并**后 deny > ask > allow，无规则命中默认 **ask**
  （"未命中 allow 的调用一律拒绝"是 headless fail-closed 的前提）；
- **破坏性动词保护**（硬编码清单）：通配规则不能自动放行含 `rm -rf`、`git push --force`、
  `git reset --hard`、`chmod -R`、`git clean -fd` 等模式的命令——只能精确规则或逐次审批。
  （回应 Claude Code 生态 `Bash(git *)` 类规则放行破坏性命令的已知教训。）
- 来源分层（命令行 > 项目级 `.codelotte/permissions.json` > 用户级 `~/.codelotte/permissions.json`）：
  层级决定**信任门槛与审计出处**；判定时全局合并，任何来源的 deny 都不会被更弱来源放行
  （宁严勿松：陌生仓库的通配 allow 压不过你用户文件里的 deny）。
- 未信任仓库的项目级规则被忽略并提示（`codelotte trust` 确认后生效）——防"clone 恶意仓库
  打开即被其规则劫持"。
- 审批四档：本次 / 本会话 / 始终（写**用户级**文件，绝不写项目）/ 拒绝。无头模式没有审批者，
  ask 一律 fail-closed 拒绝，原因写进会话记录。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOW = "allow"
ASK = "ask"
DENY = "deny"
_SEVERITY = {ALLOW: 0, ASK: 1, DENY: 2}

DECISION_ONCE = "once"
DECISION_SESSION = "session"
DECISION_ALWAYS = "always"
DECISION_DENY = "deny"

RULES_FILE = Path(".codelotte") / "permissions.json"  # 规则文件（用户级在家目录下、项目级在项目下）
TRUST_FILE = Path(".codelotte") / "trusted"

_SUBJECT_FIELDS = {"bash": "command", "read": "path", "write": "path", "edit": "path"}
_RULE_RE = re.compile(r"^(?P<tool>[a-z_][\w-]*)(?:\((?P<pattern>.*)\))?$")
_FILE_KEYS = (ALLOW, ASK, DENY)


def subject_of(tool: str, arguments: dict[str, Any]) -> str | None:
    """规则匹配的主体（工具调用的"主参数"）：bash→command，read/write/edit→path。"""
    field_name = _SUBJECT_FIELDS.get(tool)
    value = arguments.get(field_name) if field_name else None
    return value if isinstance(value, str) else None


def _segments_after(text: str, word: str) -> list[str]:
    """word 出现处到下一个命令分隔符（; & | 换行）之间的整段。

    旗标不只在命令词后面：`rm dir1 -rf dir2`、`git -C x push --force` 都要扫到——
    审查实测的七种漏抓形态都源于"只看紧跟命令词的旗标"。
    """
    return [m.group(1) for m in re.finditer(rf"\b{word}\b([^\n;&|]*)", text)]


def _flags(tokens: str) -> tuple[set[str], set[str]]:
    """从一段命令里收集旗标：(短旗标字母集合, 长旗标小写集合)。

    支持 -rf、-f -r、--recursive 等写法；长旗标按 GNU 前缀宽认（--rec → --recursive）。
    """
    short: set[str] = set()
    long: set[str] = set()
    for token in re.findall(r"(?<!\S)(-{1,2}[\w-]+)", tokens):
        if token.startswith("--"):
            long.add(token.lower())
        else:
            short.update(ch for ch in token[1:] if ch.isalpha())
    return short, long


def _long(long_flags: set[str], prefix: str) -> bool:
    return any(flag.startswith(prefix) for flag in long_flags)


def _has_destructive(command: str) -> str | None:
    """扫描整条命令，命中破坏性模式返回其名字（藏在中段/后置参数也要抓）。

    逐条独立判断、宁松勿漏：宁可误报进审批，不可漏放。
    """
    for segment in _segments_after(command, "rm"):
        short, long = _flags(segment)
        if ("r" in short or _long(long, "--rec")) and ("f" in short or _long(long, "--for")):
            return "rm -rf"
    for segment in _segments_after(command, "push"):
        short, long = _flags(segment)
        if "f" in short or _long(long, "--for"):  # 含 --force-with-lease：也是历史重写
            return "git push --force"
    for segment in _segments_after(command, "reset"):
        _short, long = _flags(segment)
        if _long(long, "--har"):
            return "git reset --hard"
    for segment in _segments_after(command, "chmod"):
        short, long = _flags(segment)
        if "R" in short or _long(long, "--rec"):  # chmod 的 -R 大写，-r 无关
            return "chmod -R"
    for segment in _segments_after(command, "clean"):
        short, long = _flags(segment)
        if ("f" in short or _long(long, "--for")) and "d" in short:
            return "git clean -fd"
    if re.search(r"\bmkfs\b|\bdd\b[^\n;&|]*\bof=/dev/", command, re.I):
        return "磁盘级破坏（mkfs / dd 写设备）"
    if re.search(r"\b(shutdown|reboot|poweroff)\b", command, re.I):
        return "关机/重启"
    return None


def _is_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def _covers_broadly(rule: "Rule") -> bool:
    """规则是否"宽"到需要破坏性保护：裸工具规则（匹配全部调用）或含通配的 pattern。"""
    return rule.pattern is None or _is_wildcard(rule.pattern)


def _exact_pattern(subject: str) -> str:
    """把原文字符串变成只匹配它自己的 fnmatch 模式（转义通配字符）。"""
    return re.sub(r"([*?\[\]])", r"[\1]", subject)


@dataclass(frozen=True)
class Rule:
    """一条规则。pattern=None 表示"该工具的全部调用"；text 是原文（审计展示用）。"""

    tool: str
    pattern: str | None
    verdict: str
    source: str  # cli / project / user / session
    text: str


def rule_text(tool: str, subject: str | None) -> str:
    return tool if subject is None else f"{tool}({subject})"


def parse_rule(text: str, verdict: str, source: str) -> Rule:
    """解析 `tool` 或 `tool(pattern)`；畸形直接抛 ValueError（调用方转成可读报错/跳过）。"""
    match = _RULE_RE.match(text.strip())
    if match is None:
        raise ValueError(f"规则格式不对（要 `tool` 或 `tool(pattern)`）：{text!r}")
    tool = match.group("tool")
    pattern = match.group("pattern")
    return Rule(tool=tool, pattern=pattern, verdict=verdict, source=source, text=text.strip())


def _load_rules_file(path: Path, *, source: str) -> tuple[list[Rule], list[str]]:
    """读 JSON 规则文件：`{"allow": ["read", ...], "ask": [...], "deny": [...]}`。

    整份不是合法 JSON → 忽略全部规则（安全方向：等于没写规则）并汇报；
    单条解析失败 → 跳过该条并汇报；未知键 → 忽略并汇报。任何问题都不静默吞。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        return [], [f"权限规则文件 {path} 不是合法 JSON，已忽略全部规则（{exc}）"]
    if not isinstance(raw, dict):
        return [], [
            f'权限规则文件 {path} 的顶层应是对象（{{"allow": [...], "ask": [...], "deny": [...]}}），已忽略全部规则'
        ]
    rules: list[Rule] = []
    problems: list[str] = []
    for key, entries in raw.items():
        if key not in _FILE_KEYS:
            problems.append(f"权限规则文件 {path} 有未知键 {key!r}，已忽略")
            continue
        if not isinstance(entries, list):
            problems.append(f"权限规则文件 {path} 的 {key!r} 应是字符串数组，已忽略该键")
            continue
        for entry in entries:
            try:
                rules.append(parse_rule(str(entry), key, source))
            except ValueError as exc:
                problems.append(f"权限规则文件 {path} 的 {key} 里有无法解析的规则：{exc}")
    return rules, problems


def append_rules(path: Path, verdict: str, texts: Sequence[str]) -> tuple[list[str], list[str]]:
    """往 JSON 规则文件追加规则（读-改-写，保留文件里已有的其他键）。

    返回 (新增, 已存在)；已存在的规则不重复追加、无新增时不触碰文件。
    文件损坏（非法 JSON / 结构不对）抛 ValueError——调用方决定报错还是降级，绝不毁人文件。
    """
    data: dict[str, Any] = {}
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            raise ValueError(f"{path} 的顶层应是 JSON 对象，先手动修好再自动写入")
        data.update(raw)
    for key in _FILE_KEYS:
        entries = data.get(key, [])
        if not isinstance(entries, list):
            raise ValueError(f"{path} 的 {key!r} 应是字符串数组，先手动修好再自动写入")
        data[key] = [str(item) for item in entries]
    added: list[str] = []
    existing: list[str] = []
    for text in texts:
        if text in data[verdict]:
            existing.append(text)
        else:
            data[verdict].append(text)
            added.append(text)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return added, existing


def _normalized(path: Path) -> str:
    resolved = str(path.resolve())
    return resolved.casefold() if os.name == "nt" else resolved  # 只有 Windows 大小写不敏感


def is_trusted(cwd: Path, trust_file: Path) -> bool:
    """信任表只认**绝对路径**条目：相对条目解析随 cwd 漂移（审查实测：仓库自带一个
    `trusted` 文件写 "." 就能给自己背书）——手写/伪造的相对条目一律不参与比对。"""
    if not trust_file.is_file():
        return False
    target = _normalized(cwd)
    for line in trust_file.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or not Path(entry).is_absolute():
            continue
        if _normalized(Path(entry)) == target:
            return True
    return False


def trust_project(cwd: Path, trust_file: Path) -> None:
    """把项目目录写进信任表（幂等）。"""
    trust_file.parent.mkdir(parents=True, exist_ok=True)
    with trust_file.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(str(cwd.resolve()) + "\n")


@dataclass(frozen=True)
class Check:
    """一次调用的规则判定结果。rule=None 表示没有规则命中（默认 ask）。"""

    verdict: str
    subject: str | None
    rule: Rule | None


@dataclass(frozen=True)
class PermissionRequest:
    """交给审批者（TUI/其它交互面）的询问：工具、主参数与命中的规则。"""

    tool: str
    subject: str | None
    arguments: dict[str, Any]
    rule: Rule | None


Approver = Callable[[PermissionRequest], Awaitable[str]]


class PermissionLayer:
    """规则集合与判定。文件与信任在 build_permission_layer 里组装；本类不碰环境。"""

    def __init__(
        self,
        rules: Sequence[Rule] = (),
        *,
        notices: Sequence[str] = (),
        user_rules_path: Path | None = None,
    ) -> None:
        self._rules = list(rules)
        self._session: list[Rule] = []
        self.notices = list(notices)  # 加载期的问题与提示（CLI/TUI 负责展示）
        self.user_rules_path = user_rules_path  # "始终允许"写这里（绝不写项目文件）

    @property
    def rules(self) -> tuple[Rule, ...]:
        return (*self._rules, *self._session)

    def evaluate(self, tool: str, arguments: dict[str, Any]) -> Check:
        """全局合并判定：deny > ask > allow；无命中默认 ask。"""
        subject = subject_of(tool, arguments)
        best: Rule | None = None
        for rule in self.rules:
            if rule.tool != tool:
                continue
            if rule.pattern is not None:
                if subject is None or not fnmatch.fnmatch(subject, rule.pattern):
                    continue
            if (
                rule.verdict == ALLOW
                and _covers_broadly(rule)
                and subject is not None
                and _has_destructive(subject) is not None
            ):
                # 破坏性动词保护（SPEC §G 硬约束）：通配**和裸工具规则**（它是最宽的通配）
                # 都不放行破坏性命令——只能精确规则或逐次审批。审查实测：`--allow bash`
                # 曾让 `rm -rf /` 直接放行。
                continue
            if best is None or _SEVERITY[rule.verdict] > _SEVERITY[best.verdict]:
                best = rule
        if best is None:
            return Check(verdict=ASK, subject=subject, rule=None)
        return Check(verdict=best.verdict, subject=subject, rule=best)

    def apply_decision(self, tool: str, arguments: dict[str, Any], decision: str) -> Rule | None:
        """把审批结果落成规则：本次/拒绝不留规则；本会话/始终加精确规则（始终兼写用户文件）。

        安全约束（审查实测的越权路径）：规则绝不允许比被批准的调用更宽——
        - 无主参数 → 不落规则（裸工具规则放的就是整个工具，远超本次批准）；降级为"本次"；
        - 任何**断行类控制字符**（\\n \\r \\v \\f \\x1c-\\x1e \\x85 U+2028/9）都会让写出的行
          在重载时裂成多条规则 → "始终"降级为"本会话"；NUL 直接拒写。
        """
        if decision in (DECISION_ONCE, DECISION_DENY):
            return None
        subject = subject_of(tool, arguments)
        if subject is None:
            self.notices.append(
                f"审批：{tool} 调用没有可匹配的主参数，无法生成精确规则——'允许'按本次处理"
            )
            return None
        lines = subject.splitlines()
        if "\x00" in subject:
            self.notices.append("审批：命令含 NUL 字符，无法生成精确规则——'允许'按本次处理")
            return None
        if len(lines) != 1:  # splitlines 覆盖全部断行字符（\r \v \f \x85 U+2028…），不只 \n
            decision = DECISION_SESSION
            self.notices.append(
                "审批：命令含换行/控制字符，'始终允许'降级为'本会话允许'（避免规则文件被撑破）"
            )
        pattern = _exact_pattern(subject)
        rule = Rule(
            tool=tool,
            pattern=pattern,
            verdict=ALLOW,
            source=DECISION_SESSION if decision == DECISION_SESSION else "user",
            text=rule_text(tool, subject),
        )
        self._session.append(rule)
        if decision == DECISION_ALWAYS and self.user_rules_path is not None:
            try:
                append_rules(self.user_rules_path, ALLOW, [rule.text])
            except (OSError, ValueError) as exc:
                # 写不进去（文件损坏/权限）就降级：会话规则仍在，本次运行不受影响
                self.notices.append(
                    f"审批：写用户级规则文件失败（{exc}），'始终允许'降级为'本会话允许'"
                )
        return rule


def build_permission_layer(
    cwd: Path, *, home: Path | None = None, cli_rules: Sequence[Rule] = ()
) -> PermissionLayer:
    """组装运行用的权限层：CLI 规则 + 项目级（需信任）+ 用户级；问题收进 notices。"""
    home_dir = home if home is not None else Path.home()
    notices: list[str] = []
    user_path = home_dir / RULES_FILE
    if user_path.is_file():
        user_rules, problems = _load_rules_file(user_path, source="user")
        notices.extend(problems)
    else:
        user_rules = []
    project_path = cwd / RULES_FILE
    project_rules: list[Rule] = []
    if project_path.is_file():
        if is_trusted(cwd, home_dir / TRUST_FILE):
            project_rules, problems = _load_rules_file(project_path, source="project")
            notices.extend(problems)
        else:
            notices.append(
                f"检测到项目级权限规则（{project_path}）但此仓库未被信任，已忽略；"
                "运行 `codelotte trust` 确认一次后生效"
            )
    return PermissionLayer(
        [*cli_rules, *project_rules, *user_rules],
        notices=notices,
        user_rules_path=user_path,
    )


def allow_builtin_tools() -> PermissionLayer:
    """裸放行四个内置工具的层（破坏性保护仍生效）——测试与"完全可信"场景用；
    生产走 build_permission_layer。命名如实：它放的是内置工具，不是所有工具。"""
    return PermissionLayer([parse_rule(tool, ALLOW, "cli") for tool in _SUBJECT_FIELDS])
