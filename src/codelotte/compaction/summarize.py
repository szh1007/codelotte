"""压缩摘要模板与压缩后的上下文装配（票据 12）。

摘要由同一模型生成（self-summarize），固定七项结构；硬约束不交给摘要器，而是
作为独立文本重注入——防止摘要过程把"不许做什么"润色掉。

## 一次压缩 = 两次模型请求

- **① 摘要请求**（`tools=None`）：`被压缩前缀 + user(七项摘要指令)`。模型只输出摘要；
  摘要文本**不落 assistant 消息**，这次调用只落一条 usage 记录。
- **② 压缩后正常请求**（tools 正常）：`system(摘要 + 硬约束) + (user 桥) + 保留段`。
  保留段以 assistant 开头时才补 user 桥；以 user 开头则不补，避免连续两条 user。

## 三种典型场景（消息数组）

阈值来自 settings.json 的 `compactionSoftThreshold` / `compactionHardThreshold`
（比例 0.2–0.9，且 hard - soft ≥ 0.2；默认 0.60 / 0.85）。

### 1. 软触发 @ 新用户消息（默认 60% + 最新边界是刚输入的 user）

```text
① 摘要请求: [旧 task 的历史..., user(七项摘要指令)]
② 正常请求: [system(摘要+硬约束), user(新任务)]
```

保留段以 user 开头，不加桥；旧历史只进摘要请求，不再进正常请求。

### 2. 硬触发 @ 工具链中间（默认 85%，最近一个 turn 以 assistant 开头）

```text
① 摘要请求: [该 turn 之前的历史..., user(七项摘要指令)]
② 正常请求: [system(摘要+硬约束), user(桥), assistant(工具调用), tool(结果)]
```

最小保留集 = run 的最后一个 turn；这个 turn 的 assistant/tool 链原样保留。
注意 run / turn 两级：一个 run（`AgentLoop.run`）可含多个 turn（一次 assistant 回复 + 工具链）。

### 3. 软触发 @ git commit（默认 60% + 最新边界是声明 commit 的 assistant）

```text
① 摘要请求: [commit 之前的历史..., user(七项摘要指令)]
② 正常请求: [system(摘要+硬约束), user(桥), assistant(声明 commit), tool(commit 结果), ...后续记录]
```

commit 切点取"声明这次调用的 assistant"（最近的协议安全切点）；这一轮 commit 保留，
不切半条工具链。若 commit 之后又有新的 user 消息，最新 user 边界优先。
"""

from __future__ import annotations

from typing import Any, Literal

from codelotte.guardrails import HARD_CONSTRAINTS

SummaryTemplate = Literal["seven", "compact"]

SUMMARY_SECTIONS = (
    "任务目标",
    "已完成事项",
    "关键决策及其理由",
    "活跃约束",
    "涉及文件清单",
    "当前未解决问题",
    "下一步",
)

COMPACT_SUMMARY_SECTIONS = (
    "任务目标",
    "已完成事项",
    "活跃约束",
)

_SUMMARY_REQUIREMENTS = (
    "要求：只输出摘要正文；不要调用工具；保留具体的文件路径、命令、错误信息与未完成事项；"
    "不要编造对话里没有的事实；活跃约束要逐条保留。"
)


def _instruction(title: str, sections: tuple[str, ...]) -> str:
    numbered = "\n".join(
        f"{index}. {section}" for index, section in enumerate(sections, 1)
    )
    count = {3: "三个", 7: "七个"}.get(len(sections), f"{len(sections)} 个")
    return (
        f"请把上面的对话压缩成一份{title}，"
        f"严格使用以下{count}标题（不要增删、不要改写标题）：\n"
        + numbered
        + "\n\n"
        + _SUMMARY_REQUIREMENTS
    )


SUMMARY_INSTRUCTION = _instruction("结构化摘要", SUMMARY_SECTIONS)
COMPACT_SUMMARY_INSTRUCTION = _instruction("简短摘要", COMPACT_SUMMARY_SECTIONS)


def summary_instruction(template: SummaryTemplate = "seven") -> str:
    """摘要请求的指令文本；compact 模板只保留目标/已完成/约束三节。"""
    if template == "compact":
        return COMPACT_SUMMARY_INSTRUCTION
    return SUMMARY_INSTRUCTION


# 与摘要分开存放、分开重注入（摘要是模型生成的，这段不是）
COMPACTION_CONSTRAINTS = (
    "压缩后的上下文仍必须遵守以下硬约束（独立于摘要，不得被摘要改写）：\n"
    + HARD_CONSTRAINTS
)


def build_summary_messages(
    prefix_messages: list[dict[str, Any]], *, template: SummaryTemplate = "seven"
) -> list[dict[str, Any]]:
    """摘要请求：被压缩的历史 + 最后一条摘要指令。

    不额外加 system 开头：历史本身可能已经以 system 摘要开头（多次压缩），
    再叠一个 system 会被部分 OpenAI 兼容后端拒绝。最后追加 user 指令最稳。
    `template` 是 E1 的实验变量（seven / compact）。
    """
    return [
        *prefix_messages,
        {"role": "user", "content": summary_instruction(template)},
    ]


def build_compaction_messages(
    summary: str, constraints: str, kept_messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """压缩后的请求上下文：一条 system（摘要 + 独立硬约束）+ 保留的最近记录。

    保留段以 assistant 开头时补一条 user 桥，保证请求从 user 开始（部分后端要求
    第一条非 system 消息是 user）；保留段以 user 开头则不补，避免连续两条 user。
    """
    system = (
        "以下是对之前对话的压缩摘要（原始记录仍在会话文件中，可按需回查）：\n\n"
        f"{summary}\n\n"
        "【硬约束（独立于摘要，继续有效）】\n"
        f"{constraints}"
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    if not kept_messages or kept_messages[0].get("role") != "user":
        messages.append(
            {"role": "user", "content": "请基于以上摘要与最近记录继续完成当前任务。"}
        )
    messages.extend(kept_messages)
    return messages
