# 11: 事件总线与异步汇总

**What to build:** worker 在 run 结束后把用量与审计事件发到 Kafka；独立消费者把它们落库：

- `run.usage`（键 `user_id`）→ 写 `usage_events`（幂等）→ 累加 `usage_daily`
- `run.audit`（键 `session_id`）→ 写审计表（本票新增 `session_events` 或直接落 JSONL 归档，
  按实现成本选一个并在 README 说明）

会话汇总（`sessions.message_count` / `cost_cents`）由 `run.usage` 消费者更新，并**删缓存**
（06 的一致性策略在这里闭环）。

再提供一个**账单重放**命令：清空 `usage_daily` 后从 `run.usage` 的保留期数据重算，断言结果与
重放前一致。这是「Kafka 可重放」这条选型理由的实证。

🗣 大白话：把「记账」从主流程里剥出来异步做，并证明这份账可以重算——重算得出来，才叫账本。

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] `serve/events.py`：producer 把 `CostRecorded` 与审计事件分别发到两个 topic
- [ ] usage 消费者：幂等写 `usage_events` + `usage_daily` + 更新 `sessions` 汇总 + 删缓存
- [ ] audit 消费者：落库或归档（二选一，README 说明理由）
- [ ] `python -m codelotte.serve.replay --topic run.usage --since ...`：重算 `usage_daily`
- [ ] 测试：重放前后 `usage_daily` 完全一致
- [ ] 测试：同一 `request_id` 投递 5 次，`usage_events` 只有 1 行
- [ ] 测试：会话汇总更新后缓存被删，下一次读回源拿到新值
- [ ] `labs/` 中补一个重放实验，记录重放耗时与行数
