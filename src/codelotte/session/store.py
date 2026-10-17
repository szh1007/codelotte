"""append-only JSONL 会话存储（session/v1）：单文件树。

一条记录一行、永不改写；每条带 id/parentId 构成树（线性对话＝退化的单链）。
写入采用「打开-追加-关闭」，进程任何时刻崩溃都不丢已落盘记录；
行尾强制 LF（不用平台默认，保证跨平台可复现）。

树的使用方式（票据 06）：
- **活动分支**＝文件最后一条记录（按写入顺序）所在的链，上下文沿 parentId 回溯重建；
- **fork**＝从某条历史记录处写一条 event/fork 标记、后续记录挂在它之下：原分支一字不动，
  两条分支各自可继续（谁最后说话，--continue 就回到谁）；
- 旧线性文件无需迁移：它们本来就是单链的树，沿链回溯与文件顺序一致（有测试为证）。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codelotte import __version__
from codelotte.session.context import messages_from_entries

SCHEMA = "session/v1"

# 合法 JSON 但会被 str.splitlines 按换行拆开的字符（破坏"一条记录一行"不变量）
_LINE_BREAKER_CHARS = (chr(0x2028), chr(0x2029), chr(0x0085))
_BACKSLASH = chr(92)


class SessionError(ValueError):
    """会话使用层面的错误（分支选择越界、记录链损坏等）——错误信息直接给用户看。

    继承 ValueError 是为了让测试与调用方按语义捕获；json 解码错误等同族异常不受影响。
    """


def _default_base_dir() -> Path:
    return Path.home() / ".codelotte" / "sessions"


def project_key(cwd: Path) -> str:
    """把项目路径编码为目录名（沿用 pi 的规则：去首分隔符，斜杠、反斜杠、冒号换成 -）。"""
    trimmed = str(cwd).lstrip("/" + _BACKSLASH)
    for ch in ("/", _BACKSLASH, ":"):
        trimmed = trimmed.replace(ch, "-")
    return f"--{trimmed}--"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _escape_line_breakers(line: str) -> str:
    for ch in _LINE_BREAKER_CHARS:
        if ch in line:
            line = line.replace(ch, _BACKSLASH + f"u{ord(ch):04x}")
    return line


def load_entries(path: Path) -> list[dict[str, Any]]:
    """读整个会话文件的 entry 列表（跳过空行；坏行交给 json 直接暴露，不静默吞）。"""
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def branch_entries(
    entries: list[dict[str, Any]], leaf_id: str | None = None
) -> list[dict[str, Any]]:
    """活动分支：从 leaf（默认最后一条记录）沿 parentId 回溯到根的记录序列（根在前）。

    叶子不存在、链断裂或成环都直接报错——损坏的会话不该被猜着读。
    """
    if not entries:
        return []
    index = {entry["id"]: entry for entry in entries}
    current: str | None = leaf_id if leaf_id is not None else entries[-1]["id"]
    if current not in index:
        raise SessionError(f"会话里没有记录 {current}")
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current is not None:
        if current in seen:
            raise SessionError(f"会话记录的 parentId 成环（在 {current} 处）")
        seen.add(current)
        entry = index.get(current)
        if entry is None:
            raise SessionError(f"会话记录链断了：找不到父记录 {current}")
        chain.append(entry)
        current = entry.get("parentId")
    chain.reverse()
    return chain


def load_branch(path: Path, leaf_id: str | None = None) -> list[dict[str, Any]]:
    """读文件里某条分支的记录（leaf_id=None：当前活动分支）。"""
    return branch_entries(load_entries(path), leaf_id)


def leaf_ids(entries: list[dict[str, Any]]) -> list[str]:
    """没有被任何记录挂在下面的 id（文件顺序）——每个是一条可继续的分支。"""
    referenced = {entry.get("parentId") for entry in entries}
    return [entry["id"] for entry in entries if entry["id"] not in referenced]


def _fork_point_time(chain: list[dict[str, Any]]) -> str | None:
    """链上最后一次 fork 标记的前一条记录时间（分支标注用）；主线为 None。"""
    point: dict[str, Any] | None = None
    for i, entry in enumerate(chain):
        if i and entry.get("type") == "event" and entry.get("kind") == "fork":
            point = chain[i - 1]
    return str(point.get("timestamp", "")) if point is not None else None


def open_at(
    path: Path, *, leaf_id: str | None = None
) -> tuple["SessionStore", list[dict[str, Any]]]:
    """在既有会话文件的指定分支上继续（leaf_id=None：当前活动分支）。

    返回 (store, 重建的消息数组)；后续记录都写在这条分支上。
    """
    branch = load_branch(path, leaf_id)
    store = SessionStore.resume(path, leaf_id=branch[-1]["id"] if branch else None)
    return store, messages_from_entries(branch)


def open_session(
    cwd: Path, *, base_dir: Path | None = None, resume: bool = False
) -> tuple["SessionStore", list[dict[str, Any]]]:
    """新会话，或恢复最近一次会话的**活动分支**（--continue）。返回 (store, 重建的消息数组)。

    要恢复但没有任何会话文件时抛 FileNotFoundError——调用方转成用户可读的错误。
    """
    if not resume:
        return SessionStore.start(cwd, base_dir=base_dir), []
    path = latest_session_path(cwd, base_dir=base_dir)
    if path is None:
        raise FileNotFoundError(f"没有可继续的会话：{cwd} 下没有历史会话记录")
    return open_at(path)


def _check_from_end(from_end: int) -> None:
    if from_end < 1:
        raise SessionError(
            f"--fork 要一个 ≥ 1 的位置（倒数第几条消息），给了 {from_end}"
        )


def fork_at(
    path: Path, *, leaf_id: str | None = None, from_end: int
) -> tuple["SessionStore", list[dict[str, Any]]]:
    """从某条分支的倒数第 from_end 条消息处分岔（1 = 最后一条消息；leaf_id 选分支）。

    返回 (新分支的 store, 重建消息)。分岔点之前的记录与原分支逐字节相同——前缀缓存不掉。
    """
    _check_from_end(from_end)
    chain = load_branch(path, leaf_id)
    points = [
        (i, entry) for i, entry in enumerate(chain) if entry.get("type") == "message"
    ]
    if from_end > len(points):
        raise SessionError(
            f"这条分支上只有 {len(points)} 条消息，无法从倒数第 {from_end} 条处分叉"
        )
    index, point = points[-from_end]
    store = SessionStore.resume(path)
    store.fork(point["id"])
    return store, messages_from_entries(chain[: index + 1])


def fork_session(
    cwd: Path, *, base_dir: Path | None = None, from_end: int
) -> tuple["SessionStore", list[dict[str, Any]]]:
    """从最近会话的活动分支倒数第 from_end 条消息处创建新分支（--fork 的常见形式）。

    先校验参数再找会话：`--fork 0` 这样的用法错误应当立刻报，而不是被"没有会话"盖过去。
    """
    _check_from_end(from_end)
    path = latest_session_path(cwd, base_dir=base_dir)
    if path is None:
        raise FileNotFoundError(f"没有可分叉的会话：{cwd} 下没有历史会话记录")
    return fork_at(path, from_end=from_end)


@dataclass(frozen=True)
class ResumableItem:
    """一条可恢复的分支（会话文件 × 叶子记录）。"""

    path: Path
    leaf_id: str
    timestamp: str  # 叶子记录时间（排序与展示用）
    messages: int  # 链上的 message 记录数
    title: str  # 首条用户消息（列表里认人用）
    fork_at: str | None  # 分支标注：最近一次 fork 点的记录时间；主线为 None


def list_resumable(
    cwd: Path, *, base_dir: Path | None = None
) -> tuple[list[ResumableItem], list[str]]:
    """本项目下所有可继续的分支（叶子），按活动时间倒序（同刻后写的在前）。

    返回 (可恢复项, 被跳过的损坏文件说明)：一个坏文件不该让整个列表消失，
    但也不能静默吞掉——调用方负责把说明给用户看。只有头记录的空会话不是可恢复项。
    """
    base = base_dir if base_dir is not None else _default_base_dir()
    directory = base / project_key(cwd)
    if not directory.is_dir():
        return [], []
    sortable: list[tuple[tuple[str, int, str], ResumableItem]] = []
    skipped: list[str] = []
    for path in sorted(directory.glob("*.jsonl")):
        try:
            entries = load_entries(path)
        except (OSError, ValueError) as exc:
            skipped.append(f"{path.name}：{exc}")
            continue
        if not entries:
            continue
        for order, leaf in enumerate(leaf_ids(entries)):
            try:
                chain = branch_entries(entries, leaf)
            except SessionError as exc:
                skipped.append(f"{path.name}（叶子 {leaf[:8]}）：{exc}")
                continue
            messages = [e for e in chain if e.get("type") == "message"]
            if not messages:
                continue
            title = next(
                (
                    str(e.get("content", ""))
                    for e in messages
                    if e.get("role") == "user"
                ),
                "",
            )
            item = ResumableItem(
                path=path,
                leaf_id=leaf,
                timestamp=str(chain[-1].get("timestamp", "")),
                messages=len(messages),
                title=title,
                fork_at=_fork_point_time(chain),
            )
            sortable.append(((item.timestamp, order, path.name), item))
    sortable.sort(reverse=True)
    return [item for _, item in sortable], skipped


def latest_session_path(cwd: Path, *, base_dir: Path | None = None) -> Path | None:
    """本项目目录下最近活动的会话文件（--continue 用）。没有则返回 None。"""
    base = base_dir if base_dir is not None else _default_base_dir()
    directory = base / project_key(cwd)
    if not directory.is_dir():
        return None
    files = list(directory.glob("*.jsonl"))
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, p.name))


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_id: str | None = None

    @classmethod
    def start(
        cls,
        cwd: Path,
        *,
        base_dir: Path | None = None,
        directory_name: str | None = None,
    ) -> "SessionStore":
        """新建会话。

        `directory_name` 给评测设施用：工作区是临时目录、绝对路径很长，把整条路径编码
        进目录名会在 Windows 超过 260 字符；评测传入短案例名即可。生产路径不传，
        仍按项目路径编码（--continue/--resume 的目录约定不变）。
        """
        base = base_dir if base_dir is not None else _default_base_dir()
        if directory_name is None:
            directory = base / project_key(cwd)
        else:
            name = directory_name.strip()
            if (
                not name
                or name in {".", ".."}
                or any(ch in name for ch in ("/", "\\", ":"))
            ):
                raise ValueError(f"会话目录名不合法：{directory_name!r}")
            directory = base / name
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        store = cls(directory / f"{stamp}_{_new_id()[:8]}.jsonl")
        store.append("session", schema=SCHEMA, cwd=str(cwd), version=__version__)
        return store

    @classmethod
    def resume(cls, path: Path, *, leaf_id: str | None = None) -> "SessionStore":
        """在既有会话文件上继续：不新建、不改写，只把 id 链续上。

        leaf_id 给出时把活动分支切到它（--resume 选分支）；默认接文件末尾。
        """
        store = cls(path)
        if leaf_id is not None:
            store._last_id = leaf_id
            return store
        entries = load_entries(path)
        if entries:
            store._last_id = entries[-1]["id"]
        return store

    @property
    def leaf_id(self) -> str | None:
        """当前活动分支的叶子记录（后续记录挂在它下面）。"""
        return self._last_id

    def fork(self, entry_id: str) -> dict[str, Any]:
        """从历史记录处分岔：写一条 event/fork 标记挂在其下，后续记录写在新分支上。

        原分支的记录一字不动（append-only）；两条分支各自可 --continue。
        """
        if entry_id not in {entry.get("id") for entry in load_entries(self.path)}:
            raise SessionError(f"会话里没有记录 {entry_id}，无法分叉")
        self._last_id = entry_id
        return self.append("event", kind="fork")

    def append(self, type_: str, **fields: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "type": type_,
            "id": _new_id(),
            "parentId": self._last_id,
            "timestamp": _now_iso(),
            **fields,
        }
        line = _escape_line_breakers(
            json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        )
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        self._last_id = entry["id"]
        return entry
