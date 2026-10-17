# 压缩回归套件：操作手册

> 给未来的我和接手的人。想加题、重跑、看结果、交接，从这里开始。
> 原理、指标口径与基线解读见 [docs/tech/compaction-regression.md](../docs/tech/compaction-regression.md)；
> 任务字段速查与模板见 [evals/tasks/README.md](tasks/README.md)。

## 0. 30 秒版

```bash
# 1. 只校验任务文件、打印跑数计划（不调用模型、不花钱）
uv run codelotte eval compaction --dry-run

# 2. 新任务先用 k=0 单跑一次：确认题目本身可解（不压缩也不能失败）
uv run codelotte eval compaction --k 0 --task 004-your-task

# 3. 全量跑：3/4 条任务 × k=0/1/3/5 × 1 次
uv run codelotte eval compaction --k 0,1,3,5 --out evals/runs

# 4. 打开最新 run 的报表
#    evals/runs/<新目录>/report.md
```

已经装有 `codelotte` 命令时，把 `uv run codelotte` 换成 `codelotte` 即可。

## 1. 这套东西在干什么

让 agent 做同一道题，但中途强制把上下文压缩（compaction）0/1/3/5 次：

- `k=0`：不压缩，对照组；
- `k=1/3/5`：每次请求前若还没压够 k 次，就把旧上下文压成结构化摘要；
- 每次压缩后立刻问模型“任务目标 / 已完成 / 约束”，答案用于评分（带外探针，不写回任务会话）；
- 任务结束后用确定性验收器判完成；最后按 k 聚合完成率与状态保留率。

## 2. 目录地图

| 路径 | 作用 |
|---|---|
| `evals/tasks/*.toml` | **题目定义**：初始文件、指令、验收器、checkpoint |
| `evals/runs/<run-id>/` | **一次跑数的全部证据**；每次新建，不覆盖 |
| `src/codelotte/evals/` | 实现：加载任务、强制压缩、探针、评分、报表 |
| `docs/tech/compaction-regression.md` | 方法与口径、基线解读、已知局限 |
| `tests/test_eval_*.py` | 自动化测试（加载/评分/运行/报表/CLI） |

## 3. 新增一条任务（分步）

### 第 1 步：新建 TOML

在 `evals/tasks/` 下新建 `004-your-task.toml`（编号只用于排序，必须唯一）。
最小模板见 [evals/tasks/README.md](tasks/README.md#最小模板)，复制后改这几处：

- `id`：唯一、简短、ASCII（例：`004-json-merge`）；
- `bucket`：`A` 真实自用 / `B` 对抗约束 / `C` 公开子集；
- `instruction`：给模型的题面；
- `[setup.files]`：初始文件（确定性）；
- `[verifier]`：怎么判对（文件内容 / Python 断言）；
- `[[checkpoints]]`：3 个问题 + 事实组；
- `timeout_seconds` / `max_model_calls`：预算。

### 第 2 步：校验，不花钱

```bash
uv run codelotte eval compaction --dry-run
```

它会读取并校验所有 `*.toml`，打印任务清单和案例数；TOML 缺字段、路径越界、
验收器为空会直接报错（退出码 2），不会调用模型，也不会建 run 目录。

### 第 3 步：先用 k=0 单跑

```bash
uv run codelotte eval compaction --k 0 --task 004-your-task --out evals/runs
```

看 `report.md` 的完成率和 `workspaces/<case>/` 的产物。

- k=0 就失败：**题目/验收器/指令有问题**，不是压缩问题。先修题。
- k=0 通过：题目本身可解，再进入下一步。

### 第 4 步：确认能压到 k 次

```bash
uv run codelotte eval compaction --k 5 --task 004-your-task --out evals/runs
```

看报表里的 `压缩次数` 是否是 `5/5`。

- `5/5` 且完成：可以进全量。
- 少于 `5/5`：案例标为**无效**。通常是指令里的步骤不够多，或模型把多步合并成了一次工具调用。
  在题面里写“一次只做一个动作”，并把任务拆成更多必须依次执行的步骤；或者这一轮先用较低的 k。

### 第 5 步：全量跑

```bash
uv run codelotte eval compaction --k 0,1,3,5 --out evals/runs
```

默认 `--repeat 1`。要评估模型方差，用 `--repeat 3`（同一任务 × k 会得到 `r1/r2/r3`）。

## 4. 任务设计规则（最容易踩的坑）

1. **确定性**：setup 文件固定；验收器不依赖网络、当前时间、随机数。
2. **turn 数 ≥ k**：k 次压缩需要至少 k 个 turn（一次 assistant 回复 + 工具链）。
   现有三条任务分别约 5/6/8 个工具 turn，刚好支撑 k=5。
3. **一个动作一步**：题面明确写“先 read X，再 read Y，再 write Z”，否则模型可能一次批量做完，
   压缩次数不够，案例无效。
4. **checkpoint 事实要具体**：用 `report.txt`、`TODO`、`序号` 这种可判别 token；
   不要用“文件”“内容”这种到处都有的词，否则所有答案都能命中。
5. **事实组是“全部命中”**：每个问题给若干事实组，每组给若干替代表述（任一命中即可）；
   所有组都命中，问题才通过。宁可少一组，不要把词典写成同义词大杂烩。
6. **验收器优先命令式/文件比对**：v0 没有 LLM judge；`python` 验收器在工作区里跑，退出码 0 即通过。
7. **不要放模板 `.toml` 进 `evals/tasks/`**：加载器会把目录下所有 `*.toml` 当任务；
   模板写在 `evals/tasks/README.md` 的代码块里。

## 5. 跑数参数速查

| 参数 | 默认 | 说明 |
|---|---|---|
| `--k` | `0,1,3,5` | 强制压缩次数；逗号分隔，不能重复；`0` 是不压缩对照 |
| `--task ID` | 全部 | 只跑指定任务，可重复 |
| `--tasks 目录` | `<repo>/evals/tasks` | 任务目录 |
| `--out 目录` | `<repo>/evals/runs` | 跑数根目录；每次新建 `<UTC时间>-<git短哈希>` |
| `--repeat N` | `1` | 每个任务 × k 重复 N 次，得到 r1..rN |
| `--seed N` | `0` | 随机种子（provider 重试抖动） |
| `--dry-run` | 关 | 只校验任务、打印计划 |
| `--no-sandbox` | 关 | 任务命令直接在宿主机执行；默认 Docker。只在明确知情时使用 |

退出码：`0` 报表生成且无运行错误；`1` 有案例运行错误（任务失败本身不算）；
`2` 用法/配置错误。

## 6. 一次跑数产出什么

```text
evals/runs/20261017T173510Z-037104e/
├── report.md            # 人读报表：先看“结论速览”
├── report.json          # 机器可读：meta + 全部案例
├── annotations.csv      # 人工标注表：一行一个问题
├── checkpoints.jsonl    # 每次压缩后的原始问答与评分
├── sessions/            # 原始轨迹（JSONL），在 run 根，不在工作区
└── workspaces/          # 每条案例的最终工作区（agent 实际产物）
```

案例目录名：

```text
001-audit-report-k3-r1
│                │  └─ r1 = 第 1 次重复（不是“第一轮”，是 repetition 序号）
│                └──── k3 = 强制压缩 3 次
└───────────────────── 任务 id
```

`a.txt / b.txt / c.txt` 是 001 任务的**输入文件**，和任务分类 `bucket = "A"/"B"/"C"`
没有关系；`report.txt` 是 agent 要交的答案文件。

## 7. 读报表：先看哪几列

打开 `report.md`：

1. **结论速览**：每个 k 的完成率、有效案例、状态保留率、平均压缩次数、成本。
2. **逐任务结果**：哪条任务在哪个 k 失败；`有效` 列是 ✅ 还是 ❌。
3. **Checkpoint 明细**：每次压缩后模型怎么回答；`跨段` 表示事实写在另一题里。

几个词：

- **完成率** = 验收通过 / 尝试次数（失败不剔除）。
- **有效案例** = 没运行错误，且实际压缩次数恰好等于 k；`k=0` 天然有效。
- **状态保留率** = checkpoint 问题通过数 / 问题总数。
- **misplaced（跨段）** = 事实出现在整段回答里、但不在该问题自己的编号段；算“记得”，
  只是位置不对，不扣保留率。

## 8. 人工标注

打开 `annotations.csv`，在 `human_pass` 列填 `1`（通过）/ `0`（不通过）/ 留空。

优先复核：

1. `auto_pass=0` 的行；
2. `misplaced` 非空的行（答对但答错位置）；
3. `structured=False` 的行（模型没按 1./2./3. 编号）。

v0 不自动合并人工分；CSV 本身就是记录。基线 `20261017T173510Z-037104e` 有 4 行
`misplaced`、没有 `auto_pass=0`；这 4 行是作者复核的优先队列。

## 9. 复现与对比

- 每次跑都新建 run 目录，**不会覆盖**历史。想删旧跑数，手动确认后删。
- `report.json` 的 `meta` 记录：git ref、是否有未提交改动（含工作树指纹）、seed、
  Python/codelotte 版本、`uv.lock` 哈希、模型/窗口/阈值、任务语义指纹、完整命令。
- 同一命令重跑会得到新目录；模型没有固定 temperature，数字会波动。看趋势用 `--repeat`。
- 想拿“干净的 git ref”：先提交，再重跑。未提交跑数也会被工作树指纹锁住，不是不能用。
- 对比两次跑数：并排看两个 `report.md` 的结论速览，或 diff `report.json`。

## 10. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `--dry-run` 报错 | 任务 TOML 有问题：缺字段、路径越界（绝对路径/`..`/`C:foo`）、验收器为空。按报错改 |
| k=0 就完不成 | 题目/验收器/指令有问题，不是压缩。先修题 |
| 压缩次数 `3/5`，标 invalid | 任务 turn 不够或模型合并了步骤。题面写“一次只做一个动作”，把步骤拆细；或降低 k |
| 报“Docker 沙箱不可用” | 启动 Docker Desktop；或在明确风险后加 `--no-sandbox` |
| 产物不在 `workspaces/<case>/` | 先看该目录；若模型用了 `/workspace/...`，Docker 模式下文件工具会映射回工作区（票据 13 修复） |
| 不知道花多少钱 | 先用 `--k 0 --task ...` 单跑；v0 基线 12 条案例约 ¥0.27（2026-10 DeepSeek flash 价格） |
| 只想跑 1/3/5，不要对照组 | `--k 1,3,5` |
| 想加任务但先不跑 | `--dry-run` |

## 11. 交接清单

接手的人按这个顺序看：

1. 本文件（操作）；
2. [docs/tech/compaction-regression.md](../docs/tech/compaction-regression.md)（原理、口径、基线解读、局限）；
3. [evals/tasks/README.md](tasks/README.md)（任务字段与模板）；
4. 最近一次基线的 `report.md`；
5. `src/codelotte/evals/`（实现，按 tasks → checkpoints → regression → suite → report 读）。

跑之前先 `--dry-run`；动代码后跑 `uv run pytest tests/test_eval_*.py`。
