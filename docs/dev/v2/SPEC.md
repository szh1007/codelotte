# codelotte v0.2.0 技术规格（SPEC）：服务化与中间件

> 状态：ready-for-agent ｜ 日期：2026-10-28
> 对应票据：[tickets/](tickets/README.md) 01–15
> 设计依据：[ADR-0010](../../adr/0010-agent-service-and-job-model.md) – [ADR-0012](../../adr/0012-kafka-for-jobs-and-events.md)
> 术语：[CONTEXT.md](../../../CONTEXT.md)；v0.1.x 归档在 [../v1/](../v1/README.md)，v0.3.0（MCP/Skill）在 [../v3/](../v3/README.md)
> 本文描述 v0.2.0 的行为与接口契约；实现顺序与交付节奏见 [PLAN.md](PLAN.md)。

## Problem Statement（问题陈述）

codelotte v0.1.1 是一个可测量的 minimal-core 本地 CLI：四工具、append-only 会话树、双触发压缩、
权限层 + Docker 沙箱、死循环防御、完整评测闭环。它的问题不在功能，而在**运行形态**：

- **没有并发面。** 单人单机、一次一个 run。缓存一致性、限流、削峰这些问题在这个形态里
  根本不会发生，也就无从验证。
- **没有故障面。** 中间件一个都没有，进程崩了就是崩了，没有「谁接管、谁重试、谁补偿」。
- **没有水平扩展的余地。** 状态在本地文件和进程内存里，起第二个实例只会打架。

v0.2.0 要解决的是：**在不改动内核的前提下，造出一个真实的多用户并发执行面**，并在这个面上
落地 Redis（缓存 / 限流 / 配额 / 锁）、Kafka（任务队列 / 事件总线）、PostgreSQL（持久化与对账），
每一项都带可复现的对比实验。

## Solution（解决方案）

新增第三种运行形态 **`codelotte serve`**：

1. **API 层**：FastAPI + uvicorn 多 worker；鉴权、限流、配额预检、Job 入队、SSE 事件流。
2. **Worker 层**：独立进程消费 Kafka，执行现有 `AgentLoop`，把用量与审计事件发回事件总线。
3. **Redis**：用户限流（令牌桶 Lua）、日配额（原子扣减）、会话锁（fencing）、Job 状态、
   API Key 缓存、会话元数据缓存、热上下文缓存。
4. **Kafka**：`run.jobs` 任务分发、`run.usage` 计费事件、`run.audit` 审计事件、
   `run.jobs.retry` 退避重试、`run.dlq` 死信。
5. **PostgreSQL**：7 张表承载用户、密钥、配额流水、会话元数据、Job 归档、用量流水与日聚合。
6. **实验层**：8 个 lab，每个都保留「错误版本 → 正确版本」的代码与数据对比。
7. **客户端**：远程 CLI（复用现有 presenter）与单页 HTML（`EventSource`），不新增 UI 体系。

**内核零改动**是硬约束：`AgentLoop`、`SessionStore`、`Ledger`、四个工具、权限层、沙箱层
的行为与接口不变。CLI 仍然零中间件依赖。

## User Stories（用户故事）

1. 作为 API 调用者，我希望提交一次 run 立即拿到 `job_id`，以便不用挂着一个长连接等几十秒。
2. 作为 API 调用者，我希望用 SSE 订阅事件流，以便看到工具调用与思考过程的实时增量。
3. 作为 API 调用者，我希望重复提交同一个 `Idempotency-Key` 只产生一个 Job，以便网络重试不会重复扣费。
4. 作为 API 调用者，我希望超过速率上限时收到 429 和明确的 `Retry-After`，以便知道该退避多久。
5. 作为 API 调用者，我希望当日配额耗尽时收到 402 而不是 500，以便区分「没钱」和「坏了」。
6. 作为 API 调用者，我希望批量提交时能知道哪些被接受、哪些被拒绝，以便重试时只重发失败的部分。
7. 作为账号持有者，我希望吊销一个 API Key 后它立即失效，以便泄露时能马上止损。
8. 作为账号持有者，我希望一个账号可以有多个 Key，以便轮换时不需要停机。
9. 作为账号持有者，我希望看到当日用量与费用的聚合，以便知道钱花在哪。
10. 作为运维者，我希望 `/healthz` 与 `/readyz` 分开，以便区分「进程活着」和「依赖都通」。
11. 作为运维者，我希望 `/metrics` 暴露队列 lag、缓存命中率、429 数，以便在用户投诉前发现问题。
12. 作为运维者，我希望收到 SIGTERM 后 worker 停止拉新任务、把手上的 run 跑完，以便滚动发布不丢任务。
13. 作为运维者，我希望 Kafka 挂了时入队快速失败返回 503，而不是无限重试拖死请求。
14. 作为运维者，我希望 Redis 挂了时限流放行、配额拒绝，以便可用性与资金安全各按各的策略降级。
15. 作为运维者，我希望消费失败的 Job 进 DLQ 而不是无限重试，以便能事后人工处理。
16. 作为维护者，我希望同一个 `session_id` 的 run 严格有序，以便会话树不会分叉。
17. 作为维护者，我希望同一个 session 同时只有一个 run 在跑，以便 append-only 记录不被并发写坏。
18. 作为维护者，我希望消费端按 `request_id` 幂等，以便至少一次投递不会重复计费。
19. 作为维护者，我希望账单能用 Kafka 保留期内的 `run.usage` 事件重算，以便审计与对账。
20. 作为评审者，我希望每个中间件都有「错误版本 vs 正确版本」的数据对比，以便相信这些设计是验证过的而不是抄来的。
21. 作为面试官，我希望每个关键取舍都有 ADR 与故障矩阵，以便追问时有据可查。

## Implementation Decisions（实现决策）

### 服务形态与 API 契约

| 方法 | 路径 | 作用 | 成功 |
|---|---|---|---|
| POST | `/v1/runs` | 提交一次 run | 202 `{job_id, status, created_at}` |
| POST | `/v1/runs:batch` | 批量提交（≤ 500 条） | 202 `{accepted: [...], rejected: [{index, reason}]}` |
| GET | `/v1/runs/{job_id}` | 查询 Job 状态 | 200 `{job_id, status, attempts, error, timings}` |
| GET | `/v1/runs/{job_id}/events` | SSE 事件流 | `text/event-stream` |
| GET | `/healthz` | 进程存活 | 200 固定 |
| GET | `/readyz` | 依赖就绪（Redis/Kafka/PG） | 200 / 503 |
| GET | `/metrics` | Prometheus 文本 | 200 |

请求头：

- `Authorization: Bearer <api_key>` — 必填；缺失或无效一律 401，不区分「格式错」与「不存在」。
- `Idempotency-Key: <uuid>` — 可选；同一 user 下 24 小时内同 key 返回同一个 `job_id`。

请求体：

```json
{
  "prompt": "Fix the off-by-one bug in calc.py",
  "session_id": "可选；缺省则新建会话",
  "model": "可选；缺省用服务端默认",
  "allow": ["read", "edit", "bash(python check.py)"]
}
```

错误码：**401** 无效 Key；**402** 配额不足；**429** 限流；**503** 队列饱和或 Kafka 不可用。
**400** 只用于请求体本身不合法。错误响应体统一 `{"error": {"code", "message", "retry_after?"}}`。

**Job 状态机**：`queued → running → succeeded | failed | cancelled`。终态不可逆；
`attempts` 记录第几次投递；`failed` 附带最后一次错误摘要。

**SSE 事件**沿用内核的结构化事件流（文本增量 / 思考增量 / 工具调用 / 工具结果 / 用量 /
run 边界），外层加 `job_id` 与 `seq`。断线重连用 `Last-Event-ID` 续传。

### 数据模型（PostgreSQL）

金额一律用**整数分**（`cost_cents`），避免浮点误差；展示层再转人民币。

```sql
CREATE TABLE users (
  id          TEXT PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  status      TEXT NOT NULL DEFAULT 'active',      -- active | suspended
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
  key_hash    TEXT PRIMARY KEY,                    -- sha256(明文)，不存明文
  user_id     TEXT NOT NULL REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at  TIMESTAMPTZ
);

CREATE TABLE quota_ledger (
  id          BIGSERIAL PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id),
  job_id      TEXT,
  delta_cents INTEGER NOT NULL,                    -- 负数 = 扣减
  reason      TEXT NOT NULL,                       -- reserve | settle | refund | reconcile
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id),
  title         TEXT,
  leaf_id       TEXT,
  message_count INTEGER NOT NULL DEFAULT 0,
  cost_cents    INTEGER NOT NULL DEFAULT 0,
  fencing_token BIGINT  NOT NULL DEFAULT 0,        -- 票据 07：会话锁的单调递增凭证
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id),
  session_id  TEXT NOT NULL,
  status      TEXT NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at  TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);

CREATE TABLE usage_events (
  id               BIGSERIAL PRIMARY KEY,
  request_id       TEXT NOT NULL UNIQUE,           -- 幂等键
  user_id          TEXT NOT NULL,
  session_id       TEXT NOT NULL,
  job_id           TEXT NOT NULL,
  model            TEXT NOT NULL,
  input_tokens     INTEGER NOT NULL,
  output_tokens    INTEGER NOT NULL,
  cache_hit_tokens INTEGER NOT NULL,
  cost_cents       INTEGER NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE usage_daily (
  user_id       TEXT NOT NULL,
  usage_date    DATE NOT NULL,
  calls         INTEGER NOT NULL DEFAULT 0,
  input_tokens  BIGINT  NOT NULL DEFAULT 0,
  output_tokens BIGINT  NOT NULL DEFAULT 0,
  cost_cents    BIGINT  NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, usage_date)
);
```

不做迁移框架：`CREATE TABLE IF NOT EXISTS` + `deploy/init.sql`，版本化靠文件名。

### Redis：Key 设计与策略

| Key | 类型 | TTL | 用途 |
|---|---|---|---|
| `rl:user:{user_id}:{epoch_minute}` | HASH | 120s | 令牌桶（tokens / last_refill） |
| `quota:user:{user_id}:{yyyymmdd}` | STRING | 到次日 00:05 | 当日余额（分） |
| `lock:session:{session_id}` | STRING | PX 30000 + 续租 | 会话写锁，value = `{owner_token}` |
| `job:{job_id}` | HASH | 24h | Job 状态、进度、错误摘要 |
| `apikey:{sha256}` | STRING | 300s | Key → user_id 映射 |
| `sess:meta:{session_id}` | STRING | 60s | 会话元数据缓存 |
| `ctx:{session_id}:{leaf_id}` | STRING | 3600s | 热上下文（不可变，按 leaf 版本寻址） |

**各对象的一致性策略**（详见 ADR-0011）：

| 对象 | 策略 | 失效方式 |
|---|---|---|
| 配额余额 | Redis 为主存，`DECRBY` 原子扣减 | DB 流水对账 |
| API Key | cache-aside，PG 权威 | 吊销时 `DEL` + 300s TTL 兜底 |
| 会话元数据 | cache-aside，PG 权威 | 事件驱动 `DEL` + 60s TTL 兜底 |
| 热上下文 | 只读缓存，按 `leaf_id` 寻址 | 不失效（不可变），TTL 回收 |
| Job 状态 | Redis 为主存 | 终态写 PG 归档 |

**限流算法**：令牌桶，Lua 脚本单次求值（`HMGET` 取 tokens/last_refill → 计算补充 →
`HMSET` 写回 → 返回是否放行与建议等待时间）。按用户分 key，避免单 key 热点。

**配额扣减**：run 提交时**预扣**（预估上限），run 结束后**结算**（实际用量），差额退回。
预扣失败返回 402。结算与对账由消费者异步完成。

**会话锁**：`SET lock:session:{id} {token} NX PX 30000`；后台每 10s 续租；释放时校验 token；
锁过期后由 `fencing_token`（session 内单调递增）保证过期锁的写入被拒。

### Kafka：Topic 与消费语义

| Topic | 分区键 | 分区数 | 保留 |
|---|---|---|---|
| `run.jobs` | `session_id` | 6 | 24h |
| `run.jobs.retry` | `session_id` | 6 | 24h |
| `run.usage` | `user_id` | 6 | 7d |
| `run.audit` | `session_id` | 6 | 7d |
| `run.dlq` | `session_id` | 6 | 7d |

- **手动提交位点**：处理成功后才 `commit`；失败不提交，重试 N 次（默认 3）后投 `run.dlq`。
- **幂等**：`usage_events.request_id` 唯一约束；`jobs.id` 主键；重复投递不产生副作用。
- **顺序**：同一 `session_id` 固定同一分区，保证会话内有序。
- **重放**：`run.usage` 保留 7 天，可用脚本重算 `usage_daily` 验证账单一致性。

### 背压、降级与故障矩阵

**背压**：以 Kafka consumer lag 为队列深度信号；超过阈值（默认 10000 条）时 `/v1/runs`
返回 503 + `Retry-After: 5`。第一版不做按用户公平调度，作为压测后的第二版。

| 故障 | 限流 | 配额 | 缓存 | 会话锁 | 入队 | 消费 |
|---|---|---|---|---|---|---|
| Redis 不可用 | **fail-open** | **fail-closed**（503） | 直连 PG | **fail-closed**（409） | 正常 | 正常 |
| Kafka 不可用 | 正常 | 正常 | 正常 | 正常 | **503** | 停止 |
| PostgreSQL 不可用 | 正常 | 正常（Redis 主存） | 读降级失败（500） | 正常 | 正常 | 重试 → DLQ |

两条链路策略相反是有意的：**限流保护可用性，配额保护钱**。

### 客户端

serve **不新增 UI 体系**，复用现有事件流（「同一套事件、不同呈现」的第五、第六个实例）：

- **远程 CLI**：`codelotte --remote <url> -p "..."`。事件源从本地 `AgentLoop` 换成 SSE 异步迭代器，
  [run.py](../../../src/codelotte/run.py) 的 presenter 不改。
- **单页 HTML**：`deploy/web/index.html`，vanilla JS + `EventSource`，无构建、无框架；
  只有提交、状态、流式输出三件事。
- **事件编解码**：`TextDelta` / `ReasoningDelta` / `ToolRequested` / `ToolFinished` /
  `CostRecorded` / `CompactionEvent` / `GuardrailTriggered` / `RunEnded` 的 JSON 双向序列化，
  以 [loop.py](../../../src/codelotte/loop.py) 的 dataclass 为准，不在 serve 侧重造。
- **断线重连**：`Last-Event-ID` 续传，事件不重不漏。
- **不压缩**：`text/event-stream` 保持纯文本，便于抓包与调试；响应头不出现 `Content-Encoding`。

明确不做：远程 Textual TUI（服务端 fail-closed，没有审批弹层的对应交互）、SPA / 登录页 /
会话列表页。

### 可观测性

`/metrics` 至少暴露：

```
codelotte_http_requests_total{method,path,status}
codelotte_http_request_duration_seconds{method,path}
codelotte_runs_submitted_total
codelotte_runs_finished_total{status}
codelotte_queue_lag{topic}
codelotte_cache_requests_total{name,result}
codelotte_rate_limited_total
codelotte_quota_rejected_total
codelotte_job_attempts_histogram
```

日志为结构化 JSON，字段固定包含 `ts` / `level` / `request_id` / `user_id` / `session_id` /
`job_id`（缺省为空串）。**不记录 prompt 正文与 API Key**。

### 部署与配置

`deploy/docker-compose.yml` 起五个服务：`api`、`worker`、`redis`、`kafka`、`postgres`，
全部带 healthcheck；`api` 与 `worker` `depends_on: condition: service_healthy`。
Session entries 目录挂 **named volume**，API 与 worker 共享。

镜像按 digest 固定，与本地已拉取的一致（2026-10-28 实测）：

| 服务 | 镜像 | 版本 | 备注 |
|---|---|---|---|
| redis | `redis@sha256:344e3945…` | 8.10.0 | 内置 Bloom 模块，lab 02 可直接 `BF.ADD` |
| kafka | `apache/kafka@sha256:77e3df90…` | 4.3.1 | 纯 KRaft，无 ZooKeeper |
| postgres | `postgres@sha256:979bccfd…` | 18.6 | **`PGDATA=/var/lib/postgresql/18/docker`，卷必须挂 `/var/lib/postgresql`** |

Session entries 的共享卷挂在 `/data/sessions`，API 与 Worker 都通过环境变量
`CODELOTTE_SESSION_ROOT` 指向它。

配置全部走环境变量，提供 `deploy/.env.example`。模板里的开发默认值与 compose、`serve/config.py`
保持一致，复制后不配置也能跑通；密码类字段在注释里注明「生产必须替换」。

### 实验（labs）

| lab | 主题 | 错误版本 | 正确版本 |
|---|---|---|---|
| 01 | 限流 | 非原子 `GET`+`SET`；固定窗口临界突刺 | 令牌桶 Lua |
| 02 | 缓存三大问题 | 无空值缓存 / 无互斥重建 / TTL 齐过期 | 空值缓存 + singleflight + 随机 TTL |
| 03 | 缓存一致性 | 只写 DB 不删缓存；先删后写 | cache-aside + 删除重试 + TTL 兜底 |
| 04 | 分布式锁 | 无过期；无 owner 校验；无续租 | `SET NX PX` + 校验 + watchdog + fencing |
| 05 | 配额 | DB `SELECT`+`UPDATE`；Redis 当副本 | Redis 原子扣减 + 流水 + 对账 |
| 06 | 队列选型 | Redis List；Redis Streams | Kafka 手动提交 |
| 07 | 消费语义 | 先提交后处理；无幂等；不按 session 分区 | 手动提交 + 幂等键 + 分区键 |
| 08 | 削峰与积压 | 同步执行 | 全异步 + 有界队列 + 背压 + lag 监控 |

每个 lab 产出：`labs/NN-*/README.md`（假设、步骤、复现命令）、错误版与正确版代码、
`results.json`（量化对比）、一段可直接用于面试的结论。

## Testing Decisions（测试决策）

- **只测外部行为**：给定请求与注入依赖，断言响应、PG 行、Kafka 消息、Redis key、可见日志。
- **确定性优先**：LLM 用 fake provider；时间与随机数可注入；默认测试离线。
- **三层测试缝**：
  1. **API 缝**：FastAPI `TestClient` + 真实 Redis/PG（docker），断言状态码与副作用。
  2. **Worker 缝**：直接调用消费函数，注入 fake Kafka consumer，断言位点提交与幂等。
  3. **lab 缝**：每个 lab 是独立可执行脚本，输出 `results.json`，由测试断言关键不等式
     （错误版必须失败、正确版必须通过）。
- **集成测试标记** `@pytest.mark.serve`，默认 `pytest -q` 跳过；CI 与本地用
  `pytest -m serve` 跑。
- **故障注入**：`deploy/faults/*.sh`，每个脚本自带断言与观察输出。
- **压测**：fake provider，目标见 PLAN §4。

## Out of Scope（不在范围内）

- 注册登录、密码找回、OAuth、团队/组织层级（只有 User，没有 Org）。
- Web SPA、登录页、会话列表页；远程 Textual TUI；SSE 事件压缩。
- Grafana / Prometheus Server / 告警推送链路（只暴露 `/metrics`）。
- Kubernetes、多地域、多活、容灾演练。
- 语义缓存（embedding 相似度复用）。
- Session entries 入库（维持 ADR-0003 与 ADR-0011）。
- MCP / Skill / 权限 v2 / 专用沙箱镜像（属 v0.3.0，见 [../v3/](../v3/README.md)）。
- 按用户加权公平调度（第一版不做，压测后再评估）。
- 真实模型的大规模压测（只做小样本端到端验证）。

## Further Notes（补充说明）

- **为什么这个功能集不算膨胀**：八个 lab 对应八个被追问的高频问题，每个都是「先失败再修好」；
  没有一个是「因为技术栈里有它所以用它」。排行榜、布隆过滤器之外的花活明确不做。
- **已知限制**：多实例部署依赖共享卷；消费者数受分区数限制；配额对账存在异步窗口。
- **交付原则**：全部票据完成并跑出数据后，才写入简历与面试材料。部分完成不对外。
- **变更控制**：实现中若需推翻 ADR-0010–0012，新增 ADR 并在旧文末标注 superseded。
