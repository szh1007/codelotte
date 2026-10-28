# 06: 缓存一致性（lab 03）

**What to build:** 会话汇总（`sessions.message_count` / `cost_cents`）走 cache-aside，
由 Kafka 消费者异步更新 DB 后删缓存。复现三种不一致并修复：

| 错误版本 | 现象 |
|---|---|
| 只写 DB 不删缓存 | 读到的永远是旧值，直到 TTL 过期 |
| 先删缓存再写 DB | 并发读写交错，缓存被旧值回填 |
| 删缓存失败不重试 | 偶发脏读，且不可观测 |

正确版本：**先写 DB，再删缓存**；删除失败重试 3 次并退避；保留 60s TTL 兜底；
所有删除失败打点 `codelotte_cache_invalidate_failed_total`。

同时给出「延迟双删」的对照数据，说明它在什么条件下才有意义——本项目的预期结论是
**TTL 兜底 + 重试已足够，延迟双删不带来可测收益**；如果数据不支持这个结论，如实写。

🗣 大白话：缓存和数据库总有先后，关键是选一个「错了也能自己好」的顺序，并给错误留观测。

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] `serve/cache.py` 增加 `delete_with_retry(key, attempts=3)`
- [ ] 会话汇总更新路径：写 PG → 删缓存 → 失败重试 → 打点
- [ ] `labs/03-cache-consistency/`：三种错误版 + 正确版 + 并发读写脚本
- [ ] `results.json`：每种版本的「脏读次数 / 总读次数」与「最长脏读持续时间」
- [ ] 对照实验：延迟双删 vs TTL 兜底，给出两者脏读次数与额外延迟
- [ ] 测试：并发「写 summary + 读 summary」1000 次，正确版脏读 ≤ 1 且 1s 内自愈
- [ ] README 写明：为什么本项目不用「缓存双写」，以及什么场景下才必须用
