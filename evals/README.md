# codelotte 评估体系：总览

> 这个目录回答一个问题：**codelotte 这套 harness 到底有没有用，值多少？**
> 这里不是功能清单，而是可复现的任务、基线、指标、轨迹与失败分析。
>
> 第一次打开建议按这个顺序读：
>
> 1. §0 建立心智模型，认识几个术语；
> 2. §1 用零成本命令把评测器跑一遍；
> 3. §2 查“我要回答的问题该用哪条命令”；
> 4. §5 看命令的输入/输出与执行方式；
> 5. §7 学会读报表和产物。
>
> 需要深入时再跳转：
> [run.md](run.md)（通用测评/对照/judge/归因/任务格式）、
> [compaction.md](compaction.md)（压缩专项）、
> [attribution.md](attribution.md)（归因规则与回归任务）、
> [defense.md](defense.md)（注入与死循环防御）、
> [record.md](record.md)（全部跑数索引）。

## 0. 30 秒心智模型

```text
                    ┌──────────────────────────────┐
                    │ 任务集 evals/tasks/*.toml     │
                    │ 指令 / 初始文件 / 验收器       │
                    └──────────────┬───────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
    eval controls            eval run / compare       eval compaction
    （先证明考场可信）       （真实 agent 跑数）      （强制压缩专项）
          │                        │                        │
          └────────────────────────┴────────────────────────┘
                                   │
                    report.md / report.json
                    sessions/（轨迹）
                    workspaces/（最终产物）
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
   eval attribute            eval regression            eval cost
   （失败归因准不准）        （失败 → 复诊题）          （缓存/峰谷省多少）
                                   │
                             eval defense
                    （注入拦截 + 死循环防线 + 误报）
                                   │
                        evals/runs/（证据）+ record.md
```

一句话：**任务集是题目，controls 检查考场，run/compaction 是考试，compare 是对照实验，
judge 是主观题阅卷校准，attribute 是病历，regression 是把病例变成复诊题，cost 是账单
复盘，defense 是安全演练。**

### 0.1 术语速查

| 术语 | 在这里指什么 |
|---|---|
| **任务（task）** | 一条 `.toml`：题面 + 初始文件 + 验收器 + 预算（+ checkpoint/oracle/judge） |
| **案例（case）** | 一个任务的一次重复；报表里的一行 |
| **评测轮次（run）** | 一次评测命令生成的目录 `evals/runs/<时间>-<git ref>/`。**本文的 run 指评测轮次，不是 codelotte 单次对话的 run** |
| **repeat / pass^k** | 同一任务重复 N 次；N 次全部通过才算 pass^N。严格口径，不提供 pass@k |
| **bucket** | `A` 真实自用 / `B` 对抗构造 / `C` 公开子集 |
| **checkpoint** | 压缩后用来问模型“还记得吗”的事实组；每条确定性任务至少 3 个 |
| **harness** | 被测/对照的 agent 外壳：codelotte、mini-swe-agent、裸 API |
| **control agent** | 用来自检评测器的假 agent：oracle / no-op / cheating |
| **judge** | LLM 阅卷人；只在任务声明 `[verifier.judge]` 时启用 |
| **guardrail** | 死循环三层防御产生的事件：`repeat` / `stagnation` / `circuitBreaker` / `reinject` / `terminate` |
| **注入（injection）** | 数据文件里伪装成指令的文本；E5 检查 agent 会不会执行它 |
| **误报（false positive）** | 正常任务（A 桶）的会话里出现 `guardrail` 事件 |

## 1. 五分钟上手

### 1.1 前置条件

| 项 | 说明 |
|---|---|
| Python 3.13 + `uv` | 在仓库根目录执行 `uv run ...`；已安装 `codelotte` 时可省略 `uv run` |
| 模型与 API key | 真实跑数需要；从环境变量/用户配置读取，**不要把 key 写进任务或文档** |
| Docker | 默认沙箱；最终入库证据用它。`--no-sandbox` 只适合快速接线 |
| mini-swe-agent | 只有 `eval compare` 需要；装在单独的 `.mini-venv`，不在项目 lockfile 里 |

### 1.2 先跑离线检查（0 成本）

```bash
uv run codelotte eval run --dry-run
uv run codelotte eval compaction --dry-run
uv run codelotte eval judge --dry-run
uv run codelotte eval controls
uv run codelotte eval attribute --dry-run
uv run codelotte eval defense --dry-run
```

这些命令不调用模型、不花钱。带 `--dry-run` 的只校验并打印计划；`eval controls`
会真实执行三个假 agent 并写一个控制组 run 目录（仍然零模型、零成本）：

- `eval run --dry-run`：任务 TOML、初始文件、快照 ref、验收器是否合法；
- `eval compaction --dry-run`：任务是否有足够 checkpoint、压缩计划是否成立；
- `eval judge --dry-run`：judge 任务的样本数/路径/输出目录；
- `eval controls`：用 oracle/no-op/cheating 三个假 agent 证明评测器不瞎打分；
- `eval attribute --dry-run`：归因语料的类别和数量；
- `eval defense --dry-run`：8 个剧本的期望 guard，以及当前跑数里能读到多少案例。

### 1.3 第一次真实跑数（会产生费用）

```bash
# 最便宜的一条：单任务、单次
uv run codelotte eval run --task 001-audit-report --repeat 1
```

跑完打开新生成的：

```text
evals/runs/<新目录>/report.md
```

报表里能看到通过率、模型调用数、成本、耗时、计费时段；失败案例会给出会话路径。
确认接线正确后，再跑全量 `uv run codelotte eval run`（默认 9 任务 × 3 次）。

### 1.4 第一次读产物

先看 `report.md` 的“结论速览 → 汇总表 → 失败案例”，再看 `report.json` 的 `meta`
确认这轮数字对应哪版代码。完整读法见 §7。

## 2. 评估体系一览

### 2.1 九个命令一张表

| 命令 | 回答的问题 | 调模型？ | 需要什么材料 | 主要产出 | 典型用途 |
|---|---|---|---|---|---|
| [`eval run`](run.md) | 当前 harness 能不能过这批任务？稳定吗？每条多少钱/多久？ | ✅ | 任务 TOML + key + Docker | `runs/<id>/report.md/json`、sessions、workspaces | 日常回归、基线、pass^k |
| [`eval compaction`](compaction.md) | 上下文被强制压缩 k 次后，任务目标和关键状态还记得吗？ | ✅ | 带 ≥3 checkpoint 的任务 + key + Docker | 压缩专项报表、checkpoint 明细、`annotations.csv` | E1 压缩实验、压缩回归 |
| [`eval compare`](run.md#45-对照组eval-compare) | 同模型下 codelotte / mini-swe-agent / 裸 API 谁强？增量在哪？ | ✅ | 任务 TOML + key + Docker（+ mini-swe-agent） | 父报表 + `harnesses/<组>/` 明细 | E4 scaffolding tax 对照 |
| [`eval controls`](run.md#46-控制-agent-自检eval-controls) | 评测器本身可信吗？oracle 会 100%、no-op 会 0%、cheating 会被抓吗？ | ❌ | 带 oracle 的确定性任务 | 自检结论表 + 三组控制案例 | 改任务/评测器后的第一关 |
| [`eval judge`](run.md#47-llm-judge-与-κ-校准eval-judge) | LLM 阅卷人和人工标注一致吗？κ 是多少？ | ✅（阅卷模型） | judge 任务 + ≥20 条人工标注样本 | `evals/judges/<task>/calibration.*` | 主观题校准 |
| [`eval attribute`](attribution.md) | 失败归因规则和人工标注一致吗？真实失败怎么分布？ | ❌（规则） | `labels.jsonl` + `sessions/`；可选 run 目录 | `evals/attribution/attribution-report.*` | E3 归因准确率 |
| [`eval regression`](attribution.md#5-失败-回归任务) | 这条失败能不能变成以后每轮都跑的复诊题？ | ❌ | 一个失败 run + 原任务 id | `evals/regressions/<new-id>.toml` | 失败防复发 |
| [`eval cost`](run.md#49-成本曲线eval-cost) | 缓存和 off-peak 实际省了多少？无缓存/全峰价的反事实是多少？ | ❌（读会话） | 一个或多个 run 目录 | `evals/cost/cost-report.md/json` | E2 成本曲线 |
| [`eval defense`](defense.md) | 注入与死循环拦得住吗？正常任务会不会被误拦？ | ❌（剧本 + 读会话） | 防御/死循环/正常任务的 run；剧本离线 | `evals/defense/defense-report.md/json` + 剧本会话 | E5 防御有效性 |

完整参数用 `uv run codelotte eval --help` 或 `uv run codelotte eval <子命令> --help` 查看。

### 2.2 五个视角

| 视角 | 命令 | 一句话 |
|---|---|---|
| 能力 | `eval run` / `eval compaction` / `eval compare` | 会不会做、压缩后还记不记得、相对基线强多少 |
| 可信度 | `eval controls` / `eval judge` / `eval attribute` | 评测器、阅卷人、归因器本身靠不靠谱 |
| 成本 | `eval cost` | 实际账单与“没有缓存/全峰价”的差距 |
| 安全 | `eval defense` | 注入拦不拦、死循环防线动不动、正常任务误不误报 |
| 复发 | `eval regression` | 把一次失败固化成以后必跑的题 |

### 2.3 体系分层

| 层 | 内容 | 代表文件/命令 |
|---|---|---|
| 任务层 | 9 条确定性任务 + 3 条主观任务 + 3 条注入 + 1 条死循环压力；指令/初始文件/验收/预算/checkpoint | `evals/tasks/`、`evals/judge-tasks/`、`evals/defense-tasks/`、`evals/loop-tasks/` |
| 执行层 | codelotte loop、mini-swe-agent、裸 API、三种控制 agent；工作区准备与隔离 | `src/codelotte/evals/`、`eval compare/controls` |
| 验收层 | 确定性文件检查 / python / command；LLM judge 兜底；防篡改检查 | `workspace.py`、`judge.py` |
| 度量层 | pass^k、成本、峰谷时段、耗时、模型调用、judge κ、失败五类 | `eval_report.py`、`attribution.py`、`defense.py` |
| 证据层 | append-only 会话、最终工作区、`report.json`、实验报告 | `evals/runs/`、`docs/experiments/` |
| 校准层 | judge 与人工的一致性、归因与人工标注的一致性 | `eval judge`、`eval attribute` |
| 回归层 | 失败案例 → 永久回归任务；失败 → 复诊题 | `eval regression`、`evals/regressions/` |

## 3. 评估对象：一条任务由什么组成

### 3.1 任务文件（`.toml`）

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

关键约束：

- 验收必须**确定性**（不靠模型）；judge 只在显式声明时启用；
- 主任务集与 judge 任务的每条任务至少有一个 `unchanged` 保护文件，cheating 控制组
  才有可检测的篡改目标（死循环压力题 013 例外：它是行为题，没有 oracle/保护文件）；
- 用于压缩回归的每条**确定性任务**有 ≥3 个 checkpoint；
- 路径必须是工作区内相对路径；重复 id 直接报错。

完整字段见 [run.md §3](run.md#3-任务格式)。

### 3.2 验收器（verifier）

| 类型 | 写法 | 判定 |
|---|---|---|
| 文件内容 | `[[verifier.files]]` + `equals` / `contains` | 精确相等 / 包含 |
| 文件未被改 | `unchanged = true` | 与初始内容一致；被改则失败并标记 |
| Python 检查 | `verifier.python = "..."` | 工作区内执行，退出码 0 通过 |
| 命令检查 | `verifier.command = ["python", "check.py"]` | 不经 shell；退出码 0 通过 |
| LLM judge | `[verifier.judge]` | 确定性检查通过后，按评分卡打分 |

**确定性优先**：没有声明 judge 的任务零 judge 调用；确定性检查失败时也不调用 judge。

### 3.3 checkpoint

压缩回归的带外探针：每次强制压缩后，问“任务目标 / 已完成步骤 / 关键约束”，
按事实组（同义词数组）确定性评分。通用 `eval run` 可省略；`eval compaction` 需要
每条任务至少 3 个。

### 3.4 控制 agent 与 oracle

| 控制 agent | 行为 | 预期 |
|---|---|---|
| `oracle` | 直接写 `[control.oracle.files]` 参考解 | 100% 通过 |
| `no-op` | 什么都不做 | 0% 通过 |
| `cheating` | 写假成功内容 + 篡改 `unchanged` 文件 | 0% 通过且全部被标记 |

任何一条不符，先修评测器，再相信真实跑分。

### 3.5 会话与工作区

| 文件 | 位置 | 说明 |
|---|---|---|
| codelotte 会话 | `evals/runs/<run>/sessions/<case>/*.jsonl` | append-only，含工具调用、usage、压缩、guardrail；**事实源** |
| mini-swe-agent 轨迹 | `evals/runs/<run>/harnesses/mini-swe-agent/sessions/*.traj.json` | mini 的 JSON 轨迹 |
| 裸 API 轨迹 | `evals/runs/<run>/harnesses/raw/sessions/*.jsonl` | 请求/回答/usage |
| 归因样本轨迹 | `evals/attribution/sessions/*.jsonl` | 手工构造的失败轨迹 |
| judge 标注样本 | `evals/judges/<task>/samples.jsonl` | 提交文本 + 人工 `human_pass` |
| 防御剧本会话 | `evals/defense/sessions/*.jsonl` | 8 个死循环/正常剧本 |

`workspaces/<case>/` 是每条案例的最终产物。它可能被 cheating 控制组故意写坏，
是证据，不是源码。

## 4. 目录地图

| 路径 | 放什么 | 谁生成 | 进默认 `eval run` 吗 |
|---|---|---|---|
| [`tasks/`](tasks/) | **确定性任务**：9 条 TOML。初始文件、指令、验收器、预算、checkpoint、oracle、保护文件 | 作者手写 | ✅ |
| [`judge-tasks/`](judge-tasks/) | **主观任务**：3 条 TOML，声明 `[verifier.judge]` 评分卡与校准路径 | 作者手写 | ❌（单独目录） |
| [`judges/<task>/`](judges/) | judge 校准资产：`samples.jsonl`、`calibration.json`、`calibration.md` | `eval judge` 生成 | — |
| [`attribution/`](attribution/) | 失败归因语料：`labels.jsonl`、`sessions/*.jsonl`、`attribution-report.*` | 作者手写 + `eval attribute` 生成 | — |
| [`regressions/`](regressions/) | 由失败案例生成的回归任务 TOML | `eval regression` 生成 | ❌（需 `--tasks evals/regressions`） |
| [`cost/`](cost/) | E2 成本曲线：`cost-report.md` / `.json` | `eval cost` 生成 | — |
| [`defense-tasks/`](defense-tasks/) | **E5 注入任务**：3 条 TOML（010–012） | 作者手写 | ❌（需 `--tasks evals/defense-tasks`） |
| [`loop-tasks/`](loop-tasks/) | **E5 死循环压力**：1 条 TOML（013）；没有 oracle | 作者手写 | ❌（需 `--tasks evals/loop-tasks`） |
| [`defense/`](defense/) | E5 防御报告与 8 个剧本会话 | `eval defense` 生成 | — |
| [`runs/`](runs/) | **跑数证据**：每次评测一个目录，含报表、轨迹、最终工作区 | 各评测命令生成 | — |
| [`run.md`](run.md) | 通用测评、对照、自检、judge、归因、任务格式的操作手册 | 文档 | — |
| [`compaction.md`](compaction.md) | 压缩专项的操作手册、评分与 v0 基线 | 文档 | — |
| [`attribution.md`](attribution.md) | 五类失败归因规则、语料与回归任务 | 文档 | — |
| [`defense.md`](defense.md) | 注入任务、死循环压力、剧本与误报审计的完整手册 | 文档 | — |
| [`record.md`](record.md) | 所有已入库跑数的索引、目录约定与记录表 | 文档 | — |

## 5. 九个命令详解

### 5.1 `eval run`：通用测评（主线）

**什么时候用**：改完 harness、想确认当前通过率/成本/耗时、需要一条可入库的基线。

**需要什么**：`evals/tasks/` 的 TOML、可用的模型配置与 API key、默认 Docker。

```bash
uv run codelotte eval run --dry-run          # 只校验任务，不花钱
uv run codelotte eval run --repeat 3         # 9 任务 × 3 次
uv run codelotte eval run --bucket B --repeat 1
uv run codelotte eval run --task 001-audit-report --repeat 1
```

**产出**：`evals/runs/<run-id>/report.md`、`report.json`、`sessions/`、`workspaces/`。

**注意**：

- 每条任务重复 N 次，算 **pass^N**：全部重复都通过才算过；任何一次失败/运行错误都记 ❌；
- 失败后自动跑五类归因（只对 codelotte 轨迹），写进“失败归因”段；
- 退出码 `1` 只在**运行错误**（`case.error`）时出现；任务本身失败不会让命令返回 1，
  要看报表的通过率。详细口径见 [run.md §4](run.md#4-通用测评eval-run)。

### 5.2 `eval compaction`：强制压缩专项

**什么时候用**：研究“压缩后还记得吗”，跑 E1 矩阵或压缩回归。

**需要什么**：带 ≥3 checkpoint 的任务、key、Docker。

```bash
uv run codelotte eval compaction --k 0,1,3,5 --repeat 1

# E1 矩阵：摘要模板 seven/compact × 切点策略 minimal/wide
uv run codelotte eval compaction --k 0,1,3,5 --repeat 1 \
  --combo minimal:seven --combo minimal:compact --combo wide:seven
```

**产出**：压缩专项报表 + checkpoint 明细；除通用四件套外还有 `annotations.csv` /
`checkpoints.jsonl`。

**注意**：回答的是“压缩后还记得吗”，不是“整体能不能过”；整体能力看 `eval run`。
模板 `seven`/`compact`、切点 `minimal`/`wide` 的含义与 v0 基线见
[compaction.md](compaction.md)。

### 5.3 `eval compare`：scaffolding tax 对照

**什么时候用**：想区分“模型的功劳”和“harness 的增量”，做 E4 对照。

**需要什么**：任务集、key、Docker；跑 mini-swe-agent 组还需要 `.mini-venv`。

```bash
uv run codelotte eval compare --repeat 2 \
  --mini-python .mini-venv/Scripts/python.exe

# 只跑被测 harness，先验证接线
uv run codelotte eval compare --harness codelotte --repeat 1
```

**三组**：

| 组 | 作用 |
|---|---|
| `codelotte` | 被测 harness（四工具 + 权限/防线/压缩/会话） |
| `mini-swe-agent` | 参照 harness（开源教学级，只有 bash） |
| `raw` | 裸单轮 API（无 tools），代表“只有模型”的下界 |

**产出**：父目录 `report.md/json` + 每组 `harnesses/<组>/report.md/json`、sessions、
workspaces。

**注意**：三组使用同一模型、同一任务集、同一 `--repeat`；`--no-sandbox` 主要用于和
mini 的本地环境对齐，正式对照仍建议 Docker。最新 E4 结果见
[docs/experiments/e4-scaffolding-tax.md](../docs/experiments/e4-scaffolding-tax.md)。

### 5.4 `eval controls`：评测器自检（先信考场）

**什么时候用**：每次改任务、验收器或评测执行代码之后；跑真实分数之前。

```bash
uv run codelotte eval controls
uv run codelotte eval controls --tasks evals/defense-tasks
```

**需要什么**：带 oracle 的确定性任务；不需要 key/Docker，几秒钟跑完。

**产出**：控制组 run 目录（`harnesses/oracle|no-op|cheating/`）+ 父报表“自检结论”。

**注意**：judge 任务会被跳过（控制组必须离线）；`loop-tasks/` 没有 oracle，不要对它跑
controls。任何一项不符，CLI 返回 `1`：**先修评测器，再相信任何真实跑分。**

### 5.5 `eval judge`：LLM 阅卷与 κ 校准

**什么时候用**：新增主观任务、改评分卡、想确认 judge 与人工是否一致。

**需要什么**：`evals/judge-tasks/` 里的任务、每个任务 ≥20 条
人工标注样本、阅卷模型 key。

```bash
uv run codelotte eval judge --dry-run
uv run codelotte eval judge --task 101-concurrency-review \
  --task 102-api-design-tradeoffs
```

**产出**：`evals/judges/<task>/calibration.json` 与 `.md`（κ、一致率、样本数、标注者、
绑定指纹、逐样本结果）。

**注意**：低 κ、样本不足、校准缺失、标注者含 `draft` 都会在报表标 ⚠，命令返回 `1`；
校准文件绑定 `task_id` / `model` / rubric 指纹 / 样本哈希，任一变化旧 κ 会提示重跑。
当前三个 judge 任务各 20 条 `author-draft` 样本，κ=1.000，**草稿值待作者复核**。

### 5.6 `eval attribute`：失败归因准确率

**什么时候用**：想验证五类归因规则本身准不准，或汇总真实失败分布。

**需要什么**：`evals/attribution/labels.jsonl` + `sessions/`；`--run` 额外需要 run 目录。

```bash
uv run codelotte eval attribute
uv run codelotte eval attribute --run evals/runs   # 同时汇总真实失败分布
```

**产出**：`evals/attribution/attribution-report.md/json`（准确率、逐类精确率/召回率/F1、
宏观 F1、混淆矩阵、逐条证据、失败分布）。

**注意**：语料是作者草稿时报告标 ⚠、退出码 `1`（当前就是 1）；归因规则与优先级见
[attribution.md](attribution.md)；E3 结果见
[docs/experiments/e3-attribution-accuracy.md](../docs/experiments/e3-attribution-accuracy.md)。

### 5.7 `eval regression`：失败 → 回归任务

**什么时候用**：一轮评测出现真实失败，想把“这个坑”固化成以后每轮都跑的题。

**需要什么**：一个含 `report.json` 的失败 run + 原任务 id。

```bash
uv run codelotte eval regression \
  --run evals/runs/<run-id> --task 002-fix-off-by-one --dry-run
uv run codelotte eval regression \
  --run evals/runs/<run-id> --task 002-fix-off-by-one
```

**产出**：`evals/regressions/<new-id>.toml`（默认），保留原任务的 setup/verifier/预算/
参考解，只换 `id`，文件头写明来源、归因与失败详情。

**注意**：不覆盖已有文件；写完再用 `load_task` 校验；不参与默认 `eval run`，要跑回归集用
`uv run codelotte eval run --tasks evals/regressions`。

### 5.8 `eval cost`：缓存与 off-peak 成本曲线

**什么时候用**：想知道账单里缓存和低峰时段实际省了多少，做 E2 成本实验。

**需要什么**：一个或多个带 `report.json` 和 codelotte 会话的 run 目录。

```bash
uv run codelotte eval cost \
  --run evals/runs/<run-id> \
  --run evals/runs/<another-run> \
  --out evals/cost
```

**产出**：`evals/cost/cost-report.md/json`：实际成本、缓存命中率、off-peak 调用占比、
逐调用序号命中率曲线，以及“无缓存 / 全峰价 / 两者叠加”的反事实与节省金额。

**注意**：反事实是**重算**，不是重新跑模型；只覆盖会话 usage（压缩探针不写回会话）；
价目来自随包 `providers/models.json`。最新解读见
[docs/experiments/e2-cost-curve.md](../docs/experiments/e2-cost-curve.md)。

### 5.9 `eval defense`：注入与死循环防御有效性

**什么时候用**：想验证死循环三层防线、真实模型重复压力、注入拦截与正常任务误报。

**需要什么**：`defense-tasks/`、`loop-tasks/` 与至少一条 A 桶正常任务的 run（误报审计
需要正常案例）；主任务集 004/005 的 run 可选，有则一起汇总；剧本与汇总离线。

```bash
uv run codelotte eval defense --dry-run
uv run codelotte eval defense --run evals/runs --out evals/defense
```

**产出**：`evals/defense/defense-report.md/json` + `evals/defense/sessions/*.jsonl`。

**注意**：它不调用模型；8 个剧本用真实 `AgentLoop` + 脚本化 Provider 驱动生产
guardrails；注入/压力/误报都读已有真实跑数。退出码 `0` = 四类证据全部达标、`1` = 任一
未达标、`2` = 路径/配置错误。完整口径、任务清单、常见问题与复现命令见
[defense.md](defense.md)。

## 6. 推荐工作流

### 6.1 改任务或评测器之后

```bash
uv run codelotte eval run --dry-run
uv run codelotte eval controls
```

先证明任务能加载、考场不瞎打分，再花真钱。

### 6.2 改 harness 之后（日常回归）

```bash
uv run codelotte eval run --repeat 3
```

看通过率、pass^3、成本、耗时、失败归因；失败案例再决定是否转回归任务。

### 6.3 做一轮完整实验

```bash
# 1) 离线自检
uv run codelotte eval controls

# 2) 通用测评
uv run codelotte eval run --repeat 3

# 3) 三组对照（同任务、同模型）
uv run codelotte eval compare --repeat 2 \
  --mini-python .mini-venv/Scripts/python.exe

# 4) 主观任务：先校准，再跑
uv run codelotte eval judge --dry-run
uv run codelotte eval judge
uv run codelotte eval run --tasks evals/judge-tasks --repeat 1

# 5) 归因、成本、防御（离线）
uv run codelotte eval attribute --run evals/runs
uv run codelotte eval cost --run evals/runs/<run-id> --out evals/cost
uv run codelotte eval defense --run evals/runs

# 6) 失败 → 回归任务
uv run codelotte eval regression --run evals/runs/<run-id> --task <id>

# 7) 把新 run 写进 record.md
```

### 6.4 一条失败的完整链路

```text
eval run / compare
      │ 某条案例 ❌
      ▼
report.md 的“失败归因”段
      │ 五类之一 + 证据 + 置信度
      ├─ 想提高归因可信度 → eval attribute（人工语料对照 + 真实失败分布）
      └─ 想防复发 → eval regression（生成回归任务）
                         │
                         ▼
                 eval run --tasks evals/regressions

想证明“拦得住” → eval defense（注入拦截 + 死循环剧本 + 误报审计）
```

## 7. 产物与读法

### 7.1 一次 run 里有什么

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

- 跑数目录**不手工编辑**；要新数字就重跑，历史目录不覆盖；
- 每个 run 的 `meta` 锁定 git ref、工作树指纹、seed、Python/codelotte 版本、
  `uv.lock` SHA、模型/窗口、任务语义指纹与完整命令。

### 7.2 读 `report.md` 的顺序

1. **结论速览**：任务数、通过率、pass^k、总成本/耗时、计费时段；
2. **汇总表**：哪条任务失败、每条调用/成本/耗时；
3. **失败归因**：五类分布与逐条证据（只有 codelotte 轨迹有）；
4. **失败案例**：会话路径与验收详情；
5. **LLM judge**（如果任务声明了）：分数/理由/κ/⚠；
6. **复现锁定**：git ref、工作树指纹、模型、任务指纹。

### 7.3 非 run 产物

| 产物 | 位置 | 内容 |
|---|---|---|
| judge 校准 | `evals/judges/<task>/calibration.json/.md` | κ、一致率、样本数、标注者、逐样本结果 |
| 归因报告 | `evals/attribution/attribution-report.md/.json` | 准确率、逐类指标、混淆矩阵、失败分布 |
| 成本报告 | `evals/cost/cost-report.md/.json` | 实际/反事实成本、缓存命中率、节省 |
| 防御报告 | `evals/defense/defense-report.md/.json` | 剧本、注入、压力、误报四类证据 |
| 回归任务 | `evals/regressions/<new-id>.toml` | 可直接被 `eval run` 读取的新任务 |
| 剧本会话 | `evals/defense/sessions/*.jsonl` | 8 个死循环/正常剧本的轨迹 |

### 7.4 失败定位

- 通用测评：`report.md` 的“失败案例”+“失败归因”，再打开对应 `sessions/`；
- 压缩回归：逐案例表 + checkpoint 明细 + `annotations.csv`；
- 对照/自检：父报表“失败定位”段，按组给轨迹路径；
- 防御：先看 `defense-report.md` 的逐任务表，再打开剧本会话或真实 run 的会话。

## 8. 当前基线（2026-10-18/19）

| 评测 | 结果 | 证据 |
|---|---|---|
| 正式 `eval run`（9 任务 × 3 次，Docker） | 27/27 通过，pass^3 9/9，188 调用，¥0.205832，349.0s | [`runs/20261018T154112Z-fa9db83`](runs/20261018T154112Z-fa9db83/report.md) |
| E4 对照（3 组 × 9 任务 × 2 次） | codelotte 18/18、mini 18/18、raw 0/18；codelotte 成本 +15.4%、耗时 −33.5% | [`runs/20261018T155840Z-fa9db83-compare`](runs/20261018T155840Z-fa9db83-compare/report.md) |
| 控制组自检（9 任务） | oracle 9/9、no-op 0/9、cheating 0/9 且 9/9 标记 | [`runs/20261018T154851Z-fa9db83-controls`](runs/20261018T154851Z-fa9db83-controls/report.md) |
| judge 任务（3 条） | 3/3 通过，overall 均 1.00，κ=1.00（各 20 样本，⚠ 草稿） | [`runs/20261018T154901Z-fa9db83`](runs/20261018T154901Z-fa9db83/report.md) |
| 归因准确率（15 条语料） | 15/15（100%），宏观 F1 1.000，⚠ `author-draft` 待复核；真实 codelotte 失败 0 条 | [attribution-report.md](attribution/attribution-report.md) |
| E1 压缩矩阵（短任务 6 + 长任务 3） | 短任务完成率/保留率 100%（天花板）；长任务保留率 83–97%，compact **93.3% vs 87.8%** 且成本 −23.1%；wide 短任务 +15.8% 但 6/6 有效 | [`短任务`](runs/20261018T165516Z-8a01d9f/report.md) · [`长任务`](runs/20261019T013233Z-8a01d9f/report.md) |
| E2 成本曲线（2 个 run） | 缓存命中率 89.0% / 89.4%；相对无缓存+全峰价总节省 80.8% / 81.4% | [cost-report.md](cost/cost-report.md) |
| 压缩回归 v0（旧 3 任务） | 完成率/保留率 100%，天花板效应 | [`runs/20261017T173510Z-037104e`](runs/20261017T173510Z-037104e/report.md) |
| E5 防御有效性 | 死循环剧本 5/5、正常剧本 0/3、真实压力 3/3、注入 27/27、正常任务误报 0/31 | [defense-report.md](defense/defense-report.md) |

数字口径、完整记录与复现命令：[record.md](record.md)。实验解读：
[E1](../docs/experiments/e1-compaction-curve.md) ·
[E2](../docs/experiments/e2-cost-curve.md) ·
[E3](../docs/experiments/e3-attribution-accuracy.md) ·
[E4](../docs/experiments/e4-scaffolding-tax.md) ·
[E5](../docs/experiments/e5-defense-effectiveness.md)。

## 9. 已知边界

- 任务只有 9 条（+ 3 条 judge + 3 条注入 + 1 条死循环），且由作者构造；存在
  “为 codelotte 量身定做”的偏差。
- judge 校准与归因语料都是 `author-draft`：κ/准确率只证明管线可用，不是人工复核结论。
- 成功率的样本量小（每任务 2–3 次），没有置信区间；看趋势而不是单点。
- 已入库 run 里 codelotte 的真实失败为 0，失败分布目前是空的；这不是归因器可靠的证明，
  而是任务集难度的上限。
- mini-swe-agent 是外部依赖，不在项目 lockfile 里；安装方式与 Windows shell 修正见
  [run.md §4.5](run.md#45-对照组eval-compare)。
- 压缩基线是旧 3 任务、天花板效应；E1/E2 的完整矩阵见对应实验报告。
- E5 的死循环剧本是脚本化行为，注入拦截是任务集上的模型行为，不是运行时安全边界；
  详见 [defense.md §7](defense.md#7-口径与局限)。

## 10. 代码地图

| 路径 | 职责 |
|---|---|
| `src/codelotte/evals/tasks.py` | TOML 加载/校验（任务、验收器、checkpoint、judge、参考解） |
| `src/codelotte/evals/workspace.py` | 工作区准备、git 快照、确定性验收、防篡改检查 |
| `src/codelotte/evals/execution.py` | 单任务执行核心（codelotte loop、预算、成本/时段、验收、judge） |
| `src/codelotte/evals/runner.py` | 任务 × 重复编排、pass^k 数据、失败归因 |
| `src/codelotte/evals/eval_report.py` | 通用报表（Markdown/JSON）与失败归因段 |
| `src/codelotte/evals/compare.py` | 多组对照、控制 agent 自检、并列报表 |
| `src/codelotte/compaction/` / `src/codelotte/evals/regression.py` | 压缩触发/摘要与强制压缩回归 |
| `src/codelotte/evals/judge.py` | judge 评分卡、κ、校准文件 |
| `src/codelotte/evals/attribution.py` | 五类归因、语料评测、混淆矩阵、失败分布 |
| `src/codelotte/evals/promote.py` | 失败案例 → 回归任务 TOML |
| `src/codelotte/evals/defense.py` | E5 剧本、注入/压力/误报聚合与报告 |
| `src/codelotte/evals/cost_report.py` | 成本曲线与反事实重算 |
| `src/codelotte/evals/mini_baseline.py` / `mini_runner.py` | mini-swe-agent 外部进程适配 |
| `src/codelotte/evals/mini_proxy.py` | 本地录制代理（假 key、真实 usage） |
| `tests/test_eval_*.py` | 任务加载、评分、运行、报表、judge、归因、防御的自动化测试 |

## 11. 继续读

| 想做什么 | 读哪份 |
|---|---|
| 跑通用测评、对照、自检、judge、归因，或新增任务 | [run.md](run.md) |
| 跑压缩回归、理解 checkpoint 与 E1 矩阵 | [compaction.md](compaction.md) |
| 理解五类归因规则、语料与失败 → 回归任务 | [attribution.md](attribution.md) |
| 跑注入/死循环/误报实验，新增防御任务 | [defense.md](defense.md) |
| 查历史跑数、目录约定、基线记录 | [record.md](record.md) |
| 看 E1–E5 实验结论与口径 | [docs/experiments/](../docs/experiments/README.md) |
| 看项目整体定位与里程碑 | [../README.md](../README.md) · [../PLAN.md](../PLAN.md) |
