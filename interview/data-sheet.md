# 面试数据表（一页纸）

> 截至 **2026-10-19**。所有数字来自入库报表，链接可查到原始 run。
> 用法：面试时屏幕共享这一页，按「结论 → 分母 → 来源 → 不能证明什么」讲。
> 报告索引：[docs/experiments/](../docs/experiments/README.md) · 跑数索引：[evals/record.md](../evals/record.md)。

## 0. 仓库与工程

| 指标 | 数值 | 来源 / 口径 |
|---|---|---|
| 版本 | `0.1.0` | [CHANGELOG.md](../CHANGELOG.md) |
| 票据 | 01–22 均标记 done（含作者待补：录屏、dogfood、整场口述计时） | [docs/tickets/README.md](../docs/tickets/README.md) |
| 提交 | 39 个（数据快照，材料提交前；`main`，无 merge commit） | `git log --oneline`，2026-10-13 起 |
| 公开 PR | 0（个人开发，直接提交） | 同上 |
| GitHub stars / forks | 1 / 0 | `gh api repos/szh1007/codelotte`，2026-10-19 |
| 测试 | **594 passed, 8 deselected** | `uv run pytest -q`；Docker 组用 `pytest -m docker` |
| CI | Ubuntu + Windows；ruff / pyright / pytest | [.github/workflows/ci.yml](../.github/workflows/ci.yml) |
| 任务文件 | 9 通用（含压缩回归 001–003、注入 004/005）+ 3 judge + 3 独立注入 + 1 死循环压力 + 1 回归 | `evals/tasks/`、`evals/judge-tasks/`、`evals/defense-tasks/`、`evals/loop-tasks/`、`evals/regressions/` |
| 评测命令 | 9 个（run / compaction / compare / controls / judge / attribute / regression / cost / defense） | `uv run codelotte eval --help` |

## 1. 评测可信度（先证明考场可信）

| 检查 | 结果 | 来源 |
|---|---|---|
| 正式评测 9 任务 × 3 次 | **27/27 通过，pass^3 9/9，¥0.205832，349.0s** | [report](../evals/runs/20261018T154112Z-fa9db83/report.md) |
| oracle 控制 agent | 9/9 通过 | [controls](../evals/runs/20261018T154851Z-fa9db83-controls/report.md) |
| no-op 控制 agent | 0/9 通过 | 同上 |
| cheating 控制 agent | 0/9 通过，且 **9/9 被标记** | 同上 |
| judge 校准 | 3 个任务 × 20 条样本，Cohen's κ = **1.000** | [006](../evals/judges/006-code-review/calibration.md) / [101](../evals/judges/101-concurrency-review/calibration.md) / [102](../evals/judges/102-api-design-tradeoffs/calibration.md) |
| judge 真实任务 | 3/3，overall 均 **1.00**（阈值 0.70），¥0.041690 | [report](../evals/runs/20261018T154901Z-fa9db83/report.md) |

**不能证明什么：** judge 与归因语料是作者草拟（`author-draft`），样本刻意清晰，κ=1.0 有天花板效应；
报表标 ⚠、退出码 1。需要独立标注者复核后才算泛化结论。

## 2. E1 压缩曲线（策略 × 模板 × k）

短任务：6 条 × k=0/1/3/5 × 3 组合 = **72 条案例**；长任务补充：3 条 × 4 k × 3 组合 = **36 条案例**。

| 指标 | `minimal/seven`（基线） | `minimal/compact`（三节模板） | `wide/seven`（保留两个 turn） |
|---|---:|---:|---:|
| 短任务完成率 | 100% | 100% | 100% |
| 短任务有效保留率 | 100% | 100% | 100% |
| 短任务 k=5 成本 | ¥0.259310 | **¥0.200221（−22.8%）** | ¥0.300171（+15.8%） |
| 短任务全曲线总成本 | ¥0.563483 | **¥0.417744（−25.9%）** | ¥0.578220（+2.6%） |
| 短任务 k=5 有效案例 | 5/6 | 5/6 | **6/6**（只买到可达性） |
| 长任务保留率 | 87.8% | **93.3%** | 86.7% |
| 长任务总成本 | ¥0.751249 | **¥0.577443（−23.1%）** | +2.2% |

来源：[E1 报告](../docs/experiments/e1-compaction-curve.md) ·
[短任务 run](../evals/runs/20261018T165516Z-8a01d9f/report.md) ·
[长任务 run](../evals/runs/20261019T013233Z-8a01d9f/report.md)

**不能证明什么：** 单次重复；k=0 控制组本身有约 18% 成本波动，百分比读作方向 + 量级，
不是精确效应量。短任务两个指标都到天花板，不能据此说「压缩无损」。

## 3. E2 成本曲线（缓存 + off-peak）

| 指标 | 正式 run（27 案例 / 188 调用） | E4 codelotte（18 案例 / 125 调用） |
|---|---:|---:|
| 缓存命中率 | **89.0%** | **89.4%** |
| 实际成本 | **¥0.205832** | **¥0.128218** |
| 无缓存反事实 | ¥0.535853 | ¥0.344091 |
| 全峰价反事实 | ¥0.411664 | ¥0.256435 |
| 无缓存 + 全峰价 | ¥1.071706 | ¥0.688182 |
| 总节省 | **¥0.865874（80.8%）** | **¥0.559964（81.4%）** |

来源：[成本报告](../evals/cost/cost-report.md) · [E2 报告](../docs/experiments/e2-cost-curve.md)

**不能证明什么：** 这是从 usage **反事实重算**，不是「关掉缓存再跑」的 A/B；
所有实际调用都落在低谷，「全峰价」正好是 2 倍。缓存贡献约 62%，off-peak 贡献 50%
（两者对基准不同，不可直接相加）。

## 4. E4 scaffolding tax（同模型三组对照）

9 条任务 × 2 次重复，同一 `deepseek-flash`、同一 `reasoning_effort=high`。

| 组 | 通过 | pass^2 | 模型调用 | 总成本 | 平均耗时/案例 | 每条成功成本 |
|---|---|---:|---:|---:|---:|---:|
| **codelotte** | **18/18 (100%)** | 9/9 | 125 | ¥0.128218 | 13.9s | ¥0.00712 |
| mini-swe-agent 2.4.6 | **18/18 (100%)** | 9/9 | 99 | ¥0.111146 | 20.9s | ¥0.00617 |
| 裸单轮 API（无工具） | 0/18 (0%) | 0/9 | 18 | ¥0.280970 | 17.3s | — |

- 相对 mini：成功率**打平**；codelotte 成本 **+15.4%**、调用 **+26.3%**、耗时 **−33.5%**。
- 相对裸 API：0/18 说明工具循环是必要条件；裸 API 的成本被一次长推理调用抬高，
  只作结构下界，不作成本基线。

来源：[E4 报告](../docs/experiments/e4-scaffolding-tax.md) ·
[对照 run](../evals/runs/20261018T155840Z-fa9db83-compare/report.md)

**不能证明什么：** 只有 9 条任务、2 次重复、一个模型；没有置信区间。成功率打平不能说
「codelotte 更可靠」；三组不是同策略 A/B，执行纪律不在验收范围内。

## 5. E3 失败归因

| 指标 | 数值 | 来源 |
|---|---|---|
| 标注语料 | 15 条失败轨迹（五类各 3 条） | [labels.jsonl](../evals/attribution/labels.jsonl) |
| 规则分类准确率 | **15/15（100%）** | [归因报告](../evals/attribution/attribution-report.md) |
| 逐类精确率 / 召回率 / F1 | 全为 **1.000** | 同上 |
| 宏观 F1 | **1.000** | 同上 |
| 混淆矩阵 | 全部在对角线 | 同上 |
| 真实失败分布 | codelotte **0 条**失败；非 codelotte 23 条（裸 API，不归因）；控制组 42 条、压缩回归 124 条按口径跳过 | 同上 |

**不能证明什么：** 语料是作者按五类构造的草稿，规则与样本同源，有天花板效应。
真实跑数里 codelotte 零失败，说明任务集把失败压到了地板——当前没有真实失败分布可谈。

## 6. E5 防御有效性

| 证据 | 结果 | 来源 |
|---|---|---|
| 死循环三层防御（5 个正向剧本） | **5/5 按层拦截**（repeat / stagnation / circuitBreaker / terminate） | [E5 报告](../docs/experiments/e5-defense-effectiveness.md) |
| 真实模型死循环压力（同一命令跑 10 次） | **3/3 防线介入**（stagnation + reinject），任务仍完成 **3/3** | 同上 |
| 正常剧本误报（40 轮不同调用、失败重试、未到阈值重复） | **0/3** | 同上 |
| prompt injection（5 条任务 × 真实跑数 = 004/005 + 010–012） | **27/27 未执行注入** | 同上 |
| 真实正常任务误报（A 桶 31 条案例） | **0/31 出现 guardrail 事件** | 同上 |
| E5 新增跑数 | 18 条案例 / 137 次调用 / ¥0.161702 / 163.2s（峰值时段，Docker） | [防御报告](../evals/defense/defense-report.md) |

**不能证明什么：** 死循环剧本是脚本化模型行为；真实压力只有 1 条自建任务、3 次重复。
注入拦截是模型行为测试，不是运行时过滤器，只覆盖 5 条自建任务；误报审计只认
`guardrail` 事件，不代表语义上零误拦。

## 7. 压缩 v0 基线与演示

| 指标 | 数值 | 来源 |
|---|---|---|
| 压缩 v0 基线 | 12 条案例、112 次调用、¥0.265493、约 5 分钟 | [基线报表](../evals/runs/20261017T173510Z-037104e/report.md) |
| k=0/1/3/5 完成率 | 3/3、3/3、3/3、3/3 | 同上 |
| k=1/3/5 事实保留率 | 9/9、27/27、45/45 | 同上 |
| 30 秒演示 | 40 条记录、7 次模型调用、约 9 秒、**¥0.004394**、缓存命中 86% | [会话 HTML](../docs/examples/session-demo-fix-bug.html) |
| 现场演示实测（2026-10-19） | **12.3s**、7 次调用、**¥0.009622**（峰值）、缓存 87% | [rehearsal-session-20261019.md](rehearsal-session-20261019.md) |
| 快速开始 | 全流程 17 秒（clone <1s + `uv sync` 3s + 版本/dry-run 2s + 真实任务 12s；热缓存） | [quickstart 实测](../docs/demo/quickstart-validation.md) |

## 8. 一页话术

**30 秒版本：**

> 我独立做了一个终端 coding agent，重点不是「能改文件」，而是把 harness 的
> 成功率、成本、失败与防御做成可复现的数字。正式评测 27/27、pass^3 9/9；
> 同模型对照里和 mini-swe-agent 成功率打平，但快 33.5%、贵 15.4%；
> 压缩模板把长任务保留率从 87.8% 提到 93.3%、成本降 23.1%；
> 注入 27/27 未执行、正常任务误报 0/31。标注还有作者草稿的部分，我在报表里都标了 ⚠。

**主动说出的三个限制：**

1. 多数实验只有 1–2 次重复，没有置信区间；
2. judge / 归因语料尚未独立复核，κ / 准确率有天花板；
3. dogfood 连续记录还没开始（0 天 / 0 个自产 PR），不把这条写进已完成的成果。

**不要说：**

- 「压缩无损」——短任务到天花板，长任务保留率 83–97%；
- 「完全防注入」——只覆盖 5 条自建任务，是行为测试；
- 「归因准确率 100% 可泛化」——作者草稿语料、规则与样本同源；
- 「codelotte 比 mini-swe-agent 更好」——成功率打平，差异是成本–时延取舍。
