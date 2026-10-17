# 任务定义（`*.toml`）

> 每个 `.toml` 是一条考试题。改完先跑
> `uv run codelotte eval compaction --dry-run` 校验，再用 `--k 0 --task <id>` 试跑。
> 操作流程见 [evals/README.md](../README.md)。

## 最小模板

把下面内容复制成 `evals/tasks/004-your-task.toml`，改字段即可：

```toml
id = "004-your-task"          # 唯一；建议 NNN-slug
bucket = "A"                  # A 真实自用 / B 对抗约束 / C 公开子集
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

[verifier]
# 二选一或都用：在工作区跑一段 Python（退出码 0 = 通过）
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

三条任务的实际例子：`001-audit-report.toml`（文件计数）、`002-fix-off-by-one.toml`
（修 bug + 复跑）、`003-constrained-append.toml`（多约束 + 长操作链）。

## 字段速查

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一；用于 `--task`、目录名、报表 |
| `bucket` | 是 | `A` 真实自用 / `B` 对抗构造 / `C` 公开子集 |
| `instruction` | 是 | 发给模型的题面；决定它做多少步 |
| `setup.files` | 是 | `路径 = "内容"`；路径必须是工作区内相对路径 |
| `verifier` | 是 | 必须至少有一个 `files` 期望或 `python` |
| `[[verifier.files]]` | 否 | `path` + `equals`/`contains`/`unchanged` 三选一 |
| `verifier.python` | 否 | 在工作区执行 `python -c`，退出码 0 即通过 |
| `[[checkpoints]]` | 是 | 至少一个；每个含 `question` + `facts` |
| `checkpoint.facts` | 是 | 数组的数组：每个内层数组是一组替代表述 |
| `timeout_seconds` | 否 | 默认 300；单案例墙钟超时 |
| `max_model_calls` | 否 | 默认 40；超过后中止并记错误（软上限） |

## 验收器（verifier）

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
unchanged = true                  # 必须与 setup 内容一字不差
```

Python 验收器在工作区里跑，可以直接 import 工作区文件：

```toml
[verifier]
python = """
from calc import sum_first_n
assert sum_first_n([1, 2, 3, 4], 2) == 3
print("ok")
"""
```

验收器必须**确定性**：不看当前时间、不联网、不依赖随机数。

## Checkpoint 事实怎么写

- 每个问题给 2–4 个**事实组**；每组 1–5 个**替代表述**。
- 所有事实组都命中，这个问题才算通过（组内任一命中即可）。
- 事实按**整段回答**匹配：模型把“序号”写到约束段而不是目标段，仍算记得，但会记 `misplaced`。
- 用具体 token（`report.txt`、`TODO`、`序号`、`bash`），不要用“文件”“内容”“正确”这种到处都有的词。
- 不要把同义词写成大杂烩：词典越宽，指标越像“有没有提到这几个词”，越不像“还记不记得任务”。

例：目标题要求“产出 output.txt、来自 data.txt、带序号”，但“序号”常被模型写进约束段；
可以只把 `output.txt` / `data.txt` 放目标题，把 `序号` 放约束题，避免误判。

## 设计任务时先想清楚

1. **k 次压缩需要至少 k 个 turn**。一个 turn = 一次 assistant 回复 + 它声明的工具链。
   想稳定支撑 k=5，题面至少要有 5 个必须依次执行的工具动作。
2. **写“一次只做一个动作”**，否则模型可能一次 read 三个文件 / 一次 write 全部内容，
   压缩次数不足，案例会被标为无效。
3. **先 k=0 试跑**：不压缩都完不成，说明题目/验收器有问题，不要归因给压缩。
4. **先 k=5 单跑**：确认能压到 5/5，再跑全量。
5. **setup 要能让模型自己找到答案**：不要依赖工作区外的文件、网络或未说明的约定。

## 校验与试跑

```bash
# 只校验，不花钱
uv run codelotte eval compaction --dry-run

# 单条任务、不压缩（题目本身可解吗？）
uv run codelotte eval compaction --k 0 --task 004-your-task --out evals/runs

# 单条任务、压 5 次（turn 够吗？）
uv run codelotte eval compaction --k 5 --task 004-your-task --out evals/runs

# 全量
uv run codelotte eval compaction --k 0,1,3,5 --out evals/runs
```

## 常见校验错误

| 报错 | 修法 |
|---|---|
| `缺少字段 …` | 补齐 `id/bucket/instruction/setup/verifier/checkpoints` |
| `必须是工作区内的相对路径` | 去掉绝对路径、`..`、`C:foo` 盘符相对路径 |
| `verifier：至少给 files 期望或 python 检查` | 加验收器 |
| `重复的任务 id` | 两个 TOML 用了同一个 `id` |
| `每个事实组必须是非空数组` | `facts = [[...]]`，不要写成扁平字符串数组 |
| `bucket 只能是 A/B/C` | 改 `bucket` |
