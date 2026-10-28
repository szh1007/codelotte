# 07: MCP 运行时 UX

**What to build:** `/mcp` 查看 server 状态、工具数、错误与重连；`tools/list_changed` 在 run 边界刷新工具集合并写 `event/mcpToolsChanged`，run 中途不改；启动/刷新失败可见但不阻塞；HTML 导出标记 MCP 工具调用。

🗣 大白话：`/mcp` 能看每个外部工具服务的连接状态；运行中工具列表变了，下一轮才生效，不会在同一轮里偷偷换工具。

**Blocked by:** 05、06

**Status:** ready-for-agent

- [ ] `/mcp` 状态输出（连接中/失败/工具数/错误摘要）
- [ ] `list_changed` → run 边界刷新 + event；禁止 run 中途变更
- [ ] 重连/超时/取消路径
- [ ] 导出标记 MCP 工具（server/tool）
- [ ] 测试：`list_changed`、状态输出、失败降级、导出
- [ ] 文档：README/SECURITY
