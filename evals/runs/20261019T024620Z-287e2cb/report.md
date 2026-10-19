# 评测报表（通用测评）

> 一轮跑数：1 条任务 × 3 次重复 = 3 条案例。数字与原始轨迹同目录，可用文末命令复现。

## 结论速览

- 任务：1 · 案例：3 · 通过：3/3 (100%)
- pass^3：1/1 条任务全部重复通过
- 总成本：¥0.079322 · 总耗时：74.6s
- 计费时段：峰值 62

| 任务 | 桶 | 尝试 | 通过 | 成功率 | pass^3 | 模型调用 | 总成本 | judge | 平均耗时 | 计费时段 |
|---|---|---|---|---|---|---|---|---|---|---|
| 013-repeat-pressure | B | 3 | 3 | 3/3 (100%) | ✅ | 62 | ¥0.079322 | — | 24.9s | 峰值 62 |

读法：

- **成功率** = 通过案例 / 尝试案例；运行错误也算失败，不剔除。
- **pass^3** = 该任务的全部 3 次重复都通过；少跑一次或错一次都记 ❌。
- 成本来自每次模型调用的 usage 记录；时段是调用当时的实际峰谷判定。

## 复现锁定

| 项 | 值 |
|---|---|
| run id | `20261019T024620Z-287e2cb` |
| 开始 / 结束 | 2026-10-19T02:46:20.044000+00:00 → 2026-10-19T02:47:34.866573+00:00 |
| git ref | `287e2cbf8d8693478f3193649b032897c6eb63e9` |
| 工作树有改动 | 是（指纹 54ab9ac0cbd625a77de5ffa5c680750d64c484615a7b75081803525f6b15cba4） |
| harness / 类型 | `codelotte` / agent |
| harness 版本 / 隔离 | 0.1.0 / docker |
| 模型 / 思考档位 | `deepseek-flash` / `high` |
| 上下文窗口 | 1000000 |
| 每个任务重复次数 | 3 |
| 随机种子 | 0 |
| Python / codelotte | 3.13.13 / 0.1.0 |
| uv.lock SHA-256 | `b64ada6fe8c5faea366310bae5cc70fe25a2b98ce6baf8676e26d72c0531caf7` |
| 命令 | `codelotte eval run --tasks evals/loop-tasks --repeat 3 --out evals/runs` |

任务指纹与仓库快照：

| 任务 | 桶 | 语义指纹 | 仓库快照 |
|---|---|---|---|
| 013-repeat-pressure | B | `87bdc3ed8b50518bdcec97f7709f0a3bda7074944366826c58d2f05f538df1d1` | — |

## 逐案例结果

| 任务 | 重复 | 通过 | 标记 | 验收 / 错误 | judge | 模型调用 | 成本 | 耗时 | 计费时段 | 轨迹 |
|---|---|---|---|---|---|---|---|---|---|---|
| 013-repeat-pressure | r1 | ✅ | — | 验收通过 | — | 18 | ¥0.022434 | 21.5s | 峰值 18 | `sessions/013-repeat-pressure-r1/20261019T024620Z_ed40bce2.jsonl` |
| 013-repeat-pressure | r2 | ✅ | — | 验收通过 | — | 22 | ¥0.030519 | 27.8s | 峰值 22 | `sessions/013-repeat-pressure-r2/20261019T024641Z_8b24ee3f.jsonl` |
| 013-repeat-pressure | r3 | ✅ | — | 验收通过 | — | 22 | ¥0.026370 | 25.2s | 峰值 22 | `sessions/013-repeat-pressure-r3/20261019T024709Z_c86ead24.jsonl` |

## LLM judge

无（没有任务声明 `[verifier.judge]`，或确定性检查先失败；确定性验收优先）。

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
codelotte eval run --tasks evals/loop-tasks --repeat 3 --out evals/runs
```
