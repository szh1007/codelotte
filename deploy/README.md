# deploy

codelotte serve 的本地依赖环境。当前只有三个中间件；`api` 与 `worker` 两个服务在票据 02 接入。

## 起停

```bash
cd deploy
cp .env.example .env      # 可选：默认值已能跑通；改密码时 DSN 与 POSTGRES_PASSWORD 要一起改
docker compose up -d
docker compose ps         # 三个服务都应为 healthy
```

停止但保留数据：`docker compose down`
停止并清空数据：`docker compose down -v`

自检（在仓库根目录，需要先 `uv sync --extra serve`）：

```bash
uv run --extra serve python -m codelotte.serve.healthcheck
```

输出三项 `OK` 且退出码 0 即环境就绪；任何一项 `FAIL` 都会点名是哪一项并给出原因。

## 端口

宿主端口统一加 1 前缀，避开本机已装的同类服务（本机就有原生 PostgreSQL 占着 5432）。

| 服务 | 容器名 | 宿主机 | 容器内 | 用途 |
|---|---|---|---|---|
| redis | `codelotte-redis` | **16379** | 6379 | 缓存 / 限流 / 配额 / 锁 / Job 状态 |
| kafka | `codelotte-kafka` | **19092** | 9092（EXTERNAL）、29092（INTERNAL） | 任务队列与事件总线 |
| postgres | `codelotte-postgres` | **15432** | 5432 | 用户、密钥、流水、会话元数据、Job 归档 |

Kafka 配了双监听：宿主机客户端连 `localhost:19092`，将来 compose 网络内的 api/worker 连 `kafka:29092`。
容器名显式写成 `codelotte-<service>`，不带 compose 默认的 `-1` 后缀；这三个都是单实例，不需要扩缩容。

## 镜像版本

| 服务 | 版本 | digest（前 8 位） |
|---|---|---|
| redis | 8.10.0 | `344e3945` |
| apache/kafka | 4.3.1（纯 KRaft） | `77e3df90` |
| postgres | 18.6 | `979bccfd` |

digest 写死在 `docker-compose.yml` 里，换机器时 `docker compose pull` 会拉到完全相同的镜像。

## 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| postgres 一直 unhealthy 或数据「消失」 | PG 18 的 `PGDATA` 是 `/var/lib/postgresql/18/docker` | 卷必须挂 `/var/lib/postgresql`，不是 `/var/lib/postgresql/data` |
| kafka 启动慢、前 20 秒连接被拒 | KRaft 单节点首次格式化 + 内部 topic 创建 | `start_period` 已给 20s；等 `docker compose ps` 显示 healthy 再跑自检 |
| `init.sql` 没生效 | 只在数据卷为空时执行一次 | `docker compose down -v` 后重新 `up -d` |
| healthcheck 报密码错误 | `.env` 里 `CODELOTTE_PG_DSN` 与 `POSTGRES_PASSWORD` 不一致 | 两处改成同一个密码；不改密码时默认值本来就一致 |
| Windows 下 `init.sql` 没执行、PG 起不来 | Docker Desktop 未共享仓库所在盘符 | Settings → Resources → File Sharing 加入仓库所在盘，重启 Docker Desktop |
| 生产消息报 `UNKNOWN_TOPIC_OR_PART` | 自动建 topic 已关闭 | 预期行为；topic 由票据 08/11 显式创建，带分区数与保留期 |
| 连接 PG 报 `ConnectionDoesNotExistError: connection was closed in the middle of operation` | 本机原生 PostgreSQL 占着 5432，请求打到了它而不是容器 | 已默认映射到 **15432**；若仍冲突，改 `ports` 左侧并同步 `CODELOTTE_PG_DSN` |
| Windows 下其他端口被占 | 本机已装 Redis 等 | 改 `ports` 映射的左侧端口，并同步 `.env` 连接串 |
| `docker compose` 报找不到 `init.sql` | 不在 `deploy/` 目录执行 | compose 的相对路径以文件所在目录为基准，`cd deploy` 再执行 |

## 重置

```bash
docker compose down -v && docker compose up -d
```

清空后 `init.sql` 会重新执行，得到一份干净的 7 张表。
