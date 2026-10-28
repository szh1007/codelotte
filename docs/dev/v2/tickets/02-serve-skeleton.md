# 02: serve 骨架（API + worker + 优雅关闭）

**What to build:** `codelotte serve` 子命令启动 FastAPI。先只实现最薄的一条链路：
`POST /v1/runs` → 写 `jobs` 表 → 返回 202 + `job_id`；worker 进程轮询/消费（本票可先用
PostgreSQL 轮询做占位，08 再换 Kafka）→ 调用现有 `AgentLoop` 跑一次 run → 更新状态。
同时实现 `/healthz`、`/readyz`、SIGTERM 优雅关闭（停止拉新任务、等在跑的 run 结束、
最长等待 30s 后强制退出）。

**内核零改动**：本票只能新增 `src/codelotte/serve/**`，不得修改 `loop.py`、`store.py`、`cost.py`。

🗣 大白话：先让「提交任务 → 后台跑 → 查结果」这条最小闭环跑起来，不接任何中间件语义。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `codelotte serve` 子命令（`cli.py` 只加一行分发，不改现有命令行为）
- [ ] `POST /v1/runs`：body 校验、落 `jobs` 表、返回 202
- [ ] `GET /v1/runs/{job_id}`：返回状态与错误摘要
- [ ] worker 进程：取 `queued` → `running` → 执行 `AgentLoop` → `succeeded` / `failed`
- [ ] SIGTERM：不再取新任务；在跑任务最多等 30s；日志记录优雅关闭开始/结束
- [ ] `/healthz` 恒 200；`/readyz` 检查 Redis/Kafka/PG 三项
- [ ] 测试：一次完整 run 的 API 缝测试（fake provider），断言状态流转与 `jobs` 行
- [ ] 测试：SIGTERM 时正在跑的 run 能跑完，进程退出码 0
- [ ] `git diff --stat src/codelotte/*.py`：除 `serve/` 外为空
