# 08: 任务队列（lab 06）

**What to build:** 把 02 的 PostgreSQL 轮询占位换成 Kafka `run.jobs`，按 `session_id` 分区，
worker 消费执行。保留两代错误版本作为实验对照：

| 版本 | 实现 | 缺陷 |
|---|---|---|
| A | Redis List `LPUSH` / `BRPOP` | 消费者崩溃即丢任务，没有 ack |
| B | Redis Streams + consumer group + `XACK` | 有 ack，但 pending 堆积无告警、不可重放、受内存限制 |
| 正确 | Kafka + 手动提交位点 + 重试 topic + DLQ | 可重放、lag 可观测、失败可控 |

分区键必须是 `session_id`：同一会话的 run 有先后，必须落在同一分区。这一条单独做实验——
去掉分区键后构造两个 run 并发提交，观察会话树分叉或工具调用乱序。

🗣 大白话：队列能跑起来不难，难的是「消费者崩了任务去哪了」。三个版本就是三种答案。

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] `serve/queue/producer.py`：Job 序列化（含 `job_id` / `session_id` / `user_id` / `run` 参数）
- [ ] `serve/queue/consumer.py`：手动提交位点；处理成功才 commit
- [ ] 分区键 `session_id`；topic 与分区数见 SPEC
- [ ] worker 从 Kafka 取任务，替换 02 的轮询实现
- [ ] `labs/06-queue-selection/`：List / Streams / Kafka 三版 + 崩溃注入脚本
- [ ] `results.json`：崩溃后丢失任务数（A）、pending 堆积数（B）、重投递与接管时间（Kafka）
- [ ] 顺序实验：去掉分区键 vs 使用分区键，乱序次数对比
- [ ] 测试：`kill -9` worker 后，未提交的 Job 被另一 worker 接管并完成，恰好执行一次
