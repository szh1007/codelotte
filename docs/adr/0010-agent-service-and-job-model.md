# Agent 服务化：新增 serve 入口，run 一律走异步 job 模型

Status: accepted (2026-10-28)

codelotte 从「本地 CLI」扩展出第三种运行形态 `codelotte serve`：FastAPI 多 worker 接 HTTP，
run 不在请求里同步执行，而是提交成 **Job** 入队，由独立 worker 消费执行，客户端用 SSE 订阅
事件流。

理由：

- CLI 是单人单机，不存在并发。要让缓存一致性、限流、削峰这些问题**真实发生**，必须有一个
  多用户、多实例的执行面。
- run 持续 10–60 秒，同步执行会把连接与进程一起占死，QPS 被 worker 数锁死。
- 异步 job 把「接收」与「执行」解耦，两侧可以独立扩容——这是削峰与背压能成立的前提。

边界：

- **内核不改。** `AgentLoop` / `SessionStore` / `Ledger` / 工具 / 权限 / 沙箱的行为不变；
  serve 只改变「谁调用」与「事件往哪发」。
- CLI 保持零中间件依赖：Redis / Kafka / PostgreSQL 走 `serve` 可选依赖组。
- **Job 不替代 Run。** 一个 Job 恰好执行一次 Run；Job 是调度单元，Run 是执行单元。

被否备选：

- **同步 + SSE**：实现最简单，但长任务占死 worker，无法独立扩容，削峰无从谈起。
- **CLI 内置 asyncio 并发**：没有跨进程协调，限流、锁、配额无处落地，多实例部署时直接失效。
- **引入 Celery / RQ 等任务框架**：能把队列跑起来，但队列语义被框架封装，练不到位点提交、
  分区顺序、rebalance、DLQ 这些真正被追问的东西。
