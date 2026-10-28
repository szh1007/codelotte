# 04: 限流与配额（lab 01 + lab 05）

**What to build:** 令牌桶限流（Lua 单次求值）+ 日配额预扣/结算。限流按 user 分 key；
配额以 Redis 为唯一计数器，`quota_ledger` 记流水。实现 `POST /v1/runs` 的 429 / 402 分支。

配对两个 lab：

- **lab 01 限流**：错误版 A `GET` + `SET`（非原子）→ 并发下超额；错误版 B 固定窗口 → 临界突刺
  双倍；正确版令牌桶 Lua。
- **lab 05 配额**：错误版 A `SELECT` + `UPDATE`（窗口期超支）；错误版 B Redis 当 DB 副本
  （同样超支）；正确版 Redis 原子扣减 + 流水 + 对账。

🗣 大白话：限流是「别把下游打死」，配额是「别把钱花超」。两个都是计数器，但一个能放行、一个不能。

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `serve/ratelimit.py`：Lua 令牌桶，返回 `(allowed, remaining, retry_after_ms)`
- [ ] 429 响应带 `Retry-After`；指标 `codelotte_rate_limited_total`
- [ ] `serve/quota.py`：预扣（按预估上限）、结算（按实际用量）、差额退回
- [ ] `quota_ledger` 写 `reserve` / `settle` / `refund` 三类流水
- [ ] 402 响应语义与 429 区分；指标 `codelotte_quota_rejected_total`
- [ ] 对账命令 `python -m codelotte.serve.reconcile`：Redis 余额 vs 流水净额，输出差异
- [ ] `labs/01-rate-limit/`：两个错误版 + 正确版 + 压测脚本 + `results.json`
- [ ] `labs/05-quota/`：两个错误版 + 正确版 + `results.json`
- [ ] `results.json` 必须包含：错误版超额次数/超支金额、正确版为 0
- [ ] 测试：并发 200 请求下正确版超额数为 0（错误版作为对照，断言其超额 > 0）
