# 23: （Stretch，砍单第一位）MCP stdio 最小客户端

**What to build:** 让 codelotte 能"插外设"：实现最小 MCP（Model Context Protocol）客户端——连接一个 stdio 型 MCP server（启动子进程、走 JSON-RPC 握手）、列出它提供的工具、把这些工具并入 codelotte 的工具集供模型调用。纪律：MCP 工具与内置工具走同一个权限层与沙箱约束（不得成为绕过安全的旁路）；连接失败/断连有可读错误与测试。

🗣 大白话：MCP 是 2026 年 agent 行业的标准"外设接口"——本票给 codelotte 装上这个接口的最小闭环。它是 Stretch：时间不够时第一个砍（面试考点用设计文档覆盖即可），有余力再做。

**Blocked by:** 04（write / edit / bash 工具 + 本地执行器）

**Status:** ready-for-agent（可延后；砍单第一位）

- [ ] 可连接一个公开的 stdio MCP server 并列出其工具清单
- [ ] MCP 工具经权限层判定与沙箱执行（有测试证明不可绕过）
- [ ] 至少一条端到端用例：借助一个真实 MCP server 完成一次工具调用任务
- [ ] 连接失败/中途断连的处理与测试
