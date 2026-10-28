# 10: 削峰与背压（lab 08）

**What to build:** 两个实验证明异步化的价值，以及在压力超过处理能力时的正确行为：

1. **削峰对比**：`POST /v1/runs:batch` 一次提交 1000 个 Job。
   - 错误版：同步执行（请求内跑完）→ 连接被打满、P99 爆炸、大量超时
   - 正确版：只入队 → 提交接口 P99 恒定，Kafka lag 先涨后落
2. **背压**：lag 超过阈值（默认 10000）时 `/v1/runs` 返回 503 + `Retry-After`。
   - 对照：无背压时 lag 无限增长，恢复时间随积压线性拉长；有背压时提交端被限住，恢复时间可控。

指标 `codelotte_queue_lag{topic}` 与 `codelotte_runs_submitted_total` 是这两个实验的主要观测面。

🗣 大白话：削峰不是「让任务跑得更快」，是「让入口不被堵死」，以及在堵死之前主动喊停。

**Blocked by:** 09

**Status:** ready-for-agent

- [ ] `POST /v1/runs:batch`：≤ 500 条，返回 accepted / rejected 明细
- [ ] lag 采集：定期查询 Kafka consumer lag，写入指标
- [ ] 背压：lag > 阈值 → 503 + `Retry-After`；阈值可配
- [ ] `labs/08-burst-and-backpressure/`：同步 vs 异步、无背压 vs 有背压四组数据
- [ ] `results.json`：提交 P99、吞吐、峰值 lag、恢复时间
- [ ] 测试：背压开启时持续提交，503 比例 > 0 且 lag 有上界
- [ ] 测试：停止提交后 lag 在 60s 内回落到 0
- [ ] （可选，压测后评估）按 user 加权公平调度：单用户占满时其他用户仍能提交
