# 评测报表（通用测评）

> 一轮跑数：1 条任务 × 1 次重复 = 1 条案例。数字与原始轨迹同目录，可用文末命令复现。

## 结论速览

- 任务：1 · 案例：1 · 通过：1/1 (100%)
- pass^1：1/1 条任务全部重复通过
- 总成本：¥0.003675 · 总耗时：6.9s
- 计费时段：低谷 4

| 任务 | 桶 | 尝试 | 通过 | 成功率 | pass^1 | 模型调用 | 总成本 | judge | 平均耗时 | 计费时段 |
|---|---|---|---|---|---|---|---|---|---|---|
| 006-code-review | A | 1 | 1 | 1/1 (100%) | ✅ | 4 | ¥0.003675 | 1 次 / ¥0.001007 ⚠ | 6.9s | 低谷 4 |

读法：

- **成功率** = 通过案例 / 尝试案例；运行错误也算失败，不剔除。
- **pass^1** = 该任务的全部 1 次重复都通过；少跑一次或错一次都记 ❌。
- 成本来自每次模型调用的 usage 记录；时段是调用当时的实际峰谷判定。

## 复现锁定

| 项 | 值 |
|---|---|
| run id | `20261018T123909Z-5264236` |
| 开始 / 结束 | 2026-10-18T12:39:09.665014+00:00 → 2026-10-18T12:39:16.696575+00:00 |
| git ref | `526423664432d9c692a27f90949bf6f533d03275` |
| 工作树有改动 | 是（指纹 7be3c7ee779ac479bb4eba59eb0196d9b6c10a0386566da8c7fd0dddc4aa27a4） |
| harness / 类型 | `codelotte` / agent |
| harness 版本 / 隔离 | 0.1.0 / local |
| 模型 / 思考档位 | `deepseek-flash` / `high` |
| 上下文窗口 | 1000000 |
| 每个任务重复次数 | 1 |
| 随机种子 | 0 |
| Python / codelotte | 3.13.13 / 0.1.0 |
| uv.lock SHA-256 | `b64ada6fe8c5faea366310bae5cc70fe25a2b98ce6baf8676e26d72c0531caf7` |
| 命令 | `codelotte eval run --tasks evals/judge-tasks --task 006-code-review --repeat 1 --out evals/runs --no-sandbox` |

任务指纹与仓库快照：

| 任务 | 桶 | 语义指纹 | 仓库快照 |
|---|---|---|---|
| 006-code-review | A | `559a9a784c2f3aafa22e8d1921e5902f5314fdf290f498bd6ff988b3a71959f1` | — |

## 逐案例结果

| 任务 | 重复 | 通过 | 标记 | 验收 / 错误 | judge | 模型调用 | 成本 | 耗时 | 计费时段 | 轨迹 |
|---|---|---|---|---|---|---|---|---|---|---|
| 006-code-review | r1 | ✅ | — | 验收通过；judge overall=1.00（阈值 0.70，通过）；⚠ 标注者 author-draft 尚未复核，κ 是草稿值 | 1.00 ✅ ⚠ | 4 | ¥0.003675 | 6.9s | 低谷 4 | `sessions/006-code-review-r1/20261018T123909Z_dd8d146b.jsonl` |

## LLM judge

- `006-code-review` r1：overall 1.00（通过）；κ=1.00（20 样本）；⚠ 不可靠
  - ⚠ 标注者 author-draft 尚未复核，κ 是草稿值
  - correctness 1.00：Identifies `for i in range(n + 1):` as the bug and gives `for i in range(n):` as the fix.
  - specificity 1.00：Quotes the exact buggy line and explains both failure modes: n = 0 adds values[0], n = len(values) reads values[n] out of bounds.
  - clarity 1.00：Uses exactly the three requested sections, is concise, and does not modify bug.py.

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
codelotte eval run --tasks evals/judge-tasks --task 006-code-review --repeat 1 --out evals/runs --no-sandbox
```
