# 简历 bullet（真实数字版）

> 对照 [PLAN.md §8](../PLAN.md) 的草稿，把所有占位符替换为**截至 2026-10-19 的实测数字**。
> 每条后面给出证据来源与不能夸大的边界。投递前按文末「更新规则」刷新一次。
> 需要整段项目经历（概述、5 条技术介绍、技术栈、关键词索引）时，见
> [project-experience-v1.md](project-experience-v1.md)。

## 四条 bullet

### 1. 项目与实现

> 独立设计开发 **codelotte**：一款 minimal-core 终端 coding agent（Python 3.13 / Textual /
> 自研 LLM 接入层 + 内联 SSE），从 0 实现 agent loop、append-only 会话树、权限层 × Docker
> 双层执行安全、双触发上下文压缩与可复现评测体系；GitHub 开源（**1 star**，截至 2026-10-19）。

**证据：** [README](../README.md) · [ADR 索引](../docs/adr/README.md) · 39 个提交
（数据快照）、票据 01–22。
**边界：** 当前只实现 `openai-completions` wire protocol；`anthropic-messages` 是协议抽象预留，
未实现（见 [ADR-0004 的实现状态](../docs/adr/0004-self-built-llm-adapter.md)）。
**不要写：** 「双协议已实现」「多模型已实测」。

### 2. 质量闭环与量化改进

> 构建 agent 质量闭环：**9 条任务 × 3 次正式评测 27/27 通过、pass^3 9/9**，配套
> oracle / no-op / cheating 控制 agent 自检与 CI 冒烟；量化 harness 改进——
> 压缩模板把长任务关键状态保留率 **87.8% → 93.3%**、成本 **−23.1%**；
> 缓存 + off-peak 使实际成本较「无缓存 + 全峰价」反事实 **−80.8%**（¥1.0717 → ¥0.2058）。

**证据：** [正式 run](../evals/runs/20261018T154112Z-fa9db83/report.md) ·
[controls](../evals/runs/20261018T154851Z-fa9db83-controls/report.md) ·
[E1](../docs/experiments/e1-compaction-curve.md) · [E2](../docs/experiments/e2-cost-curve.md)。
**分母：** 27 = 9 任务 × 3 次；长任务保留率 = 84/90 vs 79/90；成本反事实 = 从 27 案例、
188 次调用的 usage 重算，不是关缓存重跑。
**边界：** E1 单次重复，成本波动约 18%，百分比读作方向 + 量级；E2 是反事实，不是 A/B。

### 3. 安全、防御与失败归因

> 设计权限层 × Docker 沙箱双层执行安全与死循环三层防御，把 prompt injection 与死循环
> 做成可复现用例：注入 **27/27 未执行**、死循环剧本 **5/5 按层拦截**、真实模型压力
> **3/3 防线介入且任务仍完成**、正常任务误报 **0/31**；失败归因 **15/15、宏观 F1 1.000**
>（作者草稿语料，待独立复核）。

**证据：** [E5](../docs/experiments/e5-defense-effectiveness.md) ·
[E3](../docs/experiments/e3-attribution-accuracy.md) ·
[SECURITY.md](../SECURITY.md)。
**边界：** 注入是 5 条自建任务上的模型行为测试，不是运行时过滤器；归因语料是
`author-draft`，规则与样本同源，有天花板效应。**不要写「完全防注入」或「归因可泛化」。**

### 4. Dogfood（当前暂不使用）

> 连续 **0 周**以自研 agent 开发自身（dogfood），累计合并 **0 个**自产 PR。

**当前真实数字：0 天、0 个自产 PR。** 截至 2026-10-19，[dogfood 日志](../docs/dogfood/log.md)
只有表头，没有记录；`main` 上也没有 merge commit。**这条暂不投递**，等日志有 ≥2 周连续记录
后再启用。启用时只填日志能查到的数字，不要估算；替换模板：

```text
连续 <日志连续周数> 周以自研 agent 开发自身（dogfood），累计合并 <日志中的 PR 数> 个自产 PR。
```

## 数字来源速查

| 数字 | 值 | 来源 | 刷新命令 |
|---|---:|---|---|
| stars | 1 | GitHub API | `gh api repos/szh1007/codelotte --jq .stargazers_count` |
| commits | 39 | git | `git log --oneline \| wc -l` |
| 正式评测 | 27/27、pass^3 9/9 | `evals/runs/20261018T154112Z-fa9db83/report.md` | 重跑 `eval run`，不要手改 |
| 单任务成本 | ¥0.00762（¥0.205832 / 27） | 同上 | 同上 |
| 控制 agent | oracle 9/9、no-op 0/9、cheating 0/9 | `...-controls/report.md` | `codelotte eval controls` |
| E1 长任务保留率 | 93.3% vs 87.8% | `docs/experiments/e1-compaction-curve.md` | 重跑 `eval compaction` |
| E1 长任务成本 | −23.1% | 同上 | 同上 |
| E2 缓存命中 | 89.0% | `evals/cost/cost-report.md` | `codelotte eval cost --run ...` |
| E2 总节省 | 80.8% | 同上 | 同上 |
| E3 归因 | 15/15、macro F1 1.000 | `evals/attribution/attribution-report.md` | `codelotte eval attribute` |
| E4 对照 | 18/18 vs 18/18 vs 0/18 | `evals/runs/20261018T155840Z-fa9db83-compare/report.md` | 重跑 `eval compare` |
| E5 注入 | 27/27 | `docs/experiments/e5-defense-effectiveness.md` | 重跑注入任务 |
| E5 死循环 | 5/5 剧本、3/3 真实压力 | 同上 | `codelotte eval defense` |
| E5 误报 | 0/31 | 同上 | 同上 |
| 测试 | 594 passed, 8 deselected | `uv run pytest -q` | 重跑 |
| dogfood | 0 天 / 0 PR | `docs/dogfood/log.md`、`git log --merges` | 读日志，不估算 |

## 投递前的更新规则

1. **stars 会变**：投递前重新查一次；如果仍是 1，保留括号里的日期，避免面试时被问「现在多少」。
2. **测试数会变**：以 `uv run pytest -q` 的最后一行为准；README 与本文同步更新。
3. **任何评测数字**：只从 `report.md/json` 抄，不手算、不估算；改了口径就新增 run，不改旧 run。
4. **dogfood 未开始就不要写**；开始后按日志里的连续天数与 PR 数填，失败任务也照实写。
5. **协议能力**：只有真正实现并端到端验证后，才能把 `anthropic-messages` 写进 bullet 1。

## 面试时的口头补充

- 「stars 只有 1」：这是 2026-10-13 起的个人求职作品，不是社区项目；我用可复现实验代替热度背书。
- 「为什么没有 dogfood 数字」：日志脚手架已就位，但连续记录还没开始；我不把计划中的事写进成果。
- 「27/27 是不是任务太简单」：是，任务集有天花板；长任务保留率已经降到 83–97%，
  下一步是更长任务链和多模型，而不是继续加同量级任务。
