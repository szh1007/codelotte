"""codelotte serve：多用户 Agent 后端的运行层（ADR-0010）。

内核（AgentLoop / SessionStore / Ledger）不在这里重写——本包只决定「谁调用内核」与
「内核的事件发到哪里」。依赖是可选组：``uv sync --extra serve``；不装它时 CLI 行为不变。
"""
