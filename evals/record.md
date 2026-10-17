# 评测跑数记录

> `evals/runs/` 下每一轮评测一个目录；本文是所有评测（通用测评 + 专用测评）的
> 索引与记录约定。操作手册：[run.md](run.md)（通用测评）·
> [compaction.md](compaction.md)（专用测评 - 压缩回归 v0）。

## 1. 目录约定

```text
evals/runs/
└── 20261017T201602Z-99d0d4d/
    ├── report.md
    ├── report.json
    ├── sessions/
    └── workspaces/
```

- 目录名：`<UTC 时间>-<git ref 前 7 位>/`；同名冲突时自动加 `-2`、`-3`。
- **不手工编辑**跑数目录；要新数字就重跑，历史目录不覆盖。
- 提交跑数证据时，在下面的记录表加一行；CI 冒烟产物不进仓库（`evals/runs-ci/` 已忽略）。

## 2. 两类评测的产出

| 评测 | 命令 | 产出 |
|---|---|---|
| 通用测评 | `eval run` | `report.md` / `report.json` / `sessions/` / `workspaces/` |
| 专用测评 - 压缩回归 v0 | `eval compaction` | 同上，另有 `annotations.csv` / `checkpoints.jsonl` |

- **`report.md`**：人读报表。通用测评看 pass^N、成功率、成本/耗时；压缩回归看完成率、
  有效案例、状态保留率。
- **`report.json`**：机器可读的 meta + cases；通用测评另有 summaries，压缩回归的
  checkpoint 细节在 cases 里。
- **`sessions/`**：每条案例的 append-only JSONL，含工具调用、usage、压缩等完整轨迹。
- **`workspaces/`**：每条案例的最终工作区（agent 实际产物）。
- **失败定位**：通用测评的失败案例在 `report.md` 的“失败案例”段；压缩回归在逐案例表 +
  checkpoint 明细。两者都给出会话路径。

## 3. 记录表

| run | 类型 | 结果 |
|---|---|---|
| `20261017T173510Z-037104e` | 专用测评 - 压缩回归 v0 | v0 基线：3 任务 × k=0/1/3/5 × 1 次，12 条案例全部有效，112 次模型调用，¥0.265493；见 `report.md` |
| `20261017T201602Z-99d0d4d` | 通用测评 | 冒烟：1 条 B 任务 × 3 次重复，pass^3 3/3，18 次调用，¥0.011544（约 20 秒） |

两条都是开发期跑数，`report.json` 的 `git_dirty` 为 true，并记录了工作树指纹；
复现时以任务指纹、模型参数和完整命令为准。

## 4. 复现与对比

- `report.json` 的 `meta` 在开跑前锁定：git ref / 工作树指纹、seed、Python/codelotte
  版本、`uv.lock` SHA-256、模型/窗口/阈值、任务语义指纹与快照 SHA、完整命令。
- 同一命令重跑得到新目录；模型没有固定 temperature，数字会波动。看趋势用 `--repeat`。
- 想拿“干净的 git ref”：先提交，再重跑；未提交跑数也会被工作树指纹锁住。
- 对比两次跑数：并排看两个 `report.md` 的结论速览，或 diff `report.json`。

## 5. 快速入口

```bash
# 通用测评：全部任务 × 3 次
uv run codelotte eval run

# 专用测评 - 压缩回归 v0：强制压缩 k=0/1/3/5
uv run codelotte eval compaction --k 0,1,3,5

# 打开最新报表
# evals/runs/<新目录>/report.md
```

详细参数、任务格式、CI 冒烟见 [run.md](run.md)；压缩评分与基线解读见
[compaction.md](compaction.md)。
