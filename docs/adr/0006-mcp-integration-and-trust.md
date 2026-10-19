# MCP：外部工具适配与项目信任

Status: accepted (2026-10-20)

MCP 作为 codelotte 的外部工具来源，而不是内建进 minimal core：

- 协议面只做 tools：`initialize` / `tools/list` / `tools/call` / `tools/list_changed`；resources / prompts / sampling / elicitation 不做，非文本结果转占位文本。
- 传输只做 stdio 与 Streamable HTTP；旧版 HTTP+SSE 明确报错；OAuth 不做，HTTP 认证用静态 headers + `${VAR}` 展开。
- 客户端使用官方 Python `mcp` SDK，不自研 JSON-RPC 与传输层。
- 配置：`~/.codelotte/mcp.json` 与项目 `.codelotte/mcp.json`，使用 Claude Desktop 兼容的 `mcpServers`；同名项目覆盖用户级。
- 信任：用户级配置视为已信任；项目级配置是「可执行代码」，首次加载必须确认，内容变化后重新确认；stdio server 在宿主机运行。
- 工具名 `mcp__<server>__<tool>`；超过 provider 的 64 字符限制时截断并加短 hash；只做 direct exposure。
- 生命周期：启动时并发连接并 `tools/list`，单 server 超时 10s、失败不阻塞会话；退出统一 kill；`list_changed` 只在 run 边界刷新。
- 权限：所有 MCP 工具默认 ask；可按 server 配置 allow；审批弹层显示 server 名。

理由：

- minimal core 的边界是「内建四工具 + 协议/扩展组装」，MCP 是扩展入口。
- context7、firecrawl 这类目标 server 都是 tools-only，stdio 或远程 HTTP；先把这条主路径做对。
- 手写 stdio framing 与 Streamable HTTP 会话成本高、错误面大，且不增加面试价值；自研 adapter 的价值已经由 `openai-completions` 承担。
- 项目级 mcp.json 能定义任意 command，等价于克隆仓库即可在宿主机执行代码；信任提示是这条链的安全边界。
- stdio 在宿主机运行而不是容器内：容器内需要额外注入 server 包与配置，且 server 往往需要宿主凭据；宿主运行 + 权限层 + 显式信任是更简单可控的组合。

被否备选：

- 自研完整 MCP 客户端（协议细节多、易错）。
- 只支持 stdio（漏掉 context7 等远程 server）。
- 直接信任项目 mcp.json（供应链风险）。
- 把 stdio server 放进 Docker（配置与凭据注入复杂）。
- codemode / deferred / hidden exposure（0.2.0 用不到）。

后果：

- MCP server 是宿主机进程，拥有当前用户权限；文档必须明确「trust 是启动边界，权限层只管工具调用」。
- MCP 工具描述来自外部，属于不可信输入；审批弹层必须显示 server 名，工具结果的注入风险由现有防御层继续覆盖。
