# 通用测评：操作手册

> 给未来的我和接手的人。想加题、重跑、看报表、交接，从这里开始。
>
> - 专用测评 - 压缩回归 v0（强制压缩 k 次、checkpoint 保留率、v0 基线）：
>   [compaction.md](compaction.md)
> - 对照组与控制 agent 自检（票据 16）：本文件 §4.5 / §4.6
> - 跑数记录：[record.md](record.md)
> - 任务定义：[evals/tasks/*.toml](tasks/)

## 0. 30 秒版

```bash
# 1. 只校验任务文件/快照 ref，不调用模型、不花钱
uv run codelotte eval run --dry-run
uv run codelotte eval compaction --dry-run

# 2. 通用测评：全部任务 × 3 次重复（pass^3、每任务成本/耗时）
uv run codelotte eval run

# 3. 只跑 B 桶（对抗构造），先花小钱验证接线
uv run codelotte eval run --bucket B --repeat 1

# 4. 压缩回归：强制压缩 k=0/1/3/5，测 checkpoint 状态保留率
uv run codelotte eval compaction --k 0,1,3,5

# 5. 控制 agent 自检（离线、零成本；不需要密钥/Docker）
uv run codelotte eval controls

# 6. 对照组：codelotte / mini-swe-agent / 裸单轮 API 跑同一任务集
uv run codelotte eval compare --repeat 1 --no-sandbox

# 7. 打开最新 run 的报表
#    evals/runs/<新目录>/report.md
```

已经装有 `codelotte` 命令时，把 `uv run codelotte` 换成 `codelotte` 即可。

## 1. 四个命令在干什么

- `eval run`（票据 15）：**通用测评**。任务按生产默认策略跑 N 次，回答“当前 harness
  能不能过、每条任务花多少钱/多久、pass^N 是多少”。
- `eval compaction`（票据 13）：**专用测评 - 压缩回归 v0**。强制压缩 k 次，回答
  “压缩后还记得任务吗”。
- `eval compare`（票据 16）：**对照组**。同一任务集分别跑 codelotte、mini-swe-agent
  和裸单轮 API，回答“模型自身的功劳 vs harness 的增量”（scaffolding tax）。
- `eval controls`（票据 16）：**控制 agent 自检**。oracle 应 100%、no-op 应 0%、
  cheating 应 0% 且被标记；先证明评测器不瞎打分，再相信任何真实跑分。

四者共用任务格式、工作区与验收代码，但报表口径不同。日常回归用 `eval run`；
压缩专项用 `eval compaction`（细节见 [compaction.md](compaction.md)）；对照与自检
见 §4.5 / §4.6。

## 2. 目录地图

| 路径 | 作用 |
|---|---|
| `evals/tasks/*.toml` | **题目定义**：初始文件/仓库快照、指令、验收器、checkpoint |
| `evals/runs/<run-id>/` | **一次跑数的全部证据**；每次新建，不覆盖 |
| `src/codelotte/evals/` | 实现：加载任务、通用测评、强制压缩、探针、评分、报表 |
| `evals/compaction.md` | 专用测评 - 压缩回归 v0 手册（机制、评分、基线、人工标注） |
| `tests/test_eval_*.py` | 自动化测试（加载/评分/运行/报表/CLI） |

## 3. 任务格式

### 3.1 最小模板

把下面内容复制成 `evals/tasks/006-your-task.toml`，改字段即可：

```toml
id = "006-your-task"          # 唯一；建议 NNN-slug
bucket = "A"                  # A 真实自用 / B 对抗构造 / C 公开子集
timeout_seconds = 300
max_model_calls = 30          # 软上限：usage 在调用完成后才到，最多越过一格

instruction = """
用一句话写清任务。若要 k=5 次压缩，题面必须包含足够多的顺序步骤，
并写“一次只做一个动作”，例如：
先 read in.txt；再 write out.txt；最后 read out.txt 确认。
"""

[setup.files]
"in.txt" = """hello
"""

# 可选：从 git ref 抽仓库快照（先抽快照，再用上面的 files 覆盖）
# [setup.snapshot]
# ref = "HEAD"                 # commit / tag / branch；开跑前解析成 SHA
# repo = "."                   # 相对评测仓库根；默认就是评测仓库本身
# script = "uv sync --locked"  # 可选初始化脚本（可信输入）

[verifier]
# 命令式验收：字符串数组，不经 shell 解析
# command = ["python", "check.py"]
# command_timeout = 60
# 或在工作区跑一段 Python（退出码 0 = 通过）
python = """
assert open("out.txt", encoding="utf-8").read().strip() == "hello"
print("ok")
"""
# 文件内容期望：equals / contains / unchanged 三选一
[[verifier.files]]
path = "out.txt"
equals = """hello
"""

[[checkpoints]]
question = "任务目标是什么？"
facts = [
  ["out.txt"],                 # 事实组 1：任一替代表述命中即可
  ["in.txt"],
]

[[checkpoints]]
question = "已经完成哪些步骤？（请带上涉及的文件名）"
facts = [
  ["read", "读取", "读了"],
  ["in.txt"],
]

[[checkpoints]]
question = "有哪些必须遵守的约束？"
facts = [
  ["out.txt"],
  ["不要", "不得", "不能"],
]
```

五条任务的实际例子：`001-audit-report.toml`（文件计数）、`002-fix-off-by-one.toml`
（修 bug + 复跑）、`003-constrained-append.toml`（多约束 + 长操作链）、
`004-prompt-injection-resistance.toml`（注入数据）、`005-scope-discipline.toml`
（受保护文件 + 范围纪律）。

### 3.2 字段速查

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一；用于 `--task`、目录名、报表 |
| `bucket` | 是 | `A` 真实自用 / `B` 对抗构造 / `C` 公开子集 |
| `instruction` | 是 | 发给模型的题面；决定它做多少步 |
| `setup.files` | 与 snapshot 二选一或叠加 | `路径 = "内容"`；路径必须是工作区内相对路径 |
| `setup.snapshot` | 与 files 二选一或叠加 | `ref` 必填；`repo` / `script` / `timeout_seconds` 可选 |
| `verifier` | 是 | 必须至少有一个 `command`、`python` 或 `files` 期望 |
| `[[verifier.files]]` | 否 | `path` + `equals`/`contains`/`unchanged` 三选一 |
| `verifier.python` | 否 | 在工作区执行 `python -c`，退出码 0 即通过 |
| `verifier.command` | 否 | 字符串数组（如 `["python", "check.py"]`）；不经 shell |
| `verifier.command_timeout` | 否 | 默认 60 秒 |
| `[[checkpoints]]` | 压缩回归必填 | 通用测评可省略；每个含 `question` + `facts` |
| `checkpoint.facts` | 是（写了 checkpoint 时） | 数组的数组：每个内层数组是一组替代表述 |
| `timeout_seconds` | 否 | 默认 300；单案例墙钟超时 |
| `max_model_calls` | 否 | 默认 40；超过后中止并记错误（软上限） |

校验在加载时完成：路径必须留在工作区/评测仓库内（拒绝绝对路径、`..`、盘符相对路径）；
验收器不能为空；重复任务 id 直接报错。任务语义指纹（含快照定义）写进报表，改缩进不影响复现。

### 3.3 验收器（verifier）

三种文件期望：

```toml
[[verifier.files]]
path = "out.txt"
equals = """精确内容
"""                       # 换行统一为 LF；末尾空行容忍
```

```toml
[[verifier.files]]
path = "notes.txt"
contains = "for i in range(n):"   # 包含子串
```

```toml
[[verifier.files]]
path = "data.txt"
unchanged = true                  # 必须与 agent 动手前的基线一字不差
```

`unchanged` 的基线在 agent 动手前捕获，所以快照/初始化脚本产生的文件也能用；
不是只看 `setup.files`。

Python 验收器在工作区里跑，可以直接 import 工作区文件：

```toml
[verifier]
python = """
from calc import sum_first_n
assert sum_first_n([1, 2, 3, 4], 2) == 3
print("ok")
"""
```

命令验收器适合跑测试（数组形式，不经 shell）：

```toml
[verifier]
command = ["python", "check.py"]
command_timeout = 60
```

验收器必须**确定性**：不看当前时间、不联网、不依赖随机数。命令式检查优先，
LLM judge 是票据 17 的兜底；未声明 judge 的任务不会走 judge。

### 3.4 仓库快照

要从某个 git ref 的历史版本开始，用 `[setup.snapshot]` 代替/叠加 `[setup.files]`：

```toml
[setup.snapshot]
ref = "b391b22"                # commit / tag / branch；开跑前解析成 SHA
repo = "."                     # 相对评测仓库根（默认就是评测仓库本身）
script = "uv sync --locked"    # 可选；在工作区执行，失败即案例失败
timeout_seconds = 120
```

- `ref` 在**开跑前**解析成 commit SHA，写进 `meta.tasks[].snapshot_ref`；同一轮所有重复使用同一个 SHA。
- 抽取用 `git archive`，不会碰评测仓库的工作树；快照先抽，`setup.files` 后覆盖。
- 快照任务适合“在某个历史版本上修 bug / 复现实验”；当前首批任务都用 `setup.files`，
  快照路径有自动化测试。
- `script` 是可信输入（实验者写的）；不要运行来路不明的任务文件。

### 3.5 Checkpoint

`checkpoints` 只被 `eval compaction` 使用；`eval run` 的任务可以完全不写。
写法（每个问题 2–4 个事实组、每组 1–5 个替代表述）、评分口径与人工标注见
[compaction.md](compaction.md)。

### 3.6 设计任务时先想清楚

1. **k 次压缩需要至少 k 个 turn**。一个 turn = 一次 assistant 回复 + 它声明的工具链。
   想稳定支撑 k=5，题面至少要有 5 个必须依次执行的工具动作。
2. **写“一次只做一个动作”**，否则模型可能一次 read 三个文件 / 一次 write 全部内容，
   压缩次数不足，案例会被标为无效。
3. **先 `eval run --repeat 1` 试跑**：验收器都过不了，说明题目/验收器有问题；
   不要归因给压缩。
4. **再做压缩试跑**：先 `--k 0`，再 `--k 5` 确认能压到 5/5，最后跑全量。
5. **setup 要能让模型自己找到答案**：不要依赖工作区外的文件、网络或未说明的约定。
6. **仓库快照要锁具体 ref**：`HEAD` 会在提交后移动；正式跑数优先写 commit SHA，
   runner 会在开跑前把它解析成 SHA 并记进报表。
7. **通用测评不需要 checkpoint**：只有压缩回归才要求 3 个问题；别为了 `eval run`
   硬凑 checkpoint。
8. **不要放模板 `.toml` 进 `evals/tasks/`**：加载器会把目录下所有 `*.toml` 当任务；
   模板就写在上面这段代码块里。

### 3.7 校验与试跑

```bash
# 只校验，不花钱（通用测评 + 压缩回归都校验）
uv run codelotte eval run --dry-run
uv run codelotte eval compaction --dry-run

# 通用测评：单条任务跑 1 次（接线是否正确？）
uv run codelotte eval run --task 006-your-task --repeat 1 --out evals/runs

# 通用测评：单条任务跑 3 次（pass^3）
uv run codelotte eval run --task 006-your-task --repeat 3 --out evals/runs

# 压缩回归：单条任务不压缩（题目本身可解吗？）
uv run codelotte eval compaction --k 0 --task 006-your-task --out evals/runs

# 压缩回归：单条任务压 5 次（turn 够吗？）
uv run codelotte eval compaction --k 5 --task 006-your-task --out evals/runs
```

### 3.8 常见校验错误

| 报错 | 修法 |
|---|---|
| `缺少字段 …` | 补齐 `id/bucket/instruction/setup/verifier`（压缩回归还需 checkpoints） |
| `必须是工作区内的相对路径` | 去掉绝对路径、`..`、`C:foo` 盘符相对路径 |
| `verifier：至少给 files 期望或 python 检查` | 加验收器（`command` / `python` / `files` 至少一个） |
| `重复的任务 id` | 两个 TOML 用了同一个 `id` |
| `每个事实组必须是非空数组` | `facts = [[...]]`，不要写成扁平字符串数组 |
| `bucket 只能是 A/B/C` | 改 `bucket` |
| `setup 至少要给 files 或 snapshot` | 至少写一个 `[setup.files]` 或 `[setup.snapshot]` |
| `verifier.command 要是非空字符串数组` | 写成 `["python", "check.py"]`，不要写成一整条 shell 字符串 |
| `仓库快照 ref 解析失败` | 检查 ref 是否存在、`repo` 是否相对评测仓库根；先跑 `--dry-run` |
| `eval compaction` 报“需要 checkpoint” | 通用任务没有 checkpoint 是合法的；改用 `eval run`，或给任务补 3 个问题 |

## 4. 通用测评（`eval run`）

### 4.1 参数

```bash
# 全部任务 × 3 次重复（默认 repeat=3），输出 pass^3、每任务成本/耗时
codelotte eval run

# 只跑 B 桶（对抗构造）
codelotte eval run --bucket B

# 只跑一条任务，先花小钱验证接线
codelotte eval run --task 004-prompt-injection-resistance --repeat 1

# 只校验任务文件与仓库快照 ref，不调用模型、不建 run 目录
codelotte eval run --dry-run
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--tasks` | `<repo>/evals/tasks` | 任务目录（`*.toml`） |
| `--out` | `<repo>/evals/runs` | 跑数根目录；每次新建 `<UTC 时间>-<git ref 前 7 位>/` |
| `--repeat` | `3` | 每个任务重复次数；`pass^N` 要求 N 次全部通过 |
| `--seed` | `0` | 随机种子（provider 重试抖动） |
| `--task` | 全部 | 只跑指定任务 id（可重复） |
| `--bucket` | 全部 | 只跑指定桶 `A/B/C`（可重复） |
| `--dry-run` | 关 | 只校验任务与快照 ref，打印计划 |
| `--no-sandbox` | 关 | 任务命令直接在宿主机执行（默认 Docker） |

退出码：`0` = 报表生成且没有运行错误；`1` = 有案例运行错误（任务本身失败不算）；
`2` = 用法/配置错误。

### 4.2 pass^k 与报表口径

- **pass^k**：一条任务的 **全部 k 次重复都通过**才算 pass^k；少跑一次、失败一次或运行错误都记 0。
- **成功率**：通过案例 / 尝试案例；运行错误也是失败，不剔除。
- **成本**：每次模型调用的 `usage` 记录之和（人民币元）；不含验收命令。
- **计费时段**：每条 usage 记录的实际 `period`（峰值 / 低谷），在案例和任务汇总里都能看到。
- **耗时**：单案例墙钟时间；任务平均耗时 = 总耗时 / 尝试次数。

报表文件：

| 文件 | 内容 |
|---|---|
| `report.md` | 人读报表：结论速览、任务汇总、复现锁定、逐案例结果、失败案例 |
| `report.json` | 机器可读：meta + summaries + cases |
| `sessions/` | 每条案例的 append-only JSONL（完整轨迹） |
| `workspaces/` | 每条案例的最终工作区 |

失败案例在 `report.md` 的“失败案例”段和逐案例表里都给出会话路径；不需要翻目录找。

案例目录名：

```text
004-prompt-injection-resistance-r1   # eval run：任务 id + 第 1 次重复
001-audit-report-k3-r1               # eval compaction：任务 id + 强制压缩 3 次 + 第 1 次重复
```

`r1` 是 repetition 序号，不是“第一轮”；`k3` 是强制压缩 3 次。`a.txt / b.txt / c.txt`
是 001 任务的输入文件，和桶分类 `A/B/C` 没有关系。

### 4.3 复现锁定

`report.json` 的 `meta` 在**开跑前**锁定：

- `git_ref`、`git_dirty`、工作树指纹（已跟踪 diff + 未跟踪文件内容哈希，排除本轮 run 目录）；
- `seed`；
- `python`、`codelotte_version`、`uv.lock` SHA-256；
- `model`、`reasoning_effort`、`context_window`；
- 每个任务的语义指纹与快照 commit SHA；
- 完整命令。

同一命令重跑得到新 run 目录；模型没有固定 temperature，数字会波动。看趋势用 `--repeat`。
想拿“干净的 git ref”：先提交，再重跑；未提交跑数也会被工作树指纹锁住，不是不能用。
对比两次跑数：并排看两个 `report.md` 的结论速览，或 diff `report.json`。

### 4.4 CI 冒烟

`.github/workflows/ci.yml` 的 `eval-smoke` job：

- 只在 **push** 时运行；
- 需要仓库 secret `DEEPSEEK_API_KEY`（Settings → Secrets and variables → Actions）；
- 有 secret：跑 `eval run --bucket B --task 004-prompt-injection-resistance --repeat 1`，
  把报表写进 job summary 并上传 `eval-smoke` artifact；
- 没 secret：checkout/同步依赖后跳过冒烟步骤（不会因为 fork/无密钥而失败）。

冒烟只验证“评测管线真的能跑”；模型偶尔答错不会让 CI 变红（任务失败不算运行错误），
但报表 artifact 会如实显示。要让它变红，可在 workflow 里加一步检查 `report.json` 的
`summaries[].pass_pow_k`。

### 4.5 对照组（`eval compare`）

同一条任务、同一次数，分别跑三种 harness：

| 组 | 是什么 | 看什么 |
|---|---|---|
| `codelotte` | 真实 loop + 四个工具 + 权限/压缩/防线 | 我们 harness 的完整能力 |
| `mini-swe-agent` | 开源教学级 agent（真实 2.4.6 包），只有 bash | 同样模型下另一套 scaffolding |
| `raw` | 裸单轮 API：一条 user 消息、无 tools | “模型自己”的下界 |

三组使用**同一个模型与同一任务集**；对照报告把它们按任务并排，单元格是
`通过标记 · 通过/尝试 · pass^N · 总成本 · 平均耗时`。各组明细仍在
`harnesses/<组名>/report.md`。

mini-swe-agent 不在项目依赖里（它带 litellm/datasets 等重依赖）。推荐装独立 venv：

```bash
# Windows
uv venv .mini-venv
uv pip install --python .mini-venv/Scripts/python.exe mini-swe-agent==2.4.6
uv run codelotte eval compare --mini-python .mini-venv/Scripts/python.exe --repeat 1 --no-sandbox

# macOS / Linux
uv venv .mini-venv
uv pip install --python .mini-venv/bin/python mini-swe-agent==2.4.6
uv run codelotte eval compare --mini-python .mini-venv/bin/python --repeat 1 --no-sandbox
```

- 不写 `--mini-python` 时，依次尝试：PATH 上的 `mini`（推同环境解释器）→ 当前解释器
  （能 `import minisweagent`）→ 报错并给安装命令。
- 只想跑两组：`--harness codelotte --harness raw`（`--harness` 可重复）。
- `--dry-run` 会校验任务、快照 ref 和 mini 是否可用，不建 run 目录、不调用模型。
- **成本口径**：三组都用本项目价目表按实际 usage 估算。mini 的真实 key 只留在
  codelotte 进程内存里的本地录制代理；被测 agent 的 bash 只看到假 key。
- **公平性限制**：任务里的“执行纪律”（必须用 read/write、不得用 bash）不在验收范围内，
  只看最终状态；mini 只有 bash，所以别把三组当成同一策略。耗时对比请让 codelotte
  也用 `--no-sandbox`（与 mini 的本地环境对齐）。

### 4.6 控制 agent 自检（`eval controls`）

三个“假 agent”检验评测器本身：

| 控制 agent | 行为 | 预期 |
|---|---|---|
| `oracle` | 直接落任务参考解（`[control.oracle.files]`）或从文件期望推导 | 100% 通过 |
| `no-op` | 什么都不做 | 0% 通过，且不应产生标记 |
| `cheating` | 写假成功内容 + 篡改所有 `unchanged` 保护文件 | 0% 通过，且全部被标记 |

```bash
uv run codelotte eval controls
uv run codelotte eval controls --dry-run    # 只校验任务/快照
```

- 不调用模型、不需要 API key、不需要 Docker；几秒钟跑完，可以放进任何 CI。
- `report.md` 顶部有“自检结论”表；任何一条不符，CLI 返回退出码 1，
  报告会写“先修评测器，再相信任何真实跑分”。
- `cheating` 的标记来自 `unchanged` 保护文件检查；为了让这条防线覆盖全部任务，
  首批任务已给只读输入（`a/b/c.txt`、`check.py`、`input/policy.txt`、
  `protected.txt`）加 `unchanged = true`。
- 新增任务时至少给 oracle 一个参考解，并至少留一个 `unchanged` 只读保护文件；
  `tests/test_eval_tasks.py` 会检查 shipped 任务两者都有。没有保护文件时，cheating
  仍会因内容不对记 0，但不会产生“篡改”标记。

### 4.7 已知局限

- 没有 LLM judge 与 κ 校准——票据 17。
- pass^k 是严格口径；不提供 pass@k（至少一次通过）的并列指标。
- 首批任务只有 5 条，B 桶 3 条；任务集扩大与 E1/E2 正式实验在票据 20。
- 任务的初始化脚本按平台 shell 语义执行；跨平台任务应优先用 Python 或 `python -c`。
- `eval compare` 的三组不是同一策略：codelotte 有四个工具与压缩/防线，mini 只有 bash，
  raw 没有工具；对照回答的是“最终状态 + 成本/耗时”，不是同策略 A/B。
- mini 的思考参数沿用它的默认请求；codelotte 用 `reasoning_effort` 配置。同模型，
  但请求参数不保证逐字段一致。

### 4.8 代码地图

| 文件 | 职责 |
|---|---|
| `src/codelotte/evals/tasks.py` | TOML 加载与校验（文件/快照/验收器/checkpoint/参考解） |
| `src/codelotte/evals/workspace.py` | 工作区准备、git 快照、初始化脚本、确定性验收、保护文件检查 |
| `src/codelotte/evals/execution.py` | 单任务执行核心（codelotte loop、预算、成本/时段、验收） |
| `src/codelotte/evals/harness_types.py` | harness 协议与 `HarnessExecution` |
| `src/codelotte/evals/harnesses.py` | 裸单轮 API + 三种控制 agent |
| `src/codelotte/evals/mini_baseline.py` | mini-swe-agent 外部进程适配 |
| `src/codelotte/evals/mini_runner.py` | 在 mini 解释器里跑的独立入口（绕开交互层） |
| `src/codelotte/evals/mini_proxy.py` | 本地录制代理（假 key、真实 usage） |
| `src/codelotte/evals/runner.py` | 通用 harness 编排（任务 × 重复、pass^k 数据） |
| `src/codelotte/evals/compare.py` | 多组对照、控制 agent 自检、并列报表 |
| `src/codelotte/evals/eval_report.py` | 单组报表（Markdown/JSON） |
| `src/codelotte/evals/regression.py` | 压缩回归（强制压缩 + checkpoint 探针） |
| `evals/tasks/*.toml` | 任务定义 |
| `evals/runs/<run-id>/` | 跑数证据 |

## 5. 专用测评 - 压缩回归 v0（`eval compaction`）

压缩回归是独立的专项实验：固定任务、强制压缩 k=0/1/3/5 次、每次压缩后用 checkpoint
问题集测“还记得吗”。完整操作、评分口径、v0 基线与已知局限见
[compaction.md](compaction.md)。

最短路径：

```bash
uv run codelotte eval compaction --dry-run
uv run codelotte eval compaction --k 0,1,3,5 --out evals/runs
```

## 6. 交接清单

接手的人按这个顺序看：

1. 本文件（通用测评：操作、任务格式、CI）；
2. [compaction.md](compaction.md)（专用测评 - 压缩回归 v0：机制、评分、基线、局限）；
3. 最近一次跑数的 `report.md`；
4. `src/codelotte/evals/`（按 tasks → workspace → execution → runner/regression → report 读）；
5. [record.md](record.md)（跑数目录、记录表与复现约定）。

跑之前先 `--dry-run`；动代码后跑 `uv run pytest tests/test_eval_*.py`。
