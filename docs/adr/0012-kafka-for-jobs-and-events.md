# 消息队列：Kafka 同时承担 Job 队列与事件总线

Status: accepted (2026-10-28)

Topic 设计：

| Topic | 分区键 | 用途 |
|---|---|---|
| `run.jobs` | `session_id` | Job 分发；同一会话的 run 有序 |
| `run.jobs.retry` | `session_id` | 退避重试 |
| `run.usage` | `user_id` | 逐次调用用量，聚合计费 |
| `run.audit` | `session_id` | 工具调用 / 审批 / 压缩 / 防御事件 |
| `run.dlq` | `session_id` | 超过重试上限的死信 |

语义：位点**手动提交**，处理成功后才提交；失败按退避重试 N 次后进 DLQ；消费端按
`request_id` 幂等写库（`INSERT ... ON CONFLICT DO NOTHING`）。

为什么 Kafka 而不是 Redis Streams / RabbitMQ：

- **可重放**：账单要能用保留期内的事件重算，这是 Kafka 独有的能力，也是「Kafka 不只是队列」
  的实证。
- **分区保序**：按 `session_id` 分区天然满足「同一会话的 run 有先后」。
- **削峰**：大量消息堆积不阻塞生产端，lag 可观测、可配告警。
- **一套基础设施**承载任务与事件，运维面小。

代价（必须能讲清楚）：

- Kafka **没有 per-message ack 与优先级**，任务队列语义要靠「手动提交 + 幂等 + DLQ」自己补。
- 消费者数**不能超过分区数**，扩容有天花板；这是面试常问的坑。
- 消费者组 rebalance 期间有短暂停顿，长任务需要心跳与续租。

被否备选：

- **Redis List（`LPUSH` / `BRPOP`）**：消费者崩溃即丢任务，没有 ack。保留为实验中的错误版本 1。
- **Redis Streams（consumer group + `XACK`）**：有 ack 与 pending list，但不可重放、受内存
  限制。保留为实验中的错误版本 2。
- **RabbitMQ**：任务队列语义最完整（ack / 优先级 / DLX），但不可重放，且要多维护一套中间件。
  取舍是「任务队列能力」换「可重放 + 少一套基础设施」。
