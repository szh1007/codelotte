# 数据所有权：配额以 Redis 为主存，Session entries 留在 JSONL

Status: accepted (2026-10-28)

服务化后每个可变对象都必须回答「谁是权威」。本决策规定如下：

| 对象 | 权威 | 副本 / 归档 | 一致性 |
|---|---|---|---|
| 用户配额余额 | **Redis**（原子扣减） | PostgreSQL `quota_ledger` 流水，定时对账 | 强（不能超支） |
| API Key | **PostgreSQL** | Redis 缓存，吊销时删除 | 强（吊销要立即生效） |
| Session entries | **JSONL 文件**（append-only） | 无 | 不适用（不可变） |
| Session 元数据 / 汇总 | **PostgreSQL** | Redis 缓存，事件驱动失效 | 最终一致 |
| Job 状态 | **Redis** | PostgreSQL `jobs` 归档 | 最终一致 |
| 用量流水 | **PostgreSQL**（`request_id` 唯一） | Kafka 可重放重建 | 至少一次 + 幂等 |

理由：

- **配额不能超支，所以缓存不能做副本。** cache-aside（DB 权威 + 缓存副本）在「读—改—写」
  之间必然有窗口；高并发下这个窗口直接变成超支。让 Redis 当唯一计数器、DB 只记流水，
  用对账补差，才能既快又不超。
- **Session entries 没有更新窗口。** append-only 意味着任何前缀都可以按 `leaf_id` 寻址、
  结果不可变；放进 DB 换不到一致性收益，却会丢掉回放、导出、归因、评测共用的现有地基
  （ADR-0003）。
- **Job 状态高频读写且可容忍短暂不一致。** Redis 天然胜任；DB 只做归档供审计。

代价（写进 SPEC，且面试要讲）：

- 多 API 实例部署时，Session entries 所在目录**必须是共享卷**；docker-compose 用 named
  volume，生产环境需要对象存储或网络文件系统。
- Redis 不可用时，配额链路 **fail-closed**（拒绝新 run），限流链路 **fail-open**（放行）。
  两条链路策略相反，因为它们保护的东西不同：一个是钱，一个是可用性。
- 配额对账是异步的，窗口内 Redis 与 DB 流水可能对不上；对账任务负责发现并修正。

被否备选：

- **全部进 PostgreSQL**：改动最大，且配额热点仍要靠行锁或乐观重试，QPS 上不去。
- **纯 Redis 不做持久化**：账单无法对账，Redis 丢数据即丢钱。
- **Session entries 进 DB**：见 ADR-0003 的反向论证；本次明确不做，留待将来若有跨实例
  共享存储需求时另立 ADR。
