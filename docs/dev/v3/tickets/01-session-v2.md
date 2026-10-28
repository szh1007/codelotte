# 01: session/v2 与兼容读取

**What to build:** 把 Session schema 从 `session/v1` 升到 `session/v2`，给后续的 prompt 元数据、`skill` entry、model/effort/mcp/prompt event 留出版本空间。写入一律 v2；读取同时接受 v1 与 v2，读取器不新增 schema 校验。v1 会话可读、可导出、可 resume/fork；第一次追加 v2-only 内容前写一条 `event/schemaUpgraded`（`from=session/v1`、`to=session/v2`），header 不改写，回放忽略该 marker。**不迁移、不重写任何历史会话**：`evals/runs/**` 的历史会话保持原样，`evals/attribution/sessions/` 与 `evals/defense/sessions/` 的 22 个手写 fixture 也保持 v1。

🗣 大白话：换新账本格式，但旧账本继续能翻；已经归档的实验记录一个字都不动。

**Blocked by:** None

**Status:** ready-for-agent

- [ ] `src/codelotte/session/store.py`：`SCHEMA = "session/v2"`，新会话头写 v2
- [ ] `load_branch` / `open_at` / `resume` / `fork` / `list_resumable` 对 v1 与 v2 一视同仁（不校验 schema 值；缺 `schema` 的旧文件按 v1 处理）
- [ ] `tests/test_session.py` 断言改为 v2；新增一条 v1 文件仍可 resume/fork 的回归测试
- [ ] v1 会话首次写入 v2-only 内容前追加 `event/schemaUpgraded`（from v1, to v2）；header 不改写，回放忽略该 marker
- [ ] 读取器不得因 schema 值报错；v1 会话导出带 `v0.1.x` 标注
- [ ] `evals/runs/**`、`evals/attribution/sessions/**`、`evals/defense/sessions/**` 零改动
- [ ] 文档：ADR-0008 已记录；票据表状态更新
