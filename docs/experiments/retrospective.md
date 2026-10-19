# 复盘：我怎么量化“记忆折叠”和“省钱”

> 这篇文章回答面试里最容易被追问的两件事：
> **你怎么知道压缩没有把 agent 压傻？** 和 **你怎么证明成本真的降下来了？**
> 数字来自 E1 / E2 的可复现跑数；E2 的反事实是 usage 重算的理论值，不是重跑模型。

## 1. 先给结论

1. **压缩没有把任务做挂，但质量差只在长任务上出现**：6 条短任务 × k=0/1/3/5 ×
   3 个组合完成率/保留率 100%；补跑 007–009 三条长任务后，完成率仍 100%，
   保留率降到 **83%–97%**。
2. **三节摘要模板省钱，长任务上还更稳**：短任务同一 k 比七项模板便宜
   **22.8%–33.5%**，长任务总成本 **−23.1%**，保留率 **93.3% vs 87.8%**；
   但只有 1 次重复，k=0 控制就有约 18% 的成本噪声，所以这些是“方向 + 量级”，
   不是精确效应。
3. **“保留两个 turn”不是质量优化，是可达性优化**：总成本 +15.8% 是因为多做了压缩；
   按有效案例算约便宜 3.5%，让 turn 数偏少的任务也能压满 5 次；保留率没有提高。
4. **缓存与低谷时段合起来，实际成本只有“无缓存 + 全峰价”的约 19%**：
   两轮真实跑数命中率 **89.0% / 89.4%**，总节省 **80.8% / 81.4%**。
5. **成功率和成本是两件事**：E4 里 codelotte 与 mini-swe-agent 都是 18/18，
   但 codelotte 贵 15.4%、快 33.5%。“我的 harness 更好”必须说清是哪一个维度更好。

## 2. E1：压缩质量怎么量

### 2.1 不是“看它有没有忘”，而是把“忘”变成可重复的探针

每次强制压缩后，立刻用**压缩后的上下文**问三个固定问题：任务目标 / 已完成步骤 /
关键约束；答案不写回任务会话，只用于评分。每个问题预定义若干事实组（可接受替代表述），
事实在整段回答里出现即算保留；只写错编号段记 `misplaced`，不扣分但保留证据。

这套做法的好处是便宜、确定、可重复；坏处是关键词代理不等于语义等价——所以报表里
同时留了 `annotations.csv` 给人工复核。

### 2.2 三个组合，控制两个变量

| 组合 | 切点 | 摘要 | 结果 |
|---|---|---|---|
| minimal/seven | 最近 1 个 turn | 七项 | 基线 |
| minimal/compact | 最近 1 个 turn | 三节 | k=5 成本 −22.8% |
| wide/seven | 最近 2 个 turn | 七项 | short k=5 +15.8%，但 6/6 有效（baseline 5/6） |

长任务补充（007–009，36 条案例）：完成率仍 100%，保留率 83–97%；compact 93.3%、
成本 −23.1%，wide 86.7%、+2.2%。

完整曲线见 [e1-compaction-curve.md](e1-compaction-curve.md)。

### 2.3 我从 E1 学到什么

- **先看“有效案例”**：005 在 minimal 下 k=5 只压到 3 次；如果只看完成率，
  100% 会掩盖“这个点根本没压满”。压缩实验必须把无效点单独列出来。
- **模板差异先体现在成本，不一定体现在分数**：这批任务太短，三节模板没丢事实；
  长任务上“决策/文件清单”可能才是关键，需要单独加 checkpoint 再测。
- **“多留上下文”不是免费的**：wide 总成本 +15.8%（多做了压缩），按有效案例反而
  便宜约 3.5%；收益只是可达性，不要把它当成质量优化。

## 3. E2：成本怎么量

### 3.1 不重跑模型，用 usage 做反事实

从每条案例的会话 `usage` 记录里拿 input/output/cache hit/miss/period，然后重算：

- **实际**：记录里已经发生的金额；
- **无缓存**：命中 token 全部按未命中价；
- **全峰价**：同一份 usage 全部按峰价（低谷 ×2）；
- **无缓存 + 全峰价**：两者都去掉。

两轮真实跑数（27 案例正式 run / 18 案例 E4 codelotte）：

| 指标 | 正式 run | E4 codelotte |
|---|---:|---:|
| 缓存命中率 | 89.0% | 89.4% |
| 实际成本 | ¥0.205832 | ¥0.128218 |
| 无缓存 + 全峰价 | ¥1.071706 | ¥0.688182 |
| 总节省 | **80.8%** | **81.4%** |

命中率随调用序号从 81.6% 升到 90%+，与确定性前缀的预期一致；但这不是关缓存的
对照实验，命中率上升也包含正常前缀增长。

### 3.2 我从 E2 学到什么

- **缓存收益是真实且可归因的**：第一条请求就有 82% 命中（system/工具 schema/任务前缀
  稳定），后面越长越高；无缓存会把成本抬到 2.6 倍。
- **off-peak 是确定性折扣**：低谷价 = 峰价 × 0.5；同一份 usage 全峰价正好 2 倍。
  非紧急批量跑放低谷，是工程上最没有争议的省钱手段。
- **反事实必须说清楚**：这不是“关掉缓存重跑一遍”，也不是“在高峰重跑一遍”。
  它是从 usage 重算的理论值；面试时主动说这句，比多报一个百分数更加分。

## 4. 一个反直觉的结果：成功率打平

E4 里 codelotte 和 mini-swe-agent 都是 18/18；codelotte 成本高 15.4%、调用多 26.3%，
但每条案例快 33.5%。这推翻了“任务变复杂就会拉开成功率”的预期，也说明：

- **scaffolding tax 不一定是成功率税**，也可能是成本–时延取舍；
- 如果目标是单位成本最低，mini 在这批任务上更好；如果目标是交互延迟，codelotte 更好；
- 想把成功率拉开，需要更长任务链、不同模型或更严格的预算，而不是继续加同量级题。

调试过程中还发现一个 Windows 陷阱：mini 的 `LocalEnvironment` 用 `shell=True` 会落到
`cmd.exe`，而它的提示词假设 bash；修复前 007 是“267s/超时”，改用 Git Bash 后
3–5 次调用通过。**这类环境 bug 如果不查，会把基础设施问题写成模型能力差异。**

## 5. 局限与下一步

- 短任务 6 条 + 长任务 3 条、各 1 次重复（E1）；9 条任务、2 次重复（E4）
  ——没有置信区间。
- checkpoint 是关键词代理；需要人工复核与更长的真实任务。
- 成本反事实只覆盖会话 usage；压缩探针不写回会话，不在 E2 报表里。
- 下一步：E1 扩到 30+ 条、k 扩到 10，加“决策/文件清单”专项 checkpoint；
  E2 在真实高峰跑一次同任务集，验证反事实与实测的偏差；E4 换更弱模型看成功率是否分化。

## 6. 面试版三句话

- “我把压缩质量变成了每次压缩后的固定探针 + 事实组评分，6 条短任务 + 3 条长任务 ×
  4 个 k × 3 个策略/模板跑出 108 条可复现案例。”
- “三节摘要模板在短任务上把成本降了 22.8%–33.5%，在长任务上既便宜 23.1%、
  保留率还从 87.8% 提到 93.3%（单次抽样，k=0 控制有约 18% 噪声）；
  ‘多留一个 turn’只买到高 k 的可达性，没有买到更高的保留率。”
- “缓存 + 低谷让实际成本只有无缓存+全峰价的约 19%；但我也会主动说，这是 usage
  重算的反事实，不是重跑。”

## 7. English summary

**What I measured.** E1 turns compaction quality into a repeatable probe: after every
forced compaction the agent answers three fixed questions (goal, progress, constraints)
from the compacted context, and a deterministic fact-group scorer reports retention.
Across 6 short tasks, completion and valid retention were both 100% (ceiling), so the
useful signal was cost; a supplement with three longer tasks kept completion at 100%
but retention fell to 83–97%. A three-section summary template cut cost by 22.8–33.5%
at the same k (25.9% over the whole short-task curve) with no retention loss; on the
long tasks it was 23.1% cheaper and retained 93.3% vs 87.8%. With one repetition and
~18% control noise, read these as direction and magnitude, not precise effects. Keeping two turns per cut
(instead of one) cost 15.8% more overall because it performed more compactions, but was
about 3.5% cheaper per valid case; its benefit was reaching 5/5 compactions on short-turn
tasks, not higher retention.

E2 reprices the recorded usage instead of rerunning the model: actual vs no-cache
(all hits charged as misses) vs all-peak vs both. Two real runs showed 89.0% / 89.4%
cache hit rates and a combined cost reduction of 80.8% / 81.4% against the
no-cache + peak counterfactual. The hit rate rose from 81.6% on the first call to
90%+ later in the trajectory, consistent with deterministic serialization and prefix
discipline (not a cache-off controlled A/B). E4 also showed a useful negative result: two capable harnesses
can tie on success while differing by 15.4% in cost and 33.5% in wall-clock time, so
"better" has to be stated per dimension.

## 8. 证据

- E1：[docs/experiments/e1-compaction-curve.md](e1-compaction-curve.md) ·
  [`evals/runs/20261018T165516Z-8a01d9f/report.md`](../../evals/runs/20261018T165516Z-8a01d9f/report.md)
- E2：[docs/experiments/e2-cost-curve.md](e2-cost-curve.md) ·
  [`evals/cost/cost-report.md`](../../evals/cost/cost-report.md)
- E4：[docs/experiments/e4-scaffolding-tax.md](e4-scaffolding-tax.md)
- 复现脚本：[scripts/reproduce-e1-e2.sh](../../scripts/reproduce-e1-e2.sh)
