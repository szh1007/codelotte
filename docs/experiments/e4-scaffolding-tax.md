# E4：scaffolding tax 对照（2026-10-18）

> 问题：同一个模型下，**工具循环本身**值多少（vs 裸 API），**codelotte 这套 harness
> 相对参照 harness** 的增量有多少（vs mini-swe-agent）？
>
> 结论先行：9 条任务 × 2 次重复，codelotte **18/18**、mini-swe-agent **18/18**、
> 裸单轮 API **0/18**。成功率没有拉开；差异在成本与时间：codelotte 比 mini
> **贵 15.4%、调用多 26.3%，但每条案例快 33.5%**。工具循环是必要条件；相对参照 harness
> 的增量是“用更多 token 换更短墙钟时间”的工程取舍，不是更高的成功率。

## 1. 任务集

任务从 5 条扩到 **9 条**：原有 5 条偏短（5–8 个工具 turn），本次新增 4 条多步任务，
并新增 2 条主观 judge 任务（单独目录，不参与本对照）。

| 任务 | 桶 | 来源 | 考什么 | codelotte 调用/次（正式 run） |
|---|---|---|---|---|
| 001-audit-report | A | 原有 | 多文件计数 + 精确输出 | 6 |
| 002-fix-off-by-one | A | 原有 | 跑测试、定位 off-by-one、复跑 | 6–7 |
| 003-constrained-append | B | 原有 | 多约束 + 长编辑链 | 8 |
| 004-prompt-injection-resistance | B | 原有 | 数据里的注入指令 | 6 |
| 005-scope-discipline | B | 原有 | 只改允许的文件 | 5–6 |
| **006-multi-bug-pipeline** | A | **新增** | 3 个 bug 分布在 3 个模块，必须跑测试 + 读多文件 | 8 |
| **007-refactor-tokenizer** | A | **新增** | 按 `spec.md` 重写 tokenizer（标点/空白/大小写/数字） | 6–10 |
| **008-settlement-policy** | A | **新增** | 21 行 CSV + 8 条结算规则，两个精确输出文件 | 5–9 |
| **009-buffer-edge-cases** | B | **新增** | 可见测试只测 happy path，规格暗含空队列边界 | 6–8 |

为什么这 4 条更能拉开差距：006/008 需要多文件、多步骤和“读规格再动手”；007 没有可见
测试，必须把规格读成可执行行为；009 有误导性注释，必须相信 `spec.md` 而不是只让可见测试变绿。
四条的 codelotte 平均调用数（约 7–9）明显高于原有任务（5–8），但**没有难倒任一
有工具的 harness**：两个 harness 都 18/18。任务复杂度的提升首先体现在成本/时间上，
而不是成功率上。

任务文件在 [`evals/tasks/`](../../evals/tasks/)；每条都有 `[control.oracle.files]` 参考解、
至少一个 `unchanged` 保护文件与 ≥3 个 checkpoint。控制 agent 自检：oracle **9/9**、
no-op **0/9**、cheating **0/9 且 9/9 标记**（[自检报表](../../evals/runs/20261018T154851Z-fa9db83-controls/report.md)）。

## 2. 基线与干预

| 组 | 是什么 | 隔离 |
|---|---|---|
| **codelotte**（干预） | 四工具（read/write/edit/bash）+ 权限层 + 死循环三层防御 + 压缩 + 会话记录 | 默认 Docker 沙箱 |
| **mini-swe-agent**（基线 A） | 开源教学级 agent 2.4.6，只有 bash；同一模型，经本地录制代理接 API | 本地环境 |
| **裸单轮 API**（基线 B） | 一条 user 消息、无 tools、不回填工具结果 | 无 |

- 模型：`deepseek-flash`，`reasoning_effort=high`；上下文窗口 1,000,000。
- 重复次数：2；随机种子 0；全部案例落在**低谷时段**。
- codelotte 走默认 Docker（工作区 RW 挂载，网络关闭）；mini 走它自己的本地环境。
- mini 的真实 API key 由 codelotte 进程内的录制代理注入；子进程只看到假 key，
  usage 由代理按项目价目表记账。
- **Windows shell 修正**：mini 的 `LocalEnvironment` 用 `shell=True`，Windows 上会落到
  `cmd.exe`，而它的提示词假设 bash；本次适配在 Windows 上把命令改走 Git Bash
  （`bash -lc`），否则 `command -v`、heredoc、管道都会变形，对照不成立。POSIX 平台不改。

## 3. 指标与结果

跑数目录：[`evals/runs/20261018T155840Z-fa9db83-compare/`](../../evals/runs/20261018T155840Z-fa9db83-compare/)
（父报表 + 每组 `harnesses/<组>/` 明细、原始会话/轨迹、最终工作区）。

| 指标 | codelotte | mini-swe-agent | 裸单轮 API |
|---|---:|---:|---:|
| 通过 / 尝试 | **18/18 (100%)** | **18/18 (100%)** | 0/18 (0%) |
| pass^2 任务 | **9/9** | **9/9** | 0/9 |
| 模型调用 | 125 | **99** | 18 |
| 总成本（CNY） | ¥0.128218 | **¥0.111146** | ¥0.280970 |
| 每条案例成本 | ¥0.00712 | **¥0.00617** | ¥0.01561 |
| 每条成功成本 | ¥0.00712 | **¥0.00617** | —（0 成功） |
| 每条案例耗时 | **13.9s** | 20.9s | 17.3s |
| 每条案例调用 | 6.9 | **5.5** | 1.0 |

### 3.1 工具循环值多少（vs 裸 API）

- 裸 API **0/18**：它没有读写文件的工具，任务要求的所有落盘都无法完成。这是**结构下界**，
  不是公平的同策略对照；它证明的是“没有工具循环，这类任务失败”，不是“模型很差”。
- codelotte **18/18**：同样的模型，接上工具循环后全部通过。
- 成本：裸 API 用 ¥0.280970 得到 0 个成功；codelotte 用 ¥0.128218 得到 18 个成功。
  裸 API 的总成本被一次长推理调用抬高（007 r2 单次 ¥0.157），**不作为稳定基线**；
  它的稳定信号是 0/18，而不是金额。工具循环不是零成本，但它把“0 个成功”变成
  “18 个成功”；没有它，后续的成本/时间比较没有分母。

### 3.2 harness 相对参照物的增量（vs mini-swe-agent）

- **成功率相同**（18/18 vs 18/18，pass^2 9/9 vs 9/9）。新任务没有把两个有工具的
  harness 拉开；这否定了“任务一复杂就会暴露 mini 不行”的预期。
- **成本**：codelotte 贵 **+15.4%**（¥0.128218 vs ¥0.111146），每条成功成本
  ¥0.00712 vs ¥0.00617。9 条任务里 codelotte 在 001–005 更便宜，006–009 更贵
  （+23.5% / +130.3% / +28.9% / +76.0%）。
- **调用**：codelotte 多 **+26.3%**（125 vs 99）；006–009 每条案例 10.5/8.5/7.5/5.5 次
  对 mini 的 6/4/4/3.5 次——mini 用更少的 bash 调用把多步操作合并了。
- **耗时**：codelotte 快 **−33.5%**（13.9s vs 20.9s/案例）；7/9 条任务更快，
  007（24.5s vs 18.7s）与 008（22.0s vs 21.6s）更慢。即使 codelotte 多一层
  Docker 容器开销，总体墙钟时间仍更短。
- 解释：codelotte 的 read/edit 把操作拆成更细的调用，system prompt 与工具 schema
  固定开销也更大，所以 token 成本更高；但每次调用更短、工具结果更结构化，模型
  不必反复 `cat`/`sed` 重读大段输出，所以总墙钟时间更短。mini 的 bash 批量操作
  省 token，却把更多内容搬进上下文并更慢地返回。
- 这是**成本–时延取舍**，不是“谁更聪明”。如果目标是单位成本最低，mini 在这个
  任务集上更好；如果目标是交互延迟/吞吐，codelotte 更好。

### 3.3 逐任务

| 任务 | codelotte | mini-swe-agent | 裸 API |
|---|---|---|---|
| 001-audit-report | ✅ 2/2 · ¥0.005807 · 7.7s | ✅ 2/2 · ¥0.009681 · 20.3s | ❌ 0/2 |
| 002-fix-off-by-one | ✅ 2/2 · ¥0.008536 · 9.3s | ✅ 2/2 · ¥0.010000 · 20.8s | ❌ 0/2 |
| 003-constrained-append | ✅ 2/2 · ¥0.008131 · 10.1s | ✅ 2/2 · ¥0.014498 · 24.8s | ❌ 0/2 |
| 004-prompt-injection-resistance | ✅ 2/2 · ¥0.007102 · 8.6s | ✅ 2/2 · ¥0.007996 · 19.7s | ❌ 0/2 |
| 005-scope-discipline | ✅ 2/2 · ¥0.005335 · 7.7s | ✅ 2/2 · ¥0.008098 · 20.0s | ❌ 0/2 |
| 006-multi-bug-pipeline | ✅ 2/2 · ¥0.023976 · 23.6s | ✅ 2/2 · ¥0.019406 · 25.8s | ❌ 0/2 |
| 007-refactor-tokenizer | ✅ 2/2 · ¥0.027786 · 24.5s | ✅ 2/2 · ¥0.012067 · 18.7s | ❌ 0/2 |
| 008-settlement-policy | ✅ 2/2 · ¥0.027918 · 22.0s | ✅ 2/2 · ¥0.021658 · 21.6s | ❌ 0/2 |
| 009-buffer-edge-cases | ✅ 2/2 · ¥0.013626 · 11.3s | ✅ 2/2 · ¥0.007744 · 16.6s | ❌ 0/2 |

单元格是“通过 · 总成本 · 平均耗时/案例”。

## 4. 失败分布

| 组 | 失败数 | 归因/原因 |
|---|---:|---|
| codelotte | 0 | —（本轮没有失败案例，五类归因段为空） |
| mini-swe-agent | 0 | — |
| 裸单轮 API | 18 | 无工具循环，无法落盘（结构下界，不是五类归因） |

失败归因分类器只读 codelotte 会话，mini/raw 的轨迹格式不同，因此不计入五类分布；
本轮没有 codelotte 失败，结论来自“成功/失败 + 成本/时间”本身，而不是归因标签。
归因机制的准确率证据见 [`evals/attribution/`](../../evals/attribution/)
（15 条 `author-draft` 语料，⚠ 待复核）。

## 5. 轨迹样本

- codelotte 成功（007 r1，8 次调用 / 21.8s）：
  `harnesses/codelotte/sessions/007-refactor-tokenizer-r1/20261018T160054Z_16f960fb.jsonl`
- mini 成功（007 r1，3 次调用 / 17.6s）：
  `harnesses/mini-swe-agent/sessions/007-refactor-tokenizer-r1-mini.traj.json`
- mini 成功（008 r1，4 次调用 / 22.4s）：
  `harnesses/mini-swe-agent/sessions/008-settlement-policy-r1-mini.traj.json`
- 裸 API 失败（001 r1，1 次调用）：
  `harnesses/raw/sessions/001-audit-report-r1-raw.jsonl`

读法：同一道题、同一个模型，codelotte 的会话是 read → edit → check 的短链；
mini 的轨迹用更少的 bash 调用完成同样的产物，但每条命令的输出更长、返回更慢。
原始文件都在对应 run 目录，未做裁剪。

## 6. 复现

安装 mini（独立 venv；`mcp` 是 litellm 的启动期可选依赖，缺了会 `ModuleNotFoundError`）：

```bash
uv venv .mini-venv
uv pip install --python .mini-venv/Scripts/python.exe mini-swe-agent==2.4.6 mcp

# 只校验任务/快照/解释器，不调用模型
uv run codelotte eval compare --dry-run --mini-python .mini-venv/Scripts/python.exe
```

本次实际跑数命令：

```bash
# 1) 控制组自检（离线、零成本）
uv run codelotte eval controls

# 2) codelotte 正式 pass^k（9 任务 × 3 次；Docker 默认沙箱）
uv run codelotte eval run --repeat 3

# 3) 三组对照（9 任务 × 2 次；codelotte Docker，mini 本地 + Git Bash）
uv run codelotte eval compare --repeat 2 \
  --mini-python .mini-venv/Scripts/python.exe

# 4) judge 任务（单独目录，不参与上面的对照）
uv run codelotte eval judge --task 101-concurrency-review --task 99-api-design-tradeoffs
uv run codelotte eval run --tasks evals/judge-tasks --repeat 1
```

## 7. 不确定性与局限

- **规模**：9 条任务、每任务 2 次重复、一个模型（`deepseek-flash`）；没有置信区间。
  成功率 18/18 对 18/18 是同分，不能说“codelotte 更可靠”；成本/时间差异有逐任务
  一致性（001–005 便宜、006–009 贵；7/9 更快）支撑，但仍只代表这批任务。
- **`--no-sandbox` 未用于本对照**：codelotte 走 Docker，mini 走本地；容器启动时间
  计入 codelotte 的耗时，方向对 codelotte 不利，但 codelotte 仍更快。
- **任务由作者构造**：9 条都是自建任务，可能存在“为 codelotte 量身定做”的偏差；
  004/005/009 已刻意加入误导/对抗信息，但任务集仍需扩充与外部复核。
- **Windows shell**：最终数字使用 Git Bash 对齐 mini 的 bash 语义；Linux/macOS 上
  mini 的 `shell=True` 天然是 POSIX shell，数字可能不同。
- **未使用 judge**：本对照只看确定性验收；主观质量（review/design）在
  `evals/judge-tasks/` 单独跑，不混入 E4 的成功率。
- **口径**：任务里的“执行纪律”（必须用 read/write、不得用 bash）不在验收范围内；
  三组不是同策略 A/B，读的是“最终状态 + 成本/耗时”。

## 8. 结论（可进 README 的版本）

> 同一模型、9 条多步任务、2 次重复：codelotte 18/18，mini-swe-agent 18/18，
> 裸单轮 API 0/18。工具循环让“能改文件”的任务从 0 变成 100%；两个有工具的 harness
> 成功率打平，但成本–时延不同：codelotte 贵 15.4%、调用多 26.3%，每条案例快 33.5%。
> 新任务提高了复杂度（调用/成本上升），但没有拉开成功率——下一步要拉开差距，
> 需要更长的任务链或不同的模型，而不是继续加同量级的题。
