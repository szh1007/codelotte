# 01: 部署地基（compose + PostgreSQL schema + 连接层）

**What to build:** 用 `deploy/docker-compose.yml` 一次拉起 `redis` / `kafka` / `postgres` 三个依赖，
全部带 healthcheck；`deploy/init.sql` 建 SPEC 里的 7 张表（`CREATE TABLE IF NOT EXISTS`）；
`deploy/.env.example` 给出全部配置项占位。新建 `src/codelotte/serve/` 包，先只放配置加载与
三个客户端的连接工厂（redis / kafka producer-consumer / asyncpg pool），并提供一个
`python -m codelotte.serve.healthcheck` 命令，能在全部依赖就绪时退出码 0、任一不可用时列出是哪一项。

镜像按 digest 固定，与本机已拉取的一致：Redis **8.10.0**、Kafka **4.3.1**（纯 KRaft）、
PostgreSQL **18.6**。注意 PG 18 的 `PGDATA` 是 `/var/lib/postgresql/18/docker`，
**named volume 必须挂 `/var/lib/postgresql`**，挂 `/var/lib/postgresql/data` 会看不到数据。

🗣 大白话：先把三台服务器点着，并写一个「都通了吗」的自检程序；后面所有实验都靠它。

**Blocked by:** None

**Status:** done

- [x] `deploy/docker-compose.yml`：redis 8.10 / kafka 4.3（KRaft）/ postgres 18.6，digest 固定，均带 healthcheck
- [x] `deploy/init.sql`：7 张表 + `usage_events.request_id` 唯一约束 + 必要索引
- [x] `deploy/.env.example`：Redis/Kafka/PG 连接、令牌桶参数、配额默认值、队列积压阈值；密码用开发默认值并在注释标明生产必须替换
- [x] `src/codelotte/serve/__init__.py`、`config.py`、`clients.py`
- [x] `python -m codelotte.serve.healthcheck` 输出三项状态，全通退出 0
- [x] `serve` 依赖写进 `pyproject.toml` 的 `[project.optional-dependencies]`，不污染默认依赖
- [x] 测试：`tests/serve/test_healthcheck.py`，依赖不可用时退出码非 0 且指明是哪一项
- [x] `deploy/README.md`：起停命令、端口、常见失败（Windows 卷权限、Kafka 启动慢）

**实测记录（2026-10-28）**：三个容器均 healthy；自检三项 OK、退出 0；7 张表与
`request_id` 唯一索引已建；`pytest -q` 606 passed / 8 deselected；ruff 与 pyright 干净。

**命名与端口约定**：compose 项目名 `codelotte`，容器名 `codelotte-redis` / `codelotte-kafka` /
`codelotte-postgres`（显式 `container_name`，不带 `-1` 后缀）；宿主端口统一加 1 前缀
**16379 / 19092 / 15432**，避免撞上本机已装的同类服务。

**踩到的坑**：宿主机已装原生 PostgreSQL 并占用 5432，请求被它接走，asyncpg 报
`ConnectionDoesNotExistError: connection was closed in the middle of operation`。容器自身日志
无任何连接记录，`netstat` 显示 `postgres.exe` 与 `com.docker.backend.exe` 同时监听 5432。
已把宿主端口映射改为 **15432**，并在 `deploy/README.md` 记录。

**复查修复（同日）**：

1. `healthcheck.main()` 遇到非法配置会抛栈——改为打印一行 `配置错误：…` 并退出码 **2**，
   与「依赖不通」的退出码 1 区分。
2. `redis.from_url()` 在 `try` 之外构造，畸形 URL 会让 `check_all` 整体抛 `ValueError`——
   把构造移进 `try`，并把 `ValueError` 计入 FAIL。
3. SPEC 的 `sessions` DDL 漏了 `fencing_token`（`init.sql` 与票据 07 都有）——补齐。

**两轴评审后的修复（同日）**：

4. 测试对 `localhost:6399/9099/5499` 真发 TCP，违反 CONTRIBUTING「单元测试不得访问网络」，
   且要求这些端口恰好空闲。改为把 `create_redis` / `asyncpg.connect` / `_list_topics`
   替换成确定性失败；只用畸形连接串的用例保留真实解析（不建连接）。
5. `healthcheck` 自建 Redis 客户端，与 `clients.create_redis` 重复且已分叉（缺 `decode_responses`）——
   改为复用工厂。
6. 票据要求「kafka producer-consumer」两个工厂，实际只有 `Producer`——补 `create_kafka_consumer`，
   写死 `enable.auto.commit=False`（ADR-0012 的手动提交位点）。它是纯适配器，订阅结果没有公开
   查询接口，离线不断言，由票据 08 的 `pytest -m serve` 覆盖。
7. 补 `main()` 在依赖不通时返回 1 的用例（此前只断言 `check_all` 与文本）。
8. 密码链路断开：`.env.example` 写 `change-me`，而 `config.py` 默认是 `codelotte-dev`，
   README 又引导复制 `.env`——照做后自检必然认证失败。三处统一为开发默认值 `codelotte-dev`，
   `.env.example` 注明生产必须替换。
9. 关闭 `KAFKA_AUTO_CREATE_TOPICS_ENABLE`：自动建 topic 会让拼错的 topic 名静默产生一个
   保留期不对的新 topic；topic 由票据 08/11 显式创建。
10. `addopts` 改为 `not docker and not serve`（SPEC 要求 serve 标记默认跳过）；
    CONTRIBUTING 的代码地图与测试约定补上 `serve/`。
11. 公共函数补 Google Style docstring（`clients` 四个工厂、`format_results`、`main`）。
