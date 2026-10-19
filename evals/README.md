# codelotte 评估体系：总览

> 这个目录回答一个问题：**codelotte 这套 harness 到底有没有用，值多少？**
> 不是“功能清单”，而是可复现的任务、基线、指标、轨迹与失败分析。
>
> 本文是入口；操作细节在 [run.md](run.md)、[compaction.md](compaction.md)、
> [attribution.md](attribution.md)，全部跑数索引在 [record.md](record.md)。

## 0. 30 秒心智模型

```text
                  ┌─────────────────────────────┐
                  │  任务集 evals/tasks/*.toml   │
                  │  指令 / 初始文件 / 验收器     │
                  └──────────────┬──────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
   eval controls           eval run / compare        eval compaction
   （评测器自检）          （真实 agent 跑数）       （强制压缩专项）
        │                        │                        │
        └────────────────────────┴────────────────────────┘
                                 │
                        report.md / report.json
                        sessions/（轨迹）
                        workspaces/（产物）
                                 │
                 ┌───────────────┴───────────────┐
                 │                               │
          eval attribute                  eval regression
     （失败归因准确率）              （失败 → 回归任务）
                 │                               │
                 └───────────────┬───────────────┘
                                 │
                    evals/runs/（证据）+ record.md
```

一句话：**任务集是题目，controls 检查考场，run/compaction 是考试，compare 是对照实验，
judge 是主观题阅卷校准，attribute 是病历，regression 是把病例变成复诊题。**

## 1. 目录里都有什么

| 路径 | 放什么 | 谁生成 | 进默认 `eval run` 吗 |
|---|---|---|---|
| [`tasks/`](tasks/) | **确定性任务**：9 条 TOML。初始文件、指令、验收器、预算、checkpoint、oracle 参考解、只读保护文件 | 作者手写 | ✅ |
| [`judge-tasks/`](judge-tasks/) | **主观任务**：3 条 TOML，声明 `[verifier.judge]` 评分卡与校准路径 | 作者手写 | ❌（单独目录） |
| [`judges/<task>/`](judges/) | judge 校准资产：`samples.jsonl`（人工标注样本）、`calibration.json`（κ/阈值/绑定指纹）、`calibration.md`（人读表） | `eval judge` 生成 | — |
| [`attribution/`](attribution/) | 失败归因语料：`labels.jsonl`、`sessions/*.jsonl`、`attribution-report.md/.json` | 作者手写 + `eval attribute` 生成 | — |
| [`regressions/`](regressions/) | 由失败案例生成的回归任务 TOML；单独目录，避免改变历史任务集口径 | `eval regression` 生成 | ❌（需 `--tasks evals/regressions`） |
| [`cost/`](cost/) | E2 成本曲线：`cost-report.md` / `.json`（实际 vs 无缓存/全峰价反事实） | `eval cost` 生成 | — |
| [`runs/`](runs/) | **跑数证据**：每次评测一个目录，含报表、会话轨迹、最终工作区 | 各评测命令生成 | — |
| [`run.md`](run.md) | 通用测评、对照、自检、judge、归因的操作手册 | 文档 | — |
| [`compaction.md`](compaction.md) | 强制压缩专项的操作手册、评分与 v0 基线 | 文档 | — |
| [`attribution.md`](attribution.md) | 五类失败归因规则、语料与回归任务说明 | 文档 | — |
| [`record.md`](record.md) | 所有已入库跑数的索引、目录约定与记录表 | 文档 | — |

### 1.1 任务文件（`.toml`）

一条任务就是一个可复现的实验单元：

```toml
id = "006-multi-bug-pipeline"
bucket = "A"                  # A 真实自用 / B 对抗构造 / C 公开子集
instruction = "..."            # 给 agent 的题面
[setup.files]                  # 初始工作区（或 [setup.snapshot] 从 git ref 抽快照）
[verifier]                     # 确定性验收：文件内容 / python 检查 / 命令
[[checkpoints]]                # 压缩后要问模型“还记得吗”的事实组
[control.oracle.files]         # oracle 控制 agent 的参考解
```

关键约束：验收必须**确定性**（不靠模型）；每条任务至少有一个 `unchanged` 保护文件
（judge 任务也有），cheating 控制组才有可检测的篡改目标；每条**确定性任务**有 ≥3 个
checkpoint，压缩回归才能用。格式细节见 [run.md](run.md) §3。

### 1.2 会话与轨迹（`.jsonl`）

- `evals/runs/<run>/sessions/<case>/<timestamp>_<id>.jsonl`：codelotte 的 append-only
  session（user / assistant / tool_call / tool_result / usage / permission /
  compaction / guardrail 等记录）。**事实源**，报表和归因都从它读。
- `evals/runs/<run>/harnesses/mini-swe-agent/sessions/*.traj.json`：mini 的轨迹（JSON）。
- `evals/runs/<run>/harnesses/raw/sessions/*.jsonl`：裸 API 的请求/回答/usage 轨迹。
- `evals/attribution/sessions/*.jsonl`：手工构造的失败轨迹样本。
- `evals/judges/<task>/samples.jsonl`：给 judge 的提交文本与人工 `human_pass` 标注。

### 1.3 报表（`.md` / `.json`）

- `report.md`：人读。结论速览、任务表、逐案例、judge 段、失败归因段、失败案例、口径。
- `report.json`：机器读。`meta`（git ref / 工作树指纹 / 模型 / 重复次数 / 任务指纹）+
  `summaries` + `cases`（含 `judge_*`、`failure_*` 字段）+ `harnesses`（对照/自检）。
- `calibration.md/json`：judge 的 κ、一致率、样本数、标注者、绑定指纹与逐样本结果。
- `attribution-report.md/json`：归因准确率、混淆矩阵、逐条证据。

### 1.4 工作区（`workspaces/`）

每条案例的**最终产物**。它可能被 agent 故意写坏（比如 cheating 控制组），
所以不要拿它当源码读；它是证据，不是仓库内容。

## 2. 八个命令分别是什么意思

| 命令 | 回答的问题 | 调模型？ | 主要产出 |
|---|---|---|---|
| `eval run` | 当前 harness 能不能过这批任务？稳定吗？每条多少钱/多久？ | ✅ | `runs/<id>/report.md/json`、sessions、workspaces |
| `eval compaction` | 上下文被强制压缩 k 次后，任务目标和关键状态还记得吗？ | ✅ | 压缩专项报表 + checkpoint 明细 + 人工标注表 |
| `eval compare` | 同一个模型下，codelotte / mini-swe-agent / 裸 API 谁强？增量在哪？ | ✅ | 父报表 + 每组 `harnesses/<group>/` 明细 |
| `eval controls` | 评测器本身可信吗？oracle 会 100%、no-op 会 0%、cheating 会被抓吗？ | ❌（离线零成本） | 自检结论表 + 三组控制案例 |
| `eval judge` | LLM 阅卷人和人工标注一致吗？κ 是多少？ | ✅（阅卷模型） | `evals/judges/<task>/calibration.*` |
| `eval attribute` | 失败归因规则和人工标注一致吗？五类分得清吗？ | ❌（规则） | `evals/attribution/attribution-report.*` |
| `eval regression` | 这条失败能不能变成以后每轮都跑的复诊题？ | ❌ | `evals/regressions/<new-id>.toml` |
| `eval cost` | 缓存和 off-peak 实际省了多少？无缓存/全峰价的反事实是多少？ | ❌（读会话） | `evals/cost/cost-report.md/json` |

### 2.1 `eval run`：通用测评（主线）

```bash
uv run codelotte eval run --dry-run          # 只校验任务，不花钱
uv run codelotte eval run --repeat 3         # 9 任务 × 3 次
uv run codelotte eval run --bucket B --repeat 1
```

- 每条任务重复 N 次，算 **pass^N**：全部重复都通过才算过；任何一次失败/运行错误都记 ❌。
- 报表含成功率、模型调用、总成本、实际峰谷时段、平均耗时；失败案例可直接定位到会话。
- 失败后自动跑五类归因（只对 codelotte 轨迹），写进“失败归因”段。
- 详细口径：[run.md](run.md) §4。

### 2.2 `eval compaction`：强制压缩专项

```bash
uv run codelotte eval compaction --k 0,1,3,5 --repeat 1

# E1 矩阵：摘要模板 seven/compact × 切点策略 minimal/wide
uv run codelotte eval compaction --k 0,1,3,5 --repeat 1 \
  --combo minimal:seven --combo minimal:compact --combo wide:seven
```

- 同一道题，中途强制压缩 0/1/3/5 次；每次压缩后用 checkpoint 问题做带外探针，
  问“任务目标 / 已完成步骤 / 关键约束”，按事实组确定性评分。
- 回答的是“压缩后还记得吗”，不是“整体能不能过”；整体能力看 `eval run`。
- E1 的两个变量：模板 `seven`/`compact`，切点 `minimal`（最近 1 turn）/`wide`（最近 2 turn）；
  报表按 `策略 / 模板 × k` 分组。结果见 [E1 报告](../docs/experiments/e1-compaction-curve.md)。
- 任务必须有 ≥3 个 checkpoint；细节与 v0 基线：[compaction.md](compaction.md)。

### 2.3 `eval compare`：scaffolding tax 对照

```bash
uv run codelotte eval compare --repeat 2 \
  --mini-python .mini-venv/Scripts/python.exe
```

三组同任务集、同模型、同次数：

| 组 | 作用 |
|---|---|
| `codelotte` | 被测 harness（四工具 + 权限/防线/压缩/会话） |
| `mini-swe-agent` | 参照 harness（开源教学级，只有 bash） |
| `raw` | 裸单轮 API（无 tools），代表“只有模型”的下界 |

- 父报表按任务并排显示三组；每组明细在 `harnesses/<组>/report.md`。
- 用来区分“模型的功劳”和“harness 的增量”，并记录成本/耗时/调用数。
- 最新 E4 结果与解释：[docs/experiments/e4-scaffolding-tax.md](../docs/experiments/e4-scaffolding-tax.md)。

### 2.4 `eval controls`：评测器自检（先信考场）

```bash
uv run codelotte eval controls
```

三个假 agent：

| 控制 agent | 行为 | 预期 |
|---|---|---|
| `oracle` | 直接写任务参考解 | **100% 通过** |
| `no-op` | 什么都不做 | **0% 通过**，不产生标记 |
| `cheating` | 写假成功内容 + 篡改所有 `unchanged` 文件 | **0% 通过且全部被标记** |

任何一条不符，CLI 返回 1：**先修评测器，再相信任何真实跑分。**
不调用模型、不需要 API key/Docker，几秒钟跑完。judge 任务会被跳过（因为控制组必须离线）。

### 2.5 `eval judge`：LLM 阅卷与 κ 校准

```bash
uv run codelotte eval judge --dry-run
uv run codelotte eval judge --task 101-concurrency-review --task 102-api-design-tradeoffs
```

- 有些任务没有唯一答案（review/design），用评分卡让模型阅卷：每个维度 0–1 分 + 理由，
  平均分过 `pass_threshold` 才算通过。
- 但阅卷人必须先证明靠谱：≥20 条人工标注样本，算 judge 与人工的 Cohen's κ；
  低 κ、样本不足、校准缺失、标注者含 `draft` 都在报表标 ⚠。
- 校准文件绑定 `task_id` / `model` / rubric 指纹 / 样本哈希；任一变化，旧 κ 会提示重跑。
- 当前三个 judge 任务各 20 条 `author-draft` 样本，κ=1.000，**草稿值待作者复核**；
  细节：[run.md](run.md) §4.7。

### 2.6 `eval attribute`：失败归因准确率

```bash
uv run codelotte eval attribute
```

- 规则版 v0 把失败归入五类：`model` / `tool_schema` / `context_loss` / `loop` / `environment`。
- 语料 `evals/attribution/labels.jsonl` 提供人工类别；命令逐条跑分类器，输出准确率、
  混淆矩阵、每条证据；报告标 ⚠ 草稿、退出码 1（因为标注未复核）。
- 归因规则与优先级：[attribution.md](attribution.md)。

### 2.7 `eval regression`：失败 → 回归任务

```bash
uv run codelotte eval regression \
  --run evals/runs/<run-id> --task 002-fix-off-by-one --dry-run
uv run codelotte eval regression \
  --run evals/runs/<run-id> --task 002-fix-off-by-one
```

- 从失败案例生成一条新任务：保留原任务的 setup/verifier/预算/参考解，只换 `id`，
  文件头写明来源、归因与失败详情。
- 默认写到 `evals/regressions/`，**不覆盖**已有文件，写盘后再用 `load_task` 校验。
- 它不参与默认 `eval run`；要跑回归集：
  `uv run codelotte eval run --tasks evals/regressions`。

### 2.8 `eval cost`：缓存与 off-peak 成本曲线

```bash
uv run codelotte eval cost \
  --run evals/runs/<run-id> \
  --run evals/runs/<another-run> \
  --out evals/cost
```

- 从 run 的会话 usage 记录重算：实际成本、**无缓存**反事实（命中 token 按未命中价）、
  **全峰价**反事实（同一份 usage × 峰价）、两者叠加的总反事实。
- 输出缓存命中率、逐调用序号的命中率曲线、off-peak 调用占比与节省金额。
- 不调用模型、不写 run 目录；可用于任意带 codelotte 会话的 run。
- 口径：反事实不是重新跑模型；压缩回归的 checkpoint 探针不写回会话，不在本报表里。
  最新结果与解读：[docs/experiments/e2-cost-curve.md](../docs/experiments/e2-cost-curve.md)。

## 3. 它们怎么串起来

### 3.1 一条失败的完整链路

```text
eval run / compare
      │ 某条案例 ❌
      ▼
report.md 的“失败归因”段
      │ 五类之一 + 证据 + 置信度
      ├─ 想提高归因可信度 → eval attribute（人工语料对照）
      └─ 想防复发 → eval regression（生成回归任务）
                         │
                         ▼
                 eval run --tasks evals/regressions
```

- 确定性验收优先：未声明 judge 的任务零 judge 调用；确定性检查失败时**不调用** judge。
- 归因只读 codelotte 会话；mini/raw 轨迹格式不同，报表记“未归因”。
- 回归任务解决的是“同样的坑别再踩”，不是“这次为什么失败”。

### 3.2 推荐工作流

```bash
# 0) 改任务/改评测器后，先离线验证考场
uv run codelotte eval controls

# 1) 日常回归：当前 harness 的 pass^k、成本、耗时、失败归因
uv run codelotte eval run --repeat 3

# 2) 改 harness 后做三组对照（同任务、同模型）
uv run codelotte eval compare --repeat 2 \
  --mini-python .mini-venv/Scripts/python.exe

# 3) 主观任务：先校准，再跑
uv run codelotte eval judge --dry-run
uv run codelotte eval judge
uv run codelotte eval run --tasks evals/judge-tasks --repeat 1

# 4) 归因机制本身的准确率（离线）
uv run codelotte eval attribute

# 5) 把一条失败转成回归任务
uv run codelotte eval regression --run evals/runs/<run-id> --task <id>

# 6) 成本曲线（缓存 / off-peak 反事实；离线）
uv run codelotte eval cost --run evals/runs/<run-id> --out evals/cost
```

### 3.3 一次跑数里有什么

```text
evals/runs/<run-id>/
├── report.md              # 人读总报表
├── report.json            # 机器读（meta / summaries / cases）
├── sessions/<case>/       # 每条案例的会话轨迹
└── workspaces/<case>/     # 每条案例的最终工作区

# compare / controls 的父目录多一层分组：
evals/runs/<run-id>/
├── report.md / report.json
└── harnesses/<group>/
    ├── report.md / report.json
    ├── sessions/
    └── workspaces/
```

- 跑数目录**不手工编辑**；要新数字就重跑，历史目录不覆盖。
- 每个 run 的 `meta` 锁定 git ref、工作树指纹、seed、Python/codelotte 版本、`uv.lock` SHA、
  模型/窗口、任务语义指纹与完整命令。
- 失败定位：通用测评看“失败案例”+“失败归因”；压缩看逐案例 + checkpoint；
  对照/自检看父报表“失败定位”并按组给轨迹路径。

## 4. 体系由哪几层组成

| 层 | 内容 | 代表文件/命令 |
|---|---|---|
| 任务层 | 9 条确定性任务 + 3 条主观任务；指令/初始文件/验收/预算/checkpoint | `evals/tasks/`、`evals/judge-tasks/` |
| 执行层 | codelotte loop、mini-swe-agent、裸 API、三种控制 agent；工作区准备与隔离 | `src/codelotte/evals/`、`eval compare/controls` |
| 验收层 | 确定性文件检查 / python / command；LLM judge 兜底；防篡改检查 | `workspace.py`、`judge.py` |
| 度量层 | pass^k、成本、峰谷时段、耗时、模型调用、judge κ、失败五类 | `eval_report.py`、`attribution.py` |
| 证据层 | append-only 会话、最终工作区、`report.json`、实验报告 | `evals/runs/`、`docs/experiments/` |
| 校准层 | judge 与人工的一致性、归因与人工标注的一致性 | `eval judge`、`eval attribute` |
| 回归层 | 失败案例 → 永久回归任务 | `eval regression`、`evals/regressions/` |

## 5. 当前基线（2026-10-18/19，低谷时段）

| 评测 | 结果 | 证据 |
|---|---|---|
| 正式 `eval run`（9 任务 × 3 次，Docker） | 27/27 通过，pass^3 9/9，188 调用，¥0.205832，349.0s | [`runs/20261018T154112Z-fa9db83`](runs/20261018T154112Z-fa9db83/report.md) |
| E4 对照（3 组 × 9 任务 × 2 次） | codelotte 18/18、mini 18/18、raw 0/18；codelotte 成本 +15.4%、耗时 −33.5% | [`runs/20261018T155840Z-fa9db83-compare`](runs/20261018T155840Z-fa9db83-compare/report.md) |
| 控制组自检（9 任务） | oracle 9/9、no-op 0/9、cheating 0/9 且 9/9 标记 | [`runs/20261018T154851Z-fa9db83-controls`](runs/20261018T154851Z-fa9db83-controls/report.md) |
| judge 任务（3 条） | 3/3 通过，overall 均 1.00，κ=1.00（各 20 样本，⚠ 草稿） | [`runs/20261018T154901Z-fa9db83`](runs/20261018T154901Z-fa9db83/report.md) |
| 归因准确率（15 条语料） | 15/15（100%），⚠ `author-draft` 待复核 | [attribution-report.md](attribution/attribution-report.md) |
| E1 压缩矩阵（短任务 6 + 长任务 3） | 短任务完成率/保留率 100%（天花板）；长任务保留率 83–97%，compact **93.3% vs 87.8%** 且成本 −23.1%；wide 短任务 +15.8% 但 6/6 有效 | [`短任务`](runs/20261018T165516Z-8a01d9f/report.md) · [`长任务`](runs/20261019T013233Z-8a01d9f/report.md) |
| E2 成本曲线（2 个 run） | 缓存命中率 89.0% / 89.4%；相对无缓存+全峰价总节省 80.8% / 81.4% | [cost-report.md](cost/cost-report.md) |
| 压缩回归 v0（旧 3 任务） | 完成率/保留率 100%，天花板效应 | [`runs/20261017T173510Z-037104e`](runs/20261017T173510Z-037104e/report.md) |

数字口径、完整记录与复现命令：[record.md](record.md)。实验解读：
[E4 报告](../docs/experiments/e4-scaffolding-tax.md)。

## 6. 读报表的顺序

1. **结论速览**：任务数、通过率、pass^k、总成本/耗时、计费时段。
2. **汇总表**：哪条任务失败、每条调用/成本/耗时。
3. **失败归因**：五类分布与逐条证据（只有 codelotte 轨迹有）。
4. **失败案例**：会话路径与验收详情。
5. **LLM judge**（如果任务声明了）：分数/理由/κ/⚠。
6. **复现锁定**：git ref、工作树指纹、模型、任务指纹——确认这轮数字对应哪版代码。

## 7. 已知边界

- 任务只有 9 条，且由作者构造；存在“为 codelotte 量身定做”的偏差。
- judge 校准与归因语料都是 `author-draft`：κ/准确率只证明管线可用，不是人工复核结论。
- 成功率的样本量小（每任务 2–3 次），没有置信区间；看趋势而不是单点。
- mini-swe-agent 是外部依赖，不在项目 lockfile 里；安装方式与 Windows shell 修正见
  [run.md](run.md) §4.5。
- 压缩基线是旧 3 任务、天花板效应；E1/E2 已在票据 20 完成（见上方基线表）。

## 8. 代码地图

| 路径 | 职责 |
|---|---|
| `src/codelotte/evals/tasks.py` | TOML 加载/校验（任务、验收器、checkpoint、judge、参考解） |
| `src/codelotte/evals/workspace.py` | 工作区准备、git 快照、确定性验收、防篡改检查 |
| `src/codelotte/evals/execution.py` | 单任务执行核心（codelotte loop、预算、成本/时段、验收、judge） |
| `src/codelotte/evals/runner.py` | 任务 × 重复编排、pass^k 数据、失败归因 |
| `src/codelotte/evals/eval_report.py` | 通用报表（Markdown/JSON）与失败归因段 |
| `src/codelotte/evals/compare.py` | 多组对照、控制 agent 自检、并列报表 |
| `src/codelotte/evals/compaction` / `regression.py` | 压缩触发与强制压缩回归 |
| `src/codelotte/evals/judge.py` | judge 评分卡、κ、校准文件 |
| `src/codelotte/evals/attribution.py` | 五类归因、语料评测、混淆矩阵 |
| `src/codelotte/evals/promote.py` | 失败案例 → 回归任务 TOML |
| `src/codelotte/evals/mini_baseline.py` / `mini_runner.py` | mini-swe-agent 外部进程适配 |
| `src/codelotte/evals/mini_proxy.py` | 本地录制代理（假 key、真实 usage） |

## 9. 继续读

- 操作与任务格式：[run.md](run.md)
- 压缩专项：[compaction.md](compaction.md)
- 归因与回归任务：[attribution.md](attribution.md)
- 全部跑数索引：[record.md](record.md)
- E1/E2/E4 实验报告：[../docs/experiments/](../docs/experiments/README.md)
- 复盘文：[../docs/experiments/retrospective.md](../docs/experiments/retrospective.md)
- 项目总览：[../README.md](../README.md)
