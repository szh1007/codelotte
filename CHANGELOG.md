# CHANGELOG

所有值得一提的变更都记在这里；条目按版本倒序，与 `settings.json` 的
`lastChangelogVersion` 配合：启动时落后就提示，一致就不打扰。

## [0.1.0] - 2026-10-17

- 核心循环：流式对话、tool_calls 装配、工具执行与结果回填，会话落盘 JSONL（票据 01–04）
- 会话树：`--continue` / `--resume` / `--fork`，分支成树、前缀逐字节可缓存（票据 06）
- 成本记账：官方价目 + 峰谷时段判定 + 按模型/时段/缓存的分项账单（票据 07）
- 导出：会话转单文件自包含 HTML 或 Markdown（票据 08）
- 权限层：allow/ask/deny 规则、破坏性命令守门、四档审批、无头 fail-closed（票据 09）
- 沙箱：bash 默认在每会话一个 Docker 长驻容器里执行（只挂工作区、`--network none`、内存/CPU/PID/超时限额）；`--no-sandbox` 为显式逃生门（风险警告 + 执行记录 `env=local`）（票据 10）
- 配置：用户级 settings.json / models.json，无环境变量来源、无内置默认（SPEC §M）；思考开关与强度统一在模型条目的 `reasoning_effort`（none 关闭思考；开启时思考总是既落盘又展示）
