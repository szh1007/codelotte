# 05: Slash Command 基础设施 + 核心命令

**What to build:** TUI 输入以 `/` 开头时由 codelotte 解析，不发给模型；未知命令报错；命令只在空闲时可用。实现 `/help`、`/model`、`/effort`、`/context`、`/clear`（别名 `/new`）、`/compact [指令]`、`/permissions`。`/model`、`/effort` 切换下一次 run 生效，写 `event/modelChanged` / `event/effortChanged`，resume/fork 重放最后一次；模型不存在时回退默认并告警；不写默认配置。`/context` 显示 provider 精确总数 + 分项估算（标 `est.`）+ 压缩阈值。`/clear` 新建会话文件，旧会话保留。`/compact` 即使低于阈值也强制压缩，可带关注点。

🗣 大白话：终端里终于有斜杠命令；切模型、看上下文、开新会话、手动压缩都不用退出重开。

**Blocked by:** 01、02、03

**Status:** ready-for-agent

- [ ] TUI slash parser（idle-only、未知报错、参数保留）
- [ ] `/help`、`/permissions` 输出规则与来源
- [ ] `/model` 选择器/参数；client 与 loop 模型切换；event + 重放 + 回退告警
- [ ] `/effort` 接受完整枚举（none…ultra）；event + 重放
- [ ] `/context`：精确总数 + `est.` 分项 + 阈值
- [ ] `/clear` + `/new`：新 session、清历史/ledger、旧文件保留
- [ ] `/compact`：强制压缩 + 可选指令 + 记录 manual
- [ ] 测试：解析、每个命令、resume 重放、`/clear` 切换、`/compact` 强制
- [ ] 文档：README 命令表
