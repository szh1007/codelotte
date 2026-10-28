# 03: 权限模型 v2（决策、优先级、会话规则）

**What to build:** 权限层增加 `feedback` 决策；优先级改为 **deny > 显式批准 > ask > allow > 默认 ask**；显式批准 = 同 subject 的 session/always 规则。修复 always 持久化未转义 glob 元字符的 bug。会话规则在 resume/fork 时从 `permission` 记录中 `decision=session` 重放。always 继续写用户级 `~/.codelotte/permissions.json`，弹层显示精确规则；不写项目文件。

🗣 大白话：你点了「始终允许」，以后就真的不再问；但「永远不行」仍然最大。关掉终端再回来，「本会话允许」也还认。

**Blocked by:** None

**Status:** ready-for-agent

- [ ] `permissions.py`：新增 `DECISION_FEEDBACK`；决策常量与审计字段完整
- [ ] `evaluate`：deny 最高；同 subject 的显式批准覆盖 ask；ask 覆盖 allow；无规则 ask
- [ ] `apply_decision`：always 持久化使用与 session 相同的转义逻辑（`*?[` 回归测试）
- [ ] 会话规则重放：resume/fork 时扫描活动分支的 `permission` entry，重建 `decision=session` 的 allow 规则
- [ ] always 仍写用户级；写入前展示规则文本与文件路径；写失败降级为 session 并通知
- [ ] 审计：`decision=feedback`、`allowed=false`、反馈文本进入 tool error
- [ ] 测试：优先级矩阵、跨来源 deny、转义、重放、always 写用户级
- [ ] 文档：SECURITY 与权限章节更新
