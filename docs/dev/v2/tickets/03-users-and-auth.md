# 03: 用户与鉴权（API Key + 缓存）

**What to build:** `users` / `api_keys` 两张表的数据访问层；`Authorization: Bearer <key>` 中间件
把 key 哈希后查用户；Redis 做 cache-aside（`apikey:{sha256}`，TTL 300s）。提供 seed 脚本造
测试用户与 key。Key 吊销时同步 `DEL` 缓存。

本票刻意实现**两种查 key 方式**：查存在与查不存在，为 05 的缓存穿透实验准备真实入口。

🗣 大白话：把「你是谁」这件事从数据库搬到请求头上，并给它配一层缓存；同时准备好「查一个不存在的用户」这个高频攻击场景。

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] `serve/auth.py`：key 哈希（sha256）、查库、缓存读写、吊销
- [ ] FastAPI 依赖：无效/缺失 key 一律 401，响应体不区分「格式错」与「不存在」
- [ ] Redis `apikey:{sha256}` cache-aside：命中直接返回，未命中查 PG 后回填
- [ ] seed 脚本：3 个用户 × 各 2 个 key，可重复执行
- [ ] 吊销：更新 `revoked_at` 并 `DEL` 缓存；吊销后下一次请求立即 401
- [ ] 测试：有效 key 通过；无效 key 401；吊销后立即 401；缓存命中时不再查库（注入计数断言）
- [ ] 指标：`codelotte_cache_requests_total{name="apikey",result}`
- [ ] 日志字段 `user_id` 在鉴权后全程存在
