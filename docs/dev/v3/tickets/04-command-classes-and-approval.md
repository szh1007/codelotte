# 04: 命令类匹配、路径作用域与审批弹层

**What to build:** bash 用 shell 词法分段（`;`、`&&`、`||`、`|`、换行、命令替换、反引号），每个 segment 取命令类（`argv[0]` + 非 flag 的 `argv[1]`），全部命中才放行；包装器（`sudo`/`env`/`sh -c`/`xargs`/`find -exec`）、重定向、无法解析的形态、危险 flag 一律 ask。文件工具的会话放行按工作区路径范围：`/workspace/...` → cwd、相对路径解析、symlink `resolve()`；越界 ask。MCP 工具按全名放行并在弹层显示 server。审批弹层五档：本次 / 本会话 / 始终 / 拒绝 / 手动输入建议；反馈 = 拒绝 + tool error + run 继续，且不计入连续失败熔断。批量 tool call 逐条审批。

🗣 大白话：允许 `git status` 不等于允许 `git push`；复合命令逐段检查；「换个做法」会告诉模型原因，而且不会把它算成模型失败。

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] 新增 shell 分段/命令类解析器（优先 `shlex`，失败则 ask）
- [ ] `git status` 放行不覆盖 `git push`；复合命令任一段未命中即 ask（参数化回归 ≥ 20 形态）
- [ ] 文件工具路径归一化与 symlink resolve；工作区外仍 ask
- [ ] 审批弹层五档 + 输入框；显示命令类/路径范围/server 名；Esc=拒绝
- [ ] feedback 语义与熔断豁免；普通 deny 仍计数
- [ ] 批量逐条审批；session 匹配后自动通过
- [ ] 测试：命令矩阵、路径越界、symlink、反馈、TUI 快照
- [ ] 文档：SECURITY/README 的审批说明更新
