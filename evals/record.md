# 评测跑数记录

> `evals/runs/` 下每一轮评测一个目录；本文是所有评测（通用测评 + 专用测评 +
> 对照组 + 控制 agent 自检 + LLM judge + 失败归因 + 成本曲线）的索引与记录约定。
> 总览：[README.md](README.md)；操作手册：[run.md](run.md)（通用测评、对照、自检、
> judge、归因、成本）·
> [compaction.md](compaction.md)（专用测评 - 压缩回归 v0）·
> [attribution.md](attribution.md)（归因规则与回归任务）。

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
- 归因语料在 `evals/attribution/`（可以重跑覆盖）；由失败生成的回归任务在
  `evals/regressions/`，它们是任务定义，不参与默认 `eval run`。

## 2. 八类评测的产出

| 评测 | 命令 | 产出 |
|---|---|---|
| 通用测评 | `eval run` | `report.md` / `report.json` / `sessions/` / `workspaces/` |
| 专用测评 - 压缩回归 v0 | `eval compaction` | 同上，另有 `annotations.csv` / `checkpoints.jsonl` |
| 对照组 | `eval compare` | 父目录 `report.md` / `report.json` + `harnesses/<组名>/` 明细 |
| 控制 agent 自检 | `eval controls` | 同上，父报表另有“自检结论”表与 `checks` |
| LLM judge 校准 | `eval judge` | `evals/judges/<task>/calibration.json` / `.md`（不是 run 目录） |
| 失败归因准确率 | `eval attribute` | `evals/attribution/attribution-report.md` / `.json`（不是 run 目录） |
| 失败 → 回归任务 | `eval regression` | `evals/regressions/<新 id>.toml`（不是 run 目录） |
| 成本曲线 | `eval cost` | `evals/cost/cost-report.md` / `.json`（不是 run 目录） |

- **`report.md`**：人读报表。通用测评看 pass^N、成功率、成本/耗时；压缩回归看完成率、
  有效案例、状态保留率；声明了 judge 的任务另有“LLM judge”段（分数/理由/κ/⚠）；
  通用测评/对照另有“失败归因”段（五类分布 + 逐条证据）。
- **`report.json`**：机器可读的 meta + cases；通用测评另有 summaries，压缩回归的
  checkpoint 细节在 cases 里；judge 字段在 cases 里（`judge_*`），归因字段在 cases 里
  （`failure_*`）。
- **`sessions/`**：每条案例的 append-only JSONL，含工具调用、usage、压缩等完整轨迹。
- **`workspaces/`**：每条案例的最终工作区（agent 实际产物）。
- **失败定位**：通用测评的失败案例在 `report.md` 的“失败案例”段与“失败归因”段；
  压缩回归在逐案例表 + checkpoint 明细；对照/自检在父报表的“失败定位”段，并按组
  给出轨迹路径。三者都给出路径。

## 3. 记录表

| run | 类型 | 结果 |
|---|---|---|
| `20261017T173510Z-037104e` | 专用测评 - 压缩回归 v0 | v0 基线：3 任务 × k=0/1/3/5 × 1 次，12 条案例全部有效，112 次模型调用，¥0.265493；见 `report.md` |
| `20261017T201602Z-99d0d4d` | 通用测评 | 冒烟：1 条 B 任务 × 3 次重复，pass^3 3/3，18 次调用，¥0.011544（约 20 秒） |
| `20261017T223658Z-f2320a8-compare` | 对照组 | 3 组 × 5 任务 × 1 次，同一模型 `deepseek-flash` / `high`：codelotte 5/5（31 调用，¥0.015903，5.3s/案例）、mini-swe-agent 5/5（31 调用，¥0.022858，13.6s/案例）、裸单轮 API 0/5（5 调用，¥0.011245，3.4s/案例）；v0 任务太短，尚未拉开成功率 |
| `20261017T223904Z-f2320a8-controls` | 控制 agent 自检 | 5 任务 × 1 次，oracle 5/5、no-op 0/5、cheating 0/5 且 5/5 标记；零模型调用、零成本 |
| `20261018T123909Z-5264236` | 通用测评（judge） | 1 条 judge 任务 × 1 次：通过，4 次调用（3 agent + 1 judge），¥0.003675；judge overall 1.00，κ=1.00（20 样本） |
| `20261018T154112Z-fa9db83` | 通用测评（E4 正式） | 9 任务 × 3 次：27/27 通过，pass^3 9/9，188 次调用，¥0.205832，349.0s（低谷；Docker） |
| `20261018T154901Z-fa9db83` | 通用测评（judge） | 3 条 judge 任务 × 1 次：3/3 通过，17 次调用（含 3 次 judge），¥0.041690，58.5s；三条 overall 均 1.00，κ=1.00（各 20 样本，⚠ 草稿） |
| `20261018T154851Z-fa9db83-controls` | 控制 agent 自检 | 9 任务 × 1 次：oracle 9/9、no-op 0/9、cheating 0/9 且 9/9 标记；零模型调用、零成本 |
| `20261018T155840Z-fa9db83-compare` | 对照组（E4） | 3 组 × 9 任务 × 2 次：codelotte 18/18（125 调用，¥0.128218，13.9s/案例）、mini-swe-agent 18/18（99 调用，¥0.111146，20.9s/案例）、裸 API 0/18（18 调用，¥0.280970，17.3s/案例）；实验报告 `docs/experiments/e4-scaffolding-tax.md` |
| `20261018T165516Z-8a01d9f` | 压缩回归（E1 短任务） | 6 任务 × k=0/1/3/5 × 3 组合（minimal/seven、minimal/compact、wide/seven）× 1 次 = 72 条案例；651 任务调用 + 158 探针；主任务 ¥1.185327 + 探针 ¥0.374119 = ¥1.559446；完成率/有效保留率 100%（天花板），compact k=5 −22.8%，wide k=5 +15.8% 但 6/6 有效（按有效案例约 −3.5%；单次重复，k=0 噪声约 18%）；实验报告 `docs/experiments/e1-compaction-curve.md` |
| `20261019T013233Z-8a01d9f` | 压缩回归（E1 长任务补充） | 007–009 × k=0/1/3/5 × 3 组合 × 1 次 = 36 条案例；311 任务调用，¥2.096687；完成率 100%，保留率 83–97%；compact 93.3% vs 基线 87.8%，总成本 −23.1%；wide 86.7%，+2.2% |

E2 成本曲线记录（不是跑数目录）：

| 日期 | 输入 run | 命中率 | 实际成本 | 无缓存+全峰价 | 总节省 | 报告 |
|---|---|---|---|---|---|---|
| 2026-10-19 | `20261018T154112Z-fa9db83` + E4 codelotte | 89.0% / 89.4% | ¥0.205832 / ¥0.128218 | ¥1.071706 / ¥0.688182 | 80.8% / 81.4% | `evals/cost/cost-report.md` |

LLM judge 校准记录（不是跑数目录）：

| 日期 | 任务 | 样本 | 标注者 | κ | 一致率 | 成本 | 结论 |
|---|---|---|---|---|---|---|---|
| 2026-10-18 | `006-code-review` | 20 | `author-draft` | 1.000 | 100.0% | ¥0.033613 | ⚠ 草稿标注（κ 高但未复核）；样本刻意清晰、κ 有天花板效应，作者复核后重跑 |
| 2026-10-18 | `101-concurrency-review` | 20 | `author-draft` | 1.000 | 100.0% | ¥0.071073 | ⚠ 草稿标注；10 好/10 坏样本，待作者复核 |
| 2026-10-18 | `102-api-design-tradeoffs` | 20 | `author-draft` | 1.000 | 100.0% | ¥0.083567 | ⚠ 草稿标注；10 好/10 坏样本，待作者复核 |

失败归因准确率记录（不是跑数目录）：

| 日期 | 语料 | 样本 | 标注者 | 准确率 | 命令退出码 | 结论 |
|---|---|---|---|---|---|---|
| 2026-10-18 | `evals/attribution/labels.jsonl` | 15（五类各 3） | `author-draft` | 100.0% | 1 | ⚠ 草稿标注；构造语料有天花板效应，真实失败上的准确率待作者复核 |

回归任务示例：`evals/regressions/regression-002-fix-off-by-one.toml` 由
`eval regression` 从 raw 对照的真实失败生成；raw 没有 codelotte 轨迹，归因段如实
写“不可用”。生成的文件可被 `eval run --tasks evals/regressions` 直接读取。

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

# 失败归因准确率（离线）与失败 → 回归任务
uv run codelotte eval attribute
uv run codelotte eval regression --run evals/runs/<运行目录> --task <任务 id> --dry-run

# 打开最新报表
# evals/runs/<新目录>/report.md
```

详细参数、任务格式、CI 冒烟见 [run.md](run.md)；压缩评分与基线解读见
[compaction.md](compaction.md)。
