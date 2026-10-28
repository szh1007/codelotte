# 13: 压测与实验报告

**What to build:** 一套可复现的压测脚本，产出 SPEC 口径的完整数据，并汇总成一份报告。

口径（必须写进报告）：

- **fake provider**：零成本、确定性、可复现。真实模型只跑 3 条端到端冒烟，验证接线正确。
- 场景：单请求、并发 50 / 200 / 500、批量提交 1000、慢消费、故障恢复。
- 指标：提交 P99、端到端完成 P99、吞吐、峰值 lag、错误率、缓存命中率。

报告结构固定为「测了什么 / 数字 / 这证明了什么 / 不证明什么」——沿用 v1 实验报告体例，
其中「不证明什么」必须实写，不许留空。

压测工具用 Python `asyncio` + `httpx` 自写脚本，不引入 locust：场景简单，自写更容易把
fake provider 和中间件指标接进去。

🗣 大白话：数字要能一条命令重跑出来，并且自己先说清楚这些数字的边界在哪。

**Blocked by:** 12

**Status:** ready-for-agent

- [ ] `deploy/loadtest/`：`single.py` / `concurrent.py` / `batch.py` / `soak.py`
- [ ] fake provider 接入路径：环境变量切换，默认 fake，真实模型需显式开启
- [ ] 每档压测输出机器可读结果 `results.json`
- [ ] `docs/dev/v2/reports/loadtest.md`：表格 + 结论 + 局限
- [ ] 报告中「不证明什么」明确写出：fake provider 不代表模型速度；单机不代表生产集群
- [ ] 3 条真实模型端到端冒烟，记录成本
- [ ] 测试：压测脚本本身有 `--dry-run`，不实际发压
- [ ] README 的「服务化」一节引用本报告的数字，不手抄
