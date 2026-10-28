# 07: 分布式锁（lab 04）

**What to build:** 会话写锁，保证同一个 `session_id` 同时只有一个 run 在执行，避免 append-only
记录被并发写坏。三级错误版本逐层递进：

| 版本 | 缺陷 | 现象 |
|---|---|---|
| A | `SETNX` 无过期 | worker 崩溃后锁永不释放，会话永久卡死 |
| B | `SET NX PX` 但无 owner 校验 | A 超时释放时删掉了 B 的锁 |
| C | 有 owner 校验但无续租 | 任务跑超过锁 TTL，锁在运行中被别人拿走 |

正确版本：`SET NX PX` + `value=owner_token` + 释放时 Lua 比对 token + 每 10s 续租 +
**fencing token**（session 内单调递增）在写入时校验，拒绝过期持有者的写入。

不实现 Redlock。README 说明理由：单 Redis 实例下 Redlock 没有额外收益，主从切换场景的
正确性靠 fencing 而不是锁本身。

🗣 大白话：锁的难点不是「锁上」，是「锁不上时怎么办、锁掉了怎么办」——三种错误版本正好对应这三问。

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `serve/lock.py`：acquire / renew / release，value 为随机 owner token
- [ ] 释放用 Lua 比对 token，杜绝误删
- [ ] 后台续租任务；进程退出时停止续租
- [ ] fencing：`sessions.fencing_token` 单调递增，写入时校验，过期持有者写入被拒
- [ ] `labs/04-distributed-lock/`：三个错误版 + 正确版 + 故障注入脚本
- [ ] `results.json`：死锁次数、误删次数、运行中丢锁次数、fencing 拒绝次数
- [ ] 测试：并发 50 个 worker 抢同一 session，成功获取恰好 1 个
- [ ] README：Redlock 为什么不实现、什么条件下需要
