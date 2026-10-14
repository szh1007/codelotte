"""上下文装配：会话记录 → 发给模型的消息数组（--continue 的恢复路径，SPEC §E）。

装配是确定性的：同一份文件装配两次逐字节一致（键序固定、无时间戳混入）。
规则：
- 只有 message / tool_call / tool_result 进入上下文；usage、event、session 跳过。
- assistant 的 toolCalls 用存储时的原始 arguments 文本回传——回传雷区与前缀缓存都要求逐字节一致。
- stopReason=interrupted 的 assistant 记录跳过：原进程里它从未进入 messages（流中断后直接结束回合），
  重建时必须保持同样的视图，否则模型会看到一段它"没说过的尾话"。
- assistant 声明了 toolCalls、但某个调用没有落盘的 tool_result（回合在工具执行中被中断）：
  补一条说明中断的 tool 消息——协议要求每个 tool_call 都有对应的 tool 消息，缺一个整个请求 400。
"""

from __future__ import annotations

from typing import Any

from codelotte.providers.base import assistant_message

# 中断的工具调用在上下文里的应答文本（loop 的实时占位、TUI 的块收尾、本模块的重建兼容共用）
INTERRUPTED_TOOL_NOTE = "（回合被中断，这个工具调用没有返回结果）"


def messages_from_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按记录顺序重建消息数组（与运行中逐条 append 的结果一致，见票据 05 恢复语义）。"""
    messages: list[dict[str, Any]] = []
    pending: list[str] = []  # 最近一个 assistant 声明的、还没见到结果的 toolCallId

    def flush_pending() -> None:
        for call_id in pending:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": INTERRUPTED_TOOL_NOTE,
                }
            )
        pending.clear()

    for entry in entries:
        kind = entry.get("type")
        if kind == "message":
            flush_pending()  # 工具消息必须紧跟声明它的 assistant 消息（协议要求）
            role = entry.get("role")
            if role == "assistant":
                if entry.get("stopReason") == "interrupted":
                    continue
                calls = entry.get("toolCalls")
                messages.append(
                    assistant_message(
                        content=entry.get("content", ""),
                        reasoning=entry.get("reasoningContent"),
                        tool_calls=(
                            [
                                (call["id"], call["name"], call["arguments"])
                                for call in calls
                            ]
                            if calls
                            else None
                        ),
                    )
                )
                if calls:
                    pending.extend(call["id"] for call in calls)
            elif role == "user":
                messages.append({"role": "user", "content": entry.get("content", "")})
        elif kind == "tool_result":
            call_id = entry.get("toolCallId")
            if call_id in pending:  # 没有对应声明的孤儿结果跳过——进上下文会让请求非法
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": entry.get("content", ""),
                    }
                )
                pending.remove(call_id)
    flush_pending()
    return messages
