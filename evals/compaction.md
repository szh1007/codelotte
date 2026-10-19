# 专用测评 - 压缩回归 v0：操作手册

> 回答一个问题：**上下文被压缩后，agent 还记得任务目标、已完成步骤和关键约束吗？**
>
> 通用测评（`eval run`）、任务格式与 CI 冒烟见 [run.md](run.md)；
> 跑数记录见 [record.md](record.md)。本文只讲这个专用测评。

## 0. 30 秒版

```bash
# 1. 只校验任务文件与 checkpoint，不调用模型、不花钱
uv run codelotte eval compaction --dry-run

# 2. 新任务先用 k=0 单跑：题目本身可解吗？
uv run codelotte eval compaction --k 0 --task 004-your-task --out evals/runs

# 3. 再确认能压到 5 次：题目的 turn 数够吗？
uv run codelotte eval compaction --k 5 --task 004-your-task --out evals/runs

# 4. 全量：当前 9 条任务 × k=0/1/3/5 × 1 次 = 36 条案例
uv run codelotte eval compaction --k 0,1,3,5 --out evals/runs

# 5. E1 矩阵：策略 × 模板（每个组合各一条曲线）
uv run codelotte eval compaction --k 0,1,3,5 --repeat 1 \
  --combo minimal:seven --combo minimal:compact --combo wide:seven \
  --out evals/runs

# 6. 打开报表
#    evals/runs/<新目录>/report.md
```

已经装有 `codelotte` 命令时，把 `uv run codelotte` 换成 `codelotte` 即可。

## 1. 它回答什么，不回答什么

让 agent 做同一道题，但中途强制把上下文压缩（compaction）0/1/3/5 次：

- `k=0`：不压缩，对照组；
- `k=1/3/5`：每次请求前若还没压够 k 次，就把旧上下文压成结构化摘要；
- 每次压缩后立刻问模型“任务目标 / 已完成 / 约束”，答案用于评分（带外探针，不写回任务会话）；
- 任务结束后用确定性验收器判完成；最后按 k 聚合完成率与状态保留率。

**它回答**：压缩次数增加时，任务完成率和关键状态保留率怎么变。

**它不回答**：当前 harness 整体能不能过一批任务、每条任务花多少钱/多久——那是通用测评
`eval run`（见 [run.md](run.md)）。两边共用任务格式与工作区/验收代码，
但报表口径不同。

## 2. 参数与跑数矩阵

| 参数 | 默认 | 说明 |
|---|---|---|
| `--k` | `0,1,3,5` | 强制压缩次数；逗号分隔，不能重复；`0` 是不压缩对照 |
| `--strategy` | `minimal` | 切点策略，可重复：`minimal`=最近一个 turn，`wide`=最近两个 turn |
| `--template` | `seven` | 摘要模板，可重复：`seven`=七项，`compact`=目标/已完成/约束三节 |
| `--combo` | 无 | 精确指定 `策略:模板`，可重复；与 `--strategy/--template` 互斥 |
| `--task ID` | 全部 | 只跑指定任务，可重复 |
| `--tasks 目录` | `<repo>/evals/tasks` | 任务目录 |
| `--out 目录` | `<repo>/evals/runs` | 跑数根目录；每次新建 `<UTC时间>-<git短哈希>` |
| `--repeat N` | `1` | 每个任务 × k 重复 N 次，得到 r1..rN |
| `--seed N` | `0` | 随机种子（provider 重试抖动） |
| `--dry-run` | 关 | 只校验任务与 checkpoint、打印计划 |
| `--no-sandbox` | 关 | 任务命令直接在宿主机执行；默认 Docker。只在明确知情时使用 |

退出码：`0` = 报表生成且没有运行错误；`1` = 有案例运行错误（任务失败本身不算）；
`2` = 用法/配置错误。

v0 基线当时跑 `3 条任务 × k=0/1/3/5 × 1 次重复 = 12 条案例`。票据 15 新增 004/005，
票据 19 又新增 006–009（多步调试/规格重构/长规则/边界条件），任务目录现有 9 条，
全量是 `9 × 4 = 36` 条案例；要复现 v0 数字，用 `--task` 只选 001–003：

```bash
uv run codelotte eval compaction --k 0,1,3,5 \
  --task 001-audit-report --task 002-fix-off-by-one --task 003-constrained-append
```

### 2.1 E1 的两个实验变量

- **策略（切点）**：`minimal` 只保留最近一个 turn（v0 行为，压得最狠）；
  `wide` 保留最近两个 turn，牺牲压缩率换更多上下文。
- **模板（摘要结构）**：`seven` 是七项摘要（任务/已完成/决策/约束/文件/未解决/下一步）；
  `compact` 只保留目标/已完成/约束三节，summary token 更少。
- 用 `--combo` 精确跑组合（如 `minimal:seven`、`wide:compact`），或用
  `--strategy`/`--template` 做笛卡尔积。报表按 `策略 / 模板 × k` 分组，
  每组的完成率/保留率/成本可直接对照。
- 正式结果与曲线：[docs/experiments/e1-compaction-curve.md](../docs/experiments/e1-compaction-curve.md)。

| 指标 | 定义 |
|---|---|
| 完成率 | 验收通过 / 尝试次数（失败不剔除，失败也是数据） |
| 有效案例 | 运行无错误，且实际压缩次数恰好等于 k；`k=0` 天然有效 |
| 状态保留率 | 压缩后 checkpoint 问题通过数 / 问题总数 |
| 有效完成率 | 有效案例中验收通过 / 有效案例数 |
| 成本 | 被测任务 + checkpoint 探针的模型调用估价（人民币元） |

达不到 k 次压缩的案例仍然计入“全部”列，但另标“无效”——它不能回答“压缩 k 次后怎样”。

## 3. 专用测评的任务要求

任务格式、字段、验收器和仓库快照见 [run.md](run.md)。压缩回归额外要求：

1. **必须有 checkpoint**：`eval compaction` 会拒绝没有 checkpoint 的任务；通用任务请用 `eval run`。
2. **turn 数 ≥ k**：k 次压缩至少需要 k 个 turn（`turn` = 一次 assistant 回复 + 工具链）。
   现有任务分别约 5/6/8/5/5 个工具 turn；想稳定支撑 k=5，至少写 5 个必须依次执行的动作。
3. **题面写“一次只做一个动作”**：否则模型可能一次 read 三个文件 / 一次 write 全部内容，
   压缩次数不足，案例会被标为无效。
4. **checkpoint 事实要具体**：用 `report.txt`、`TODO`、`序号` 这种可判别 token；
   不要用“文件”“内容”这种到处都有的词，否则所有答案都能命中。
5. **事实组是“全部命中”**：每个问题给若干事实组，每组给若干替代表述（任一命中即可）；
   所有组都命中，问题才通过。宁可少一组，不要把词典写成同义词大杂烩。

不要把模板 `.toml` 放进 `evals/tasks/`：加载器会把目录下所有 `*.toml` 当任务；
模板写在 [run.md](run.md) 的代码块里。

## 4. 强制压缩机制

生产触发是双阈值（票据 12）。回归套件不修改生产逻辑，而是给 `AgentLoop` 注入
`CompactionPolicy`：

- 每次请求前统计已落盘的 `type=compaction` 记录数；
- 少于 k 时，把利用率钉在 100% 调 `plan_compaction`，复用“硬触发 → 最小保留集”的切分；
- 达到 k 后返回 `None`，后续不再压缩。

因此：

- 每次强制压缩都发生在**上一个 turn 完成之后、下一次请求之前**；
- k 次压缩至少需要 k 个 turn（没有新 turn 时最小保留集不可再切）；
- k=0 时策略直接返回 `None`，作为不压缩对照组。

这只是实验注入点，不改变 `-p`/TUI 的生产路径；默认策略仍是 `default_compaction_policy`。

## 5. Checkpoint：压缩后问什么、怎么判

### 5.1 探针

每次 `CompactionEvent` 之后，压缩记录已落盘、`loop.messages` 已按摘要重装配。
套件此时用**同一模型**发一次**带外**请求：

```text
[压缩后的 messages]
+ user: 现在暂停任务。只根据你当前掌握的上下文回答下面 3 个问题……
```

`tools=None`，答案不写回会话——不污染被测轨迹。探针的 token 与成本单独计入报表。
探针失败只记错误，不中断被测任务。

### 5.2 问题集

每条任务三个问题（可在 TOML 增删）：

1. 任务目标是什么？
2. 已经完成哪些步骤？（带上涉及的文件名）
3. 有哪些必须遵守的约束？

### 5.3 确定性评分

- 按 `1.` / `1、` / `1)` 等编号切段；
- 每个问题有若干**事实组**；每组给可接受的替代表述（如“计数/次数/统计/count”），任一命中即可；
- **保留率口径**：事实只要在整段回答中出现就算“还记得”（模型常把格式/约束写到另一个编号段）；
- 所有事实组都命中，该问题才通过；
- 另外记录 `local_passed`（事实在本问题自己的编号段）与 `misplaced`（只在本段外出现）；
  报表明细会标“跨段”——既不影响保留率，也不假装分段完美；
- 编号解析失败时整段答案作为兜底，并标记 `structured=False`。

这是**代理指标**，不是语义等价判断。两个典型盲区：

- 同义表述未收进词典会被判缺失（词典需要随任务维护）；
- 整段命中可能来自另一题的答案；`misplaced` 把它标出来，人工复核时优先看这些行。

因此人工标注是必要的补充，不是装饰。

## 6. 读报表与人工标注

`report.md` 先看三块：

1. **结论速览**：每个 k 的完成率、有效案例、状态保留率、平均压缩次数、成本。
2. **逐任务结果**：哪条任务在哪个 k 失败；`有效` 列是 ✅ 还是 ❌。
3. **Checkpoint 明细**：每次压缩后模型怎么回答；`跨段` 表示事实写在另一题里。

几个词：

- **完成率** = 验收通过 / 尝试次数（失败不剔除）。
- **有效案例** = 没运行错误，且实际压缩次数恰好等于 k；`k=0` 天然有效。
- **状态保留率** = checkpoint 问题通过数 / 问题总数。
- **misplaced（跨段）** = 事实出现在整段回答里、但不在该问题自己的编号段；算“记得”，
  只是位置不对，不扣保留率。

每次跑数生成 `annotations.csv`，列：

```text
run_id, task_id, bucket, strategy, template, k, repetition, compaction, question,
auto_pass, structured, misplaced, human_pass, error, answer
```

规则：

1. 在 `human_pass` 填 `1`（通过）/ `0`（不通过）/ 留空（未标注）。
2. 至少复核所有 `auto_pass=0`、`misplaced` 非空与 `structured=False` 的行；抽样复核通过行。
3. 确定性评分是主口径；人工分在报告中单列。v0 不自动合并人工分，标注表本身就是记录。

v0 基线没有 `auto_pass=0` 的行；有 4 行 `misplaced`（事实写在了另一题的答案里）。
这 4 行是作者人工复核的优先队列：确认“跨段但记得”后填 `1`，其余行可留空。
**当前基线的人工分尚未填写**——方法已文档化、标注表已生成，人工步骤属于跑数后的作者工作，
不阻塞确定性基线。

## 7. 可复现

`report.json` 的 `meta` 在**开跑前**锁定：

- `git_ref`、`git_dirty`、工作树指纹（`git diff HEAD` + 未跟踪文件的**内容哈希**，
  排除本轮 run 目录）；git 不可用时记 `null`/unknown，不冒充“干净”；
- `seed`；
- `python`、`codelotte_version`、`uv.lock` SHA-256；
- `model`、`reasoning_effort`、`context_window`、soft/hard 阈值；
- 每个任务的语义指纹与快照 commit SHA；
- 完整命令。

原始证据同目录落盘：

| 路径 | 内容 |
|---|---|
| `sessions/` | 每条案例的 append-only JSONL（含 compaction、工具链、usage）；在 run 根，不在工作区内 |
| `workspaces/` | 案例结束时的最终工作区（不含会话文件） |
| `checkpoints.jsonl` | 每次压缩后的问题、答案、命中/缺失/跨段、token |
| `report.json` | 元数据 + 全部案例的机器可读结果 |
| `report.md` | 人读报表（含 checkpoint 明细） |
| `annotations.csv` | 人工标注表 |

同一命令重跑得到新 run 目录。模型本身没有固定 temperature，请求内容可能不同；
`seed` 只固定 provider 重试抖动，不能保证逐字节复现。比较时以报表口径与重复次数为准。

## 8. v0 基线（2026-10-17）

run：`evals/runs/20261017T173510Z-037104e/`（DeepSeek `deepseek-flash`，reasoning `high`，
窗口 1,000,000，阈值 0.60/0.85，seed=0，repeat=1；12 条案例，112 次模型调用，
总成本 ¥0.265493，约 5 分钟）。

| k | 完成率 | 状态保留率 | 模型调用 | 成本 |
|---|---|---|---|---|
| 0（对照） | 3/3 (100%) | — | 21 | ¥0.011355 |
| 1 | 3/3 (100%) | 9/9 (100%) | 23 | ¥0.033721 |
| 3 | 3/3 (100%) | 27/27 (100%) | 29 | ¥0.081154 |
| 5 | 3/3 (100%) | 45/45 (100%) | 39 | ¥0.139264 |

读法：

- **完成率没有衰减**：三条任务在 k=5 仍全部通过——v0 任务太短、太简单，存在天花板效应。
- **状态保留率也没有衰减**：三个 k 合计 81/81 个问题检查全部命中（表中 9/9、27/27、45/45
  是分 k 行）。其中 4 条是**跨段命中**（模型把“不要/序号”写到了另一题的答案里），
  `misplaced` 已标出，保留率仍算记得。
- **结论**：v0 证明的是管线能跑、数据能复现、指标能区分“忘了”与“答错位置”，
  不是压缩有效性的结论。E1（票据 20）已补短任务 6 条 + 长任务 3 条、3 个策略/模板组合；
  但仍是 `repeat=1`、k 最大 5，下一轮应 `repeat >= 3`、k 扩到 10 左右。

校准阶段曾观察到 002 在 k=5 漏写 `notes.txt`。定位后不是压缩丢失，而是 Docker 的
`/workspace` 容器路径被模型交给了宿主机文件工具，产物写到了工作区外；现在
`default_tools` 在 Docker 模式下把 `/workspace/...` 映射回宿主 cwd（有测试）。
这类环境缺陷不能计入压缩曲线——修复后基线全部完成。

repeat=1 无法区分真实衰减与模型方差，这是下一轮必须扩重复的直接原因。

## 9. 已知局限

- 关键词事实比对是代理指标，不是语义判断；词典需要随任务维护。
- 保留率用整段口径，可能把“另一题里顺带提到”算作记得；`misplaced` 与人工复核负责校准。
- 强制压缩发生在每个 turn 之后，与生产软触发的“任务边界”不同——它测的是压缩**能力**，
  不是真实触发策略的频率。
- v0 任务都是合成的短任务，没有仓库快照、没有多文件长任务、没有对抗注入。
- 票据 15 新增的 004/005 是 B 桶对抗任务（注入/范围纪律），属于通用测评的首批任务；
  它们也带 checkpoint，因此会进入 `eval compaction` 的全量跑数，但不在 v0 基线里。
- v0 每个点只重复 1 次；人工标注尚未填写（标注表与优先队列已生成）。
- 默认 Docker；文件工具通过 `/workspace` 别名映射到宿主工作区（票据 13 审查修复）。
- 通用测评（pass^k、仓库快照、LLM judge、CI 冒烟）不在本票范围，见
  [run.md](run.md)。

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
| `eval compaction` 报“需要 checkpoint” | 通用任务没有 checkpoint 是合法的；改用 `eval run`，或给任务补 3 个问题 |
| 想加任务但先不跑 | `--dry-run` |

## 11. 代码地图与交接

| 文件 | 职责 |
|---|---|
| `src/codelotte/evals/tasks.py` | TOML 加载与校验（任务格式，双方共用） |
| `src/codelotte/evals/workspace.py` | 工作区准备、git 快照、确定性验收（双方共用） |
| `src/codelotte/evals/execution.py` | 单任务执行核心（双方共用） |
| `src/codelotte/evals/regression.py` | 强制压缩策略、checkpoint 探针 |
| `src/codelotte/evals/suite.py` | 任务 × k × 重复编排 |
| `src/codelotte/evals/checkpoints.py` | 编号切段、事实比对 |
| `src/codelotte/evals/report.py` | 压缩报表（Markdown/JSON/CSV/JSONL） |
| `evals/tasks/*.toml` | 任务定义 |
| `evals/runs/<run-id>/` | 跑数证据 |

接手顺序：

1. 本文件（专用测评 - 压缩回归 v0 操作）；
2. [run.md](run.md)（通用测评、任务格式、CI）；
3. 最近一次压缩基线的 `report.md`；
4. `src/codelotte/evals/`（按 tasks → workspace → execution → regression → report 读）。

跑之前先 `--dry-run`；动代码后跑 `uv run pytest tests/test_eval_*.py`。
