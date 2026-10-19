# 06: MCP core（配置、信任、工具接入）

**What to build:** 接入官方 Python `mcp` SDK。配置 loader：`~/.codelotte/mcp.json` + 项目 `.codelotte/mcp.json`，`mcpServers`，`${VAR}` / `${VAR:-default}`；坏 JSON/坏条目跳过并汇报。项目级配置需 trust，内容 hash 变化后重新确认。启动时并发连接，stdio 与 Streamable HTTP，10s 超时，失败不阻塞；退出 kill。工具名 `mcp__<server>__<tool>`，sanitize、64 字符截断 + 短 hash。只做 direct exposure；默认 ask；按 server allow。结果映射：文本 / structuredContent；非文本转占位。错误作为 tool result 回模型；审计记录 server/tool。

🗣 大白话：能接 context7、firecrawl 这类 MCP 工具；陌生仓库的 MCP 配置先问你再启动；所有外部工具默认要审批。

**Blocked by:** 03、04

**Status:** ready-for-agent

- [ ] 配置 loader + trust 门控 + 变更重确认 + `${VAR}`
- [ ] SDK client：stdio / Streamable HTTP；initialize、list、call；超时、取消、退出清理
- [ ] 工具适配器：命名、schema 转换、结果映射、错误回传
- [ ] 权限集成：默认 ask、server allow、审批显示 server
- [ ] 伪造 stdio server + 本地 HTTP server 的集成测试（不依赖外网）
- [ ] 配置/信任/命名/权限/清理测试
- [ ] 文档：SECURITY 的「MCP server 在宿主运行」说明
