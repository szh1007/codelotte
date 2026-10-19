# 实验报告

按 PLAN.md 的实验标准交付：任务集 / 基线 / 干预 / 指标 / 轨迹样本 / 复现命令。
每份报告对应一个可复现的 run 目录，数字来自报表而不是手抄。

| 实验 | 问题 | 报告 | 跑数 |
|---|---|---|---|
| E1 | 压缩次数 × 切点策略 × 摘要模板：完成率/保留率/成本曲线（短任务 + 长任务补充） | [e1-compaction-curve.md](e1-compaction-curve.md) | `evals/runs/20261018T165516Z-8a01d9f` + `evals/runs/20261019T013233Z-8a01d9f` |
| E2 | 缓存命中与 off-peak 调度的实际/反事实成本 | [e2-cost-curve.md](e2-cost-curve.md) | `evals/cost/cost-report.md` |
| E3 | 归因准确率、混淆矩阵与真实失败分布 | [e3-attribution-accuracy.md](e3-attribution-accuracy.md) | `evals/attribution/attribution-report.md` |
| E4 | scaffolding tax：工具循环值多少、harness 相对参照物的增量有多少 | [e4-scaffolding-tax.md](e4-scaffolding-tax.md) | `evals/runs/20261018T155840Z-fa9db83-compare` |
| E5 | 注入拦截、死循环三层拦截、真实模型死循环压力与正常任务误报审计 | [e5-defense-effectiveness.md](e5-defense-effectiveness.md) | `evals/defense/defense-report.md` |

复盘文：[retrospective.md](retrospective.md)（结论段双语）。
材料包（票据 22）从这里取 E1–E5 的数字与链接；E3/E5 已就位，材料包的治理文档与
面试脚本待票据 22 完成。
