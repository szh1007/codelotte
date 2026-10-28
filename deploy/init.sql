-- codelotte serve 的 PostgreSQL schema（v0.2.0 / ADR-0011）。
-- 只在本文件首次挂载时由官方镜像的 entrypoint 执行一次；已有数据卷时不会重跑。
-- 不用迁移框架：新增表用 CREATE TABLE IF NOT EXISTS，破坏性变更另写 ADR。
-- 金额一律用整数「分」，避免浮点误差；展示层再转人民币。

-- 账号：配额、限流、账单的唯一主体（CONTEXT.md 的 User）
CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  status      TEXT NOT NULL DEFAULT 'active',      -- active | suspended
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 凭证：只存 sha256 摘要，不存明文；吊销靠 revoked_at，不删行（保留审计）
CREATE TABLE IF NOT EXISTS api_keys (
  key_hash    TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS api_keys_user_idx ON api_keys (user_id);

-- 配额流水：Redis 是权威计数器，这里是账本；对账任务用净额与 Redis 余额比差
CREATE TABLE IF NOT EXISTS quota_ledger (
  id          BIGSERIAL PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id),
  job_id      TEXT,
  delta_cents INTEGER NOT NULL,                    -- 负数 = 扣减
  reason      TEXT NOT NULL,                       -- reserve | settle | refund | reconcile
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quota_ledger_user_time_idx ON quota_ledger (user_id, created_at DESC);

-- 会话元数据：entries 本体仍在 JSONL（ADR-0003 / 0011），这里只存可查询的汇总
-- fencing_token 由票据 07 的分布式锁使用，单调递增，过期持有者的写入会被拒
CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES users(id),
  title         TEXT,
  leaf_id       TEXT,
  message_count INTEGER NOT NULL DEFAULT 0,
  cost_cents    INTEGER NOT NULL DEFAULT 0,
  fencing_token BIGINT NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sessions_user_time_idx ON sessions (user_id, updated_at DESC);

-- Job：一次 Run 的调度单元；状态高频读写走 Redis，这张表是终态归档
CREATE TABLE IF NOT EXISTS jobs (
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

CREATE INDEX IF NOT EXISTS jobs_user_time_idx ON jobs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);

-- 用量流水：request_id 唯一约束是消费端幂等的唯一依据（至少一次投递 → 恰好一次计费）
CREATE TABLE IF NOT EXISTS usage_events (
  id               BIGSERIAL PRIMARY KEY,
  request_id       TEXT NOT NULL UNIQUE,
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

CREATE INDEX IF NOT EXISTS usage_events_user_time_idx ON usage_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS usage_events_session_idx ON usage_events (session_id);

-- 日聚合：由 usage 消费者累加；可清空后从 Kafka 保留期重放重建（票据 11 的实证）
CREATE TABLE IF NOT EXISTS usage_daily (
  user_id       TEXT NOT NULL,
  usage_date    DATE NOT NULL,
  calls         INTEGER NOT NULL DEFAULT 0,
  input_tokens  BIGINT  NOT NULL DEFAULT 0,
  output_tokens BIGINT  NOT NULL DEFAULT 0,
  cost_cents    BIGINT  NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, usage_date)
);
