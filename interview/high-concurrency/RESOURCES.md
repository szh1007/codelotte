# 高并发后端中间件面试 Resources

> 原则：原理以官方文档、DDIA、Google SRE、AWS Builders' Library 为准；中文博客只用来找场景和面经，不用来当唯一依据。

## Knowledge

### Redis

- [Redis Docs: Cache-aside](https://redis.io/docs/latest/develop/use-cases/cache-aside/)
  Redis 官方对 cache-aside 的定义、TTL、失效和击穿防护。用于：缓存模式、缓存一致性、面试开场。
- [Redis Docs: Persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
  RDB / AOF / 混合持久化、fsync 策略、Redis 7 multi-part AOF。用于：RPO/RTO、持久化选型。
- [Redis Docs: Replication](https://redis.io/docs/latest/operate/oss_and_stack/management/replication/)
  主从复制、全量/部分重同步、replication backlog。用于：主从延迟、故障切换。
- [Redis Docs: Distributed Locks](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)
  SET NX PX、Lua 解锁、Redlock 算法与争议。用于：分布式锁、原子性、面试追问。
- [Redis Docs: Data types](https://redis.io/docs/latest/develop/data-types/)
  String / Hash / List / Set / ZSet / Bitmap / HyperLogLog / Stream 的语义与命令。用于：结构选型。
- [Redis Docs: Eviction](https://redis.io/docs/latest/develop/reference/eviction/)
  maxmemory 与 LRU/LFU/volatile 淘汰策略。用于：内存满、热 key、缓存命中率。
- [Redis Docs: Cluster scaling](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)
  16384 slots、resharding、MOVED/ASK。用于：Cluster 扩容与多 key 限制。

### Kafka / MQ

- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
  Kafka 官方文档总入口。用于：概念、配置、运维命令。
- [Apache Kafka Design](https://kafka.apache.org/43/design/design/)
  官方设计文档：日志、分区、复制、投递语义、消费者。用于：Kafka 为什么快、可靠性。
- [Confluent: Message Delivery Guarantees](https://docs.confluent.io/kafka/design/delivery-semantics.html)
  at-most-once / at-least-once / exactly-once 的官方说明。用于：投递语义、幂等。
- [RabbitMQ: Consumer Acknowledgements and Publisher Confirms](https://www.rabbitmq.com/docs/confirms)
  RabbitMQ 的确认机制。用于：RabbitMQ 不丢消息、与 Kafka 对比。
- [RabbitMQ: Dead Letter Exchanges](https://www.rabbitmq.com/docs/dlx)
  TTL + DLX 做延迟队列和死信。用于：订单超时、失败重试。
- [Apache RocketMQ Docs](https://rocketmq.apache.org/docs/)
  事务消息、延迟消息、顺序消息。用于：RocketMQ 选型与电商场景。
- [microservices.io: Transactional Outbox](https://microservices.io/patterns/data/transactional-outbox.html)
  Outbox 模式。用于：双写一致性、异步事件、分布式事务。

### 分布式系统与稳定性

- [Book: _Designing Data-Intensive Applications_ (2nd ed.) — Martin Kleppmann & Chris Riccomini](https://www.oreilly.com/library/view/designing-data-intensive-applications/9781098119058/)
  第 5/6 章复制与分区、第 11 章流处理。用于：所有“为什么这样设计”的底层依据。
- [Google SRE Book: Handling Overload](https://sre.google/sre-book/handling-overload/)
  过载、客户端限流、负载丢弃。用于：限流、降级、容量。
- [Google SRE Book: Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)
  级联故障、队列管理、load shedding。用于：雪崩、熔断、隔离。
- [AWS Builders' Library: Timeouts, Retries, and Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
  超时、重试、指数退避、jitter。用于：重试风暴、超时设置。
- [AWS Builders' Library: Making Retries Safe with Idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)
  幂等 API 与重试安全。用于：重复消费、幂等设计。
- [Martin Kleppmann: How to do Distributed Locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)
  对 Redlock 的经典批评：时钟、GC 暂停、fencing token。用于：分布式锁追问。
- [antirez: Is Redlock Safe?](https://antirez.com/news/101)
  Redis 作者对上述批评的回应。用于：展示你听过双方观点。

### 中文场景与行业实践

- [阿里云: 打造高性能秒杀系统：技术深析与实践](https://help.aliyun.com/zh/document_detail/2860128.html)
  秒杀分层、Redis、数据库冲突处理。用于：秒杀场景的工程细节。
- [Thoughtworks: 秒杀系统架构解析：应对高并发的艺术](https://www.thoughtworks.com/zh-cn/insights/blog/evolutionary-architecture/design-of-high-concurrency)
  秒杀设计套路与权衡。用于：场景开场和取舍。
- [美团技术团队](https://tech.meituan.com/)
  高并发、缓存、订单、稳定性实践。用于：找真实业务场景；具体文章按关键词搜索。

### Python 客户端

- [redis-py Documentation](https://redis.readthedocs.io/)
  Python Redis 客户端。用于：锁、Lua、Pipeline 示例。
- [Confluent Kafka Python Client](https://docs.confluent.io/kafka-clients/python/current/overview.html)
  Python Kafka 生产者/消费者。用于：实验课和项目映射。
- [aiokafka Documentation](https://aiokafka.readthedocs.io/)
  asyncio 版 Kafka 客户端。用于：AI/Agent 后端的异步消费。
- [FastAPI: Async](https://fastapi.tiangolo.com/async/)
  Python 异步 Web 的官方说明。用于：把高并发映射到 FastAPI/uvicorn。

## Wisdom (Communities)

- [牛客网讨论区](https://www.nowcoder.com/discuss)
  中文面经密度最高。用于：收集真实追问、验证你的答案是否被继续追问；不把面经当原理来源。
- [V2EX](https://www.v2ex.com/)
  程序员社区。用于：发帖求 critique、看真实故障讨论。
- [Hacker News](https://news.ycombinator.com/)
  英文技术讨论。用于：Kafka/Redis 设计取舍、事故复盘的一手讨论。
- [r/ExperiencedDevs](https://www.reddit.com/r/ExperiencedDevs/)
  有经验的工程师社区。用于：系统设计答案的 peer review。

## Gaps

- 你目前没有生产流量、真实故障和压测数据；需要用本地实验（Docker + Python）补“我跑过”的证据。
- 中文面试向的“标准答案”质量参差，很多只给结论不给取舍；本课程以官方文档和 DDIA 为主，中文博客只做场景补充。
- AI/Agent 后端的高并发公开案例很少；需要自己设计并明确标注“设计”而非“生产经验”。
