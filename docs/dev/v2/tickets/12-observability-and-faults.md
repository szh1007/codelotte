# 12: 可观测性与故障注入

**What to build:** 把 SPEC 里的指标全部打出来，并把五个故障场景写成可复现脚本，
每个脚本自带断言与观察输出。

| # | 注入 | 期望 |
|---|---|---|
| 1 | 停 Redis | 限流 fail-open；配额 fail-closed（503）；缓存降级直连 PG；锁 fail-closed（409） |
| 2 | 停 Kafka | 入队 503；消费停止；lag 不增长 |
| 3 | 停 PostgreSQL | 消费者重试 → DLQ；API 读路径降级 |
| 4 | `kill -9` worker | 未提交任务被接管，恰好执行一次 |
| 5 | 慢消费（sleep 注入） | lag 受控上升；背压生效 |

脚本放 `deploy/faults/`，统一形如 `faults/01-stop-redis.sh`，退出码 0 表示「行为符合预期」。
观察结果落 `docs/dev/v2/reports/faults.md`。

🗣 大白话：平时说「降级」「容错」都是嘴上的，这里让它们真的发生一次，并记录成证据。

**Blocked by:** 10, 11

**Status:** ready-for-agent

- [ ] 暴露 SPEC 中全部 metrics
- [ ] 结构化 JSON 日志，字段含 `request_id` / `user_id` / `session_id` / `job_id`
- [ ] 日志不含 prompt 正文与 API Key（测试断言）
- [ ] `deploy/faults/` 五个脚本，均可重复执行
- [ ] 每个脚本输出：注入动作、观察到的行为、是否符合期望
- [ ] `reports/faults.md`：五个场景的原始观察记录
- [ ] 测试：`pytest -m serve` 中断言日志不含敏感字段
