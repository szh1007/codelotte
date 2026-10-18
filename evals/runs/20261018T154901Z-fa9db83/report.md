# 评测报表（通用测评）

> 一轮跑数：3 条任务 × 1 次重复 = 3 条案例。数字与原始轨迹同目录，可用文末命令复现。

## 结论速览

- 任务：3 · 案例：3 · 通过：3/3 (100%)
- pass^1：3/3 条任务全部重复通过
- 总成本：¥0.041690 · 总耗时：58.5s
- 计费时段：低谷 17

| 任务 | 桶 | 尝试 | 通过 | 成功率 | pass^1 | 模型调用 | 总成本 | judge | 平均耗时 | 计费时段 |
|---|---|---|---|---|---|---|---|---|---|---|
| 006-code-review | A | 1 | 1 | 1/1 (100%) | ✅ | 5 | ¥0.004642 | 1 次 / ¥0.001136 ⚠ | 8.4s | 低谷 5 |
| 101-concurrency-review | A | 1 | 1 | 1/1 (100%) | ✅ | 7 | ¥0.009976 | 1 次 / ¥0.002882 ⚠ | 17.4s | 低谷 7 |
| 102-api-design-tradeoffs | A | 1 | 1 | 1/1 (100%) | ✅ | 5 | ¥0.027072 | 1 次 / ¥0.005069 ⚠ | 32.7s | 低谷 5 |

读法：

- **成功率** = 通过案例 / 尝试案例；运行错误也算失败，不剔除。
- **pass^1** = 该任务的全部 1 次重复都通过；少跑一次或错一次都记 ❌。
- 成本来自每次模型调用的 usage 记录；时段是调用当时的实际峰谷判定。

## 复现锁定

| 项 | 值 |
|---|---|
| run id | `20261018T154901Z-fa9db83` |
| 开始 / 结束 | 2026-10-18T15:49:01.072072+00:00 → 2026-10-18T15:50:00.030715+00:00 |
| git ref | `fa9db8357984efe04fd591f8f280a920c787f1f1` |
| 工作树有改动 | 是（指纹 b2ab19fdde328b9761fe62c968082cbc222da1d2dd9e4faa1c601e41c3434b85） |
| harness / 类型 | `codelotte` / agent |
| harness 版本 / 隔离 | 0.1.0 / docker |
| 模型 / 思考档位 | `deepseek-flash` / `high` |
| 上下文窗口 | 1000000 |
| 每个任务重复次数 | 1 |
| 随机种子 | 0 |
| Python / codelotte | 3.13.13 / 0.1.0 |
| uv.lock SHA-256 | `b64ada6fe8c5faea366310bae5cc70fe25a2b98ce6baf8676e26d72c0531caf7` |
| 命令 | `codelotte eval run --tasks evals/judge-tasks --repeat 1` |

任务指纹与仓库快照：

| 任务 | 桶 | 语义指纹 | 仓库快照 |
|---|---|---|---|
| 006-code-review | A | `559a9a784c2f3aafa22e8d1921e5902f5314fdf290f498bd6ff988b3a71959f1` | — |
| 101-concurrency-review | A | `09400d69bf0aa8e32a3c7716057cd5a5767b860837fbf562b8dfdeec5ad0681c` | — |
| 102-api-design-tradeoffs | A | `5f16cb247d8d58bc2c7493e8ff901d0ba76b3005de1b4572485f1188d08aa6f2` | — |

## 逐案例结果

| 任务 | 重复 | 通过 | 标记 | 验收 / 错误 | judge | 模型调用 | 成本 | 耗时 | 计费时段 | 轨迹 |
|---|---|---|---|---|---|---|---|---|---|---|
| 006-code-review | r1 | ✅ | — | 验收通过；judge overall=1.00（阈值 0.70，通过）；⚠ 标注者 author-draft 尚未复核，κ 是草稿值 | 1.00 ✅ ⚠ | 5 | ¥0.004642 | 8.4s | 低谷 5 | `sessions/006-code-review-r1/20261018T154901Z_7f02932f.jsonl` |
| 101-concurrency-review | r1 | ✅ | — | 验收通过；judge overall=1.00（阈值 0.70，通过）；⚠ 标注者 author-draft 尚未复核，κ 是草稿值 | 1.00 ✅ ⚠ | 7 | ¥0.009976 | 17.4s | 低谷 7 | `sessions/101-concurrency-review-r1/20261018T154909Z_d78169c3.jsonl` |
| 102-api-design-tradeoffs | r1 | ✅ | — | 验收通过；judge overall=1.00（阈值 0.70，通过）；⚠ 标注者 author-draft 尚未复核，κ 是草稿值 | 1.00 ✅ ⚠ | 5 | ¥0.027072 | 32.7s | 低谷 5 | `sessions/102-api-design-tradeoffs-r1/20261018T154927Z_f1dba3f1.jsonl` |

## LLM judge

- `006-code-review` r1：overall 1.00（通过）；κ=1.00（20 样本）；⚠ 不可靠
  - ⚠ 标注者 author-draft 尚未复核，κ 是草稿值
  - correctness 1.00：Identifies `for i in range(n + 1):` as the bug and gives `for i in range(n):` as the fix.
  - specificity 1.00：Quotes the exact buggy line and explains both n = 0 and n = len(values) failure modes with evidence.
  - clarity 1.00：Uses exactly the three requested sections and is concise.
- `101-concurrency-review` r1：overall 1.00（通过）；κ=1.00（20 样本）；⚠ 不可靠
  - ⚠ 标注者 author-draft 尚未复核，κ 是草稿值
  - correctness 1.00：Identifies the unsynchronized read-modify-write, explains lost update, states GIL does not make it atomic, and fixes with a module-level threading.Lock.
  - specificity 1.00：Quotes the exact racy lines, gives a concrete two-thread interleaving, and names the shared counter state.
  - clarity 1.00：Uses exactly the requested Bug/Why/Fix sections, stays on topic, and is concise.
- `102-api-design-tradeoffs` r1：overall 1.00（通过）；κ=1.00（20 样本）；⚠ 不可靠
  - ⚠ 标注者 author-draft 尚未复核，κ 是草稿值
  - tradeoff_depth 1.00：Clearly chooses batch endpoint A and compares A vs B on latency, retries/idempotency, partial failure, pagination, and versioning with concrete reasoning and numbers.
  - constraint_coverage 1.00：Covers all requirements: 500-item batches, per-item idempotency keys, per-item status/errors, no double charge, sub-2s progress feedback, pagination, and versioning.
  - clarity 1.00：Recommendation and retry flow are explicit, structured, and easy to follow; prose is concise despite the detailed contract.

## 失败归因

无失败案例。

## 失败案例

无。

## 口径

- 任务由 TOML 定义：`id` / `bucket` / `instruction` / `setup`（初始文件或仓库快照）/ `verifier` / 预算；任务文件是可信输入。
- 验收阶梯：命令式检查（command / python / 文件比对）先跑；只有任务显式声明 `[verifier.judge]` 且确定性检查通过时才调用 judge，确定性失败不会调用 judge。
- judge 的分数/理由/κ 在本报表的“LLM judge”段；judge 成本计入总成本。κ 低于任务阈值、样本 <20、校准缺失或标注者为草稿都会标 ⚠，但不会静默丢弃分数。
- 仓库快照在开跑前解析成 commit SHA 并写进上表；同一轮所有重复使用同一个快照。
- 原始轨迹在 `sessions/`，最终工作区在 `workspaces/`；失败案例的会话路径见上表与失败案例段。
- 通用测评使用生产压缩策略（不强制压缩）；压缩回归仍用 `codelotte eval compaction`。

## 复现

```bash
codelotte eval run --tasks evals/judge-tasks --repeat 1
```
