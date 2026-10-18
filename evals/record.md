# 评测跑数记录

> `evals/runs/` 下每一轮评测一个目录；本文是所有评测（通用测评 + 专用测评 +
> 对照组 + 控制 agent 自检 + LLM judge）的索引与记录约定。操作手册：[run.md](run.md)
> （通用测评、对照组、自检、judge）· [compaction.md](compaction.md)
> （专用测评 - 压缩回归 v0）。

## 1. 目录约定

```text
evals/runs/
├── 20261017T201602Z-99d0d4d/          # eval run / eval compaction
│   ├── report.md
│   ├── report.json
│   ├── sessions/
│   └── workspaces/
└── 20261017T215301Z-f2320a8-controls/ # eval compare / eval controls
    ├── report.md                      # 任务级并列 + 自检结论（controls）
    ├── report.json
    └── harnesses/
        ├── oracle/{report.md,report.json,sessions/,workspaces/}
        └── …
```

- 目录名：`<UTC 时间>-<git ref 前 7 位>/`；同名冲突时自动加 `-2`、`-3`。
- **不手工编辑**跑数目录；要新数字就重跑，历史目录不覆盖。
- 提交跑数证据时，在下面的记录表加一行；CI 冒烟产物不进仓库（`evals/runs-ci/` 已忽略）。
- judge 的资产不在 `runs/`：任务在 `evals/judge-tasks/`，样本与校准结果在
  `evals/judges/<task>/`；校准文件可以重跑覆盖（它不是历史跑数目录）。

## 2. 五类评测的产出

| 评测 | 命令 | 产出 |
|---|---|---|
| 通用测评 | `eval run` | `report.md` / `report.json` / `sessions/` / `workspaces/` |
| 专用测评 - 压缩回归 v0 | `eval compaction` | 同上，另有 `annotations.csv` / `checkpoints.jsonl` |
| 对照组 | `eval compare` | 父目录 `report.md` / `report.json` + `harnesses/<组名>/` 明细 |
| 控制 agent 自检 | `eval controls` | 同上，父报表另有“自检结论”表与 `checks` |
| LLM judge 校准 | `eval judge` | `evals/judges/<task>/calibration.json` / `.md`（不是 run 目录） |

- **`report.md`**：人读报表。通用测评看 pass^N、成功率、成本/耗时；压缩回归看完成率、
  有效案例、状态保留率；声明了 judge 的任务另有“LLM judge”段（分数/理由/κ/⚠）。
- **`report.json`**：机器可读的 meta + cases；通用测评另有 summaries，压缩回归的
  checkpoint 细节在 cases 里；judge 字段在 cases 里（`judge_*`）。
- **`sessions/`**：每条案例的 append-only JSONL，含工具调用、usage、压缩等完整轨迹。
- **`workspaces/`**：每条案例的最终工作区（agent 实际产物）。
- **失败定位**：通用测评的失败案例在 `report.md` 的“失败案例”段；压缩回归在逐案例表 +
  checkpoint 明细；对照/自检在父报表的“失败定位”段，并按组给出轨迹路径。三者都给出路径。

## 3. 记录表

| run | 类型 | 结果 |
|---|---|---|
| `20261017T173510Z-037104e` | 专用测评 - 压缩回归 v0 | v0 基线：3 任务 × k=0/1/3/5 × 1 次，12 条案例全部有效，112 次模型调用，¥0.265493；见 `report.md` |
| `20261017T201602Z-99d0d4d` | 通用测评 | 冒烟：1 条 B 任务 × 3 次重复，pass^3 3/3，18 次调用，¥0.011544（约 20 秒） |
| `20261017T223658Z-f2320a8-compare` | 对照组 | 3 组 × 5 任务 × 1 次，同一模型 `deepseek-flash` / `high`：codelotte 5/5（31 调用，¥0.015903，5.3s/案例）、mini-swe-agent 5/5（31 调用，¥0.022858，13.6s/案例）、裸单轮 API 0/5（5 调用，¥0.011245，3.4s/案例）；v0 任务太短，尚未拉开成功率 |
| `20261017T223904Z-f2320a8-controls` | 控制 agent 自检 | 5 任务 × 1 次，oracle 5/5、no-op 0/5、cheating 0/5 且 5/5 标记；零模型调用、零成本 |
| `20261018T123909Z-5264236` | 通用测评（judge） | 1 条 judge 任务 × 1 次：通过，4 次调用（3 agent + 1 judge），¥0.003675；judge overall 1.00，κ=1.00（20 样本） |

LLM judge 校准记录（不是跑数目录）：

| 日期 | 任务 | 样本 | 标注者 | κ | 一致率 | 成本 | 结论 |
|---|---|---|---|---|---|---|---|
| 2026-10-18 | `006-code-review` | 20 | `author-draft` | 1.000 | 100.0% | ¥0.033613 | ⚠ 草稿标注（κ 高但未复核）；样本刻意清晰、κ 有天花板效应，作者复核后重跑 |

以上都是开发期跑数，`report.json` 的 `git_dirty` 为 true，并记录了工作树指纹；
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

# 控制 agent 自检：离线、零成本
uv run codelotte eval controls

# 对照组：codelotte / mini-swe-agent / 裸单轮 API
uv run codelotte eval compare --repeat 1 --no-sandbox \
  --mini-python .mini-venv/Scripts/python.exe

# LLM judge 校准与 judge 任务
uv run codelotte eval judge --dry-run
uv run codelotte eval judge
uv run codelotte eval run --tasks evals/judge-tasks --task 006-code-review \
  --repeat 1 --no-sandbox

# 打开最新报表
# evals/runs/<新目录>/report.md
```

详细参数、任务格式、CI 冒烟见 [run.md](run.md)；压缩评分与基线解读见
[compaction.md](compaction.md)。
