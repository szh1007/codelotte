# 压缩回归报表 v0

> 一轮跑数：12 条案例（3 条任务 × 4 个 k × 1 次重复）。数字与原始轨迹同目录，可用文末命令复现。

## 结论速览

| k | 尝试 | 完成率 | 有效案例 | 有效完成率 | 状态保留率（全部） | 状态保留率（有效） | 平均压缩次数 | 模型调用 | 成本 |
|---|---|---|---|---|---|---|---|---|---|
| k=0（对照组） | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | — | — | 0.0 | 21 | ¥0.011355 |
| k=1 | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 9/9 (100%) | 9/9 (100%) | 1.0 | 23 | ¥0.033721 |
| k=3 | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 27/27 (100%) | 27/27 (100%) | 3.0 | 29 | ¥0.081154 |
| k=5 | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 45/45 (100%) | 45/45 (100%) | 5.0 | 39 | ¥0.139264 |

读法：

- **完成率**：验收通过 / 尝试次数。任务失败是数据，不剔除。
- **有效案例**：运行无错误，且实际压缩次数恰好等于 k；k=0 是对照组（不压缩），天然有效。
- **状态保留率**：压缩后 checkpoint 问题的通过率（事实在整段回答中出现即算记得；只写错编号段的跨段命中记入 `misplaced`，不扣保留率）；无效案例也计入“全部”一列。
- 成本包含被测任务与 checkpoint 探针（探针不写回会话，但确实调用模型）。

## 复现锁定

| 项 | 值 |
|---|---|
| run id | `20261017T173510Z-037104e` |
| 开始 / 结束 | 2026-10-17T17:35:10.894895+00:00 → 2026-10-17T17:40:10.302508+00:00 |
| git ref | `037104e0d1a4116c559d6a6d6ef411c64b7bbe6d` |
| 工作树有改动 | 是（指纹 8a5597cda504ca119728a291c1f213f47c661db7248e700f250f7ae582d10f39） |
| 模型 / 思考档位 | `deepseek-flash` / `high` |
| 上下文窗口 | 1000000 |
| 压缩阈值 soft / hard | 0.60 / 0.85 |
| k 集合 / 重复次数 | 0, 1, 3, 5 / 1 |
| 随机种子 | 0 |
| Python / codelotte | 3.13.13 / 0.1.0 |
| uv.lock SHA-256 | `b64ada6fe8c5faea366310bae5cc70fe25a2b98ce6baf8676e26d72c0531caf7` |
| 命令 | `codelotte eval compaction --k 0,1,3,5 --out evals/runs` |
| 任务 001-audit-report（A 桶） | `7f90b058f342ebc8166c703b758f251f7e276701c60ab19238086a76638a4a99` |
| 任务 002-fix-off-by-one（A 桶） | `87ef144cc9dfa88993ba4e0826d047845060c9868052a8eb17336d86b16c86ae` |
| 任务 003-constrained-append（B 桶） | `a85ade57f1e2a8cabd61f12ec895cdfe3d323ccc20fba6fa66bdab665fdefd42` |

## 逐任务结果

| 任务 | k | 有效 | 压缩次数 | 完成 | 状态保留 | 验收 / 错误 | 会话 |
|---|---|---|---|---|---|---|---|
| 001-audit-report | 0 | ✅ | 0/0 | ✅ | — | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-001-audit-report-k0-r1--/20261017T173511Z_bedec6e2.jsonl` |
| 001-audit-report | 1 | ✅ | 1/1 | ✅ | 3/3 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-001-audit-report-k1-r1--/20261017T173517Z_9a08d143.jsonl` |
| 001-audit-report | 3 | ✅ | 3/3 | ✅ | 9/9 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-001-audit-report-k3-r1--/20261017T173535Z_0a3690b5.jsonl` |
| 001-audit-report | 5 | ✅ | 5/5 | ✅ | 15/15 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-001-audit-report-k5-r1--/20261017T173602Z_cc9fde5e.jsonl` |
| 002-fix-off-by-one | 0 | ✅ | 0/0 | ✅ | — | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-002-fix-off-by-one-k0-r1--/20261017T173638Z_5c9d71da.jsonl` |
| 002-fix-off-by-one | 1 | ✅ | 1/1 | ✅ | 3/3 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-002-fix-off-by-one-k1-r1--/20261017T173647Z_ece19d89.jsonl` |
| 002-fix-off-by-one | 3 | ✅ | 3/3 | ✅ | 9/9 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-002-fix-off-by-one-k3-r1--/20261017T173703Z_ec53f663.jsonl` |
| 002-fix-off-by-one | 5 | ✅ | 5/5 | ✅ | 15/15 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-002-fix-off-by-one-k5-r1--/20261017T173730Z_15291f4b.jsonl` |
| 003-constrained-append | 0 | ✅ | 0/0 | ✅ | — | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-003-constrained-append-k0-r1--/20261017T173821Z_97bd585f.jsonl` |
| 003-constrained-append | 1 | ✅ | 1/1 | ✅ | 3/3 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-003-constrained-append-k1-r1--/20261017T173830Z_9a63d55a.jsonl` |
| 003-constrained-append | 3 | ✅ | 3/3 | ✅ | 9/9 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-003-constrained-append-k3-r1--/20261017T173847Z_95998a03.jsonl` |
| 003-constrained-append | 5 | ✅ | 5/5 | ✅ | 15/15 (100%) | 验收通过 | `sessions/--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-003-constrained-append-k5-r1--/20261017T173918Z_ea626356.jsonl` |

## Checkpoint 明细

### 001-audit-report · k=1 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 统计 a.txt、b.txt、c.txt 中大小写敏感的 "TODO" 子串出现次数，按固定顺序写入 report.txt，每行 `<文件名>:<次数>`，不写其他内容。
  > 
  > 2. 已读取 a.txt（共 5 行），其中含 2 处 "TODO"，分别在 2、4 行；尚未写 report.txt，也未确认。
  > 
  > 3. 必须逐文件处理，一次只做一个动作；依次读取 a.txt、b.txt、c.txt；用 write 一次写入 report.txt，最后读取确认；不得使用 bash；"TODO" 大小写敏感，按子串计数；顺序固定为 a 在 b 前、b 在 c 前；report.txt 只含三行 `<文件名>:<次数>`，不写其他内容；只改指定文件，不动工作区外文件。


### 001-audit-report · k=3 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 任务目标：统计 a.txt、b.txt、c.txt 各自包含的 "TODO" 次数，并按指定格式写入 report.txt。
  > 
  > 2. 已完成步骤：已读取 a.txt，统计出其中 "TODO" 出现 2 次；b.txt、c.txt 尚未读取，report.txt 尚未生成或确认。
  > 
  > 3. 必须遵守的约束：匹配 "TODO" 时大小写敏感，并按子串计数；逐文件处理，一次只执行一个动作；顺序为读取 a.txt、b.txt、c.txt；之后用 write 一次性写入 report.txt，其每行格式为 `<文件名>:<次数>`，顺序固定为 a.txt、b.txt、c.txt，不写其他内容；最后读取 report.txt 确认；不要使用 bash。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要（跨段：不要）

  > 1. 任务目标：统计 a.txt、b.txt、c.txt 中大小写敏感的 "TODO" 子串出现次数，并按 a.txt、b.txt、c.txt 的固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`，不写其他内容。
  > 
  > 2. 已完成步骤：已读取 a.txt，统计 "TODO" 出现 2 次；已读取 b.txt，统计 "TODO" 出现 1 次。尚未读取 c.txt，尚未生成和确认 report.txt。
  > 
  > 3. 必须遵守的约束：逐文件处理且一次只做一个动作；先读 a.txt、b.txt、c.txt，再一次性写入 report.txt，最后读取确认；不使用 bash；只修改指定内容，不碰工作区外文件；沙箱网络默认不可用；工具失败时换方法，无法推进时如实说明卡点。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 统计 a.txt、b.txt、c.txt 中 "TODO" 的出现次数（大小写敏感、按子串计数），并把结果按 a.txt、b.txt、c.txt 的固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`，不写其他内容。
  > 
  > 2. 已读取 a.txt（TODO 2 次）、b.txt（TODO 1 次）、c.txt（内容为 done、finished，TODO 0 次）；尚未写入 report.txt，也尚未读取确认。
  > 
  > 3. 约束：大小写敏感、按子串计数；report.txt 顺序固定且只含三行结果；逐文件处理、一次只做一个动作；不使用 bash；只改指定文件、不碰工作区外文件；网络默认不可用；工具失败要换方法、不重复同一调用；无法推进时如实说明卡点。


### 001-audit-report · k=5 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 任务目标：统计 a.txt、b.txt、c.txt 中 "TODO" 的出现次数（大小写敏感、按子串计数），并按固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`。
  > 
  > 2. 已完成步骤：已读取 a.txt（共 5 行，其中第 2、4 行各含 1 个 "TODO"，即 a.txt 计 2 次）。尚未读取 b.txt、c.txt，未统计其次数，未写 report.txt，未做最终确认。
  > 
  > 3. 必须遵守的约束：逐文件处理、一次只做一个动作；读取顺序为 a.txt→b.txt→c.txt；之后用 write 一次性写入 report.txt，再 read report.txt 确认；不使用 bash；"TODO" 大小写敏感按子串计数；report.txt 只含三行 `<文件名>:<次数>`，顺序固定为 a.txt、b.txt、c.txt，不写其他内容；只修改指定文件，不碰工作区外文件；网络默认不可用；权限被拒或工具失败时换做法、不重复同一调用，无法推进时如实说明卡点。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要（跨段：不要）

  > 1. 统计 a.txt、b.txt、c.txt 中大小写敏感的子串 "TODO" 出现次数，并写入 report.txt；每行格式为 `<文件名>:<次数>`，顺序固定为 a.txt、b.txt、c.txt，不写其他内容。
  > 
  > 2. 已读取 a.txt（5 行，2 处 "TODO"，位于第 2、4 行）；已读取 b.txt（3 行，1 处 "TODO"，位于第 2 行）。尚未读取 c.txt，尚未写 report.txt，也尚未读 report.txt 确认。
  > 
  > 3. 必须遵守以下约束：逐文件处理，一次只执行一个操作；按 a.txt、b.txt、c.txt 的顺序读取；用 write 一次性写入 report.txt；最后读取 report.txt 确认；不使用 bash；"TODO" 大小写敏感，按子串计数；固定格式与顺序；只修改指定文件；沙箱内无网络；工具失败时换一种做法；无法推进时如实说明并交还用户。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 任务目标：统计 a.txt、b.txt、c.txt 中大小写敏感的 "TODO" 子串出现次数，并按固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`，不写其他内容。
  > 
  > 2. 已完成步骤：
  > - 已读取 a.txt，统计到 2 处 "TODO"。
  > - 已读取 b.txt，统计到 1 处 "TODO"。
  > - 已读取 c.txt，内容为两行（done、finished），其中 "TODO" 出现 0 次。
  > - 尚未写入和复核 report.txt。
  > 
  > 3. 必须遵守的约束：
  > - 逐文件处理，一次只做一个动作；依次读取 a.txt、b.txt、c.txt，再一次性写入 report.txt，最后读取确认。
  > - "TODO" 大小写敏感，按子串计数。
  > - report.txt 顺序固定为 a.txt、b.txt、c.txt，格式为 `<文件名>:<次数>`，不写其他内容。
  > - 不使用 bash；不修改工作区之外的文件。
  > - 沙箱内网络默认不可用；权限被拒或工具失败时换一种做法，不重复同一调用。
  > - 无法推进时如实说明卡点并交还用户。

- 压缩 #4（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 统计 a.txt、b.txt、c.txt 中 "TODO" 的出现次数（大小写敏感、按子串计数），并按 a.txt、b.txt、c.txt 的固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`，不写其他内容。
  > 
  > 2. 已读取三个文件并统计：
  > - 读取 a.txt，含 2 处 "TODO"；
  > - 读取 b.txt，含 1 处 "TODO"；
  > - 读取 c.txt，含 0 处 "TODO"；
  > - 已用 write 一次性写入 report.txt，内容为 a.txt:2、b.txt:1、c.txt:0（当次写入成功）。
  > 
  > 3. 必须遵守的约束：
  > - 逐文件处理，一次只做一个动作；顺序先 a.txt、再 b.txt、再 c.txt，最后写入并读取确认；
  > - 不使用 bash，不碰工作区之外的文件，只修改用户指定的内容；
  > - "TODO" 大小写敏感、按子串计数；report.txt 仅含三行 `<文件名>:<次数>`，顺序固定；
  > - 沙箱内网络默认不可用；权限被拒或工具失败时换方法，不重复同一调用；
  > - 无法推进时如实说明卡点并交还用户。

- 压缩 #5（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 report.txt, TODO, 计数
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 read, a.txt
  - ✅ 有哪些必须遵守的约束？ — 命中 report.txt, 顺序, 不要

  > 1. 统计 a.txt、b.txt、c.txt 中大小写敏感的 "TODO" 子串出现次数，并按固定顺序写入 report.txt，每行格式为 `<文件名>:<次数>`，不包含其他内容。
  > 
  > 2. 已读取 a.txt（2 次）、b.txt（1 次）、c.txt（0 次）；已将结果写入 report.txt，并读取确认内容为 a.txt:2、b.txt:1、c.txt:0，格式与顺序正确。
  > 
  > 3. 约束：一次只做一个动作，按 a.txt→b.txt→c.txt 顺序先读后写；不用 bash；"TODO" 大小写敏感、按子串计数；report.txt 仅含三行固定格式；只改指定内容，不碰工作区外文件；网络不可用；工具失败换方法、不重复同一调用；无法推进时如实说明并交还用户。


### 002-fix-off-by-one · k=1 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `calc.py` 中的 off-by-one bug，使 `python check.py` 通过；修复后，将关键代码行原样写入 `notes.txt`，并且 `notes.txt` 中只写这一行，不含行号。
  > 
  > 2. 已完成的步骤：
  > - 运行了 `python check.py`，确认测试失败，抛出 AssertionError；失败位置是 `sum_first_n([1, 2, 3, 4], 2) == 3`。
  > - 读取了 `calc.py`，定位到疑似问题在第 3 行 `for i in range(n + 1):`，因为该循环多取了一个元素。
  > - 尚未修改 `calc.py`，尚未重新验证测试，尚未写入 `notes.txt`。
  > 
  > 3. 必须遵守的约束：
  > - 按顺序执行：先运行测试查看失败，再读取代码，然后最小编辑，再验证通过，最后写入 `notes.txt` 并回读确认。
  > - 只修改必要的那一行，不修改 `check.py`，也不引入无关改动。
  > - `notes.txt` 只写修复后的关键代码行，不含行号。
  > - 只操作工作区内的指定文件；工具失败时换一种做法，不重复同一调用。
  > - 无法推进时，如实说明卡点并交还用户。


### 002-fix-off-by-one · k=3 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `calc.py` 中导致 off-by-one 的 bug，使 `python check.py` 通过，然后把修复后的关键代码行原样写入 `notes.txt`；`notes.txt` 只写这一行，不含行号。不得修改 `check.py`。
  > 
  > 2. 已完成：
  > - 运行 `python check.py`，退出码为 1，报错为 `check.py` 第 3 行的 `AssertionError`：`assert sum_first_n([1, 2, 3, 4], 2) == 3`。
  > - 读取 `calc.py`（共 5 行），发现第 3 行 `for i in range(n + 1):` 是 off-by-one 问题所在。
  > - 尚未修改 `calc.py`；尚未写入 `notes.txt`；尚未复跑测试确认通过。
  > 
  > 3. 必须遵守的约束：
  > - 只修改 `calc.py` 中必要的那一行，不动工作区之外的文件，不修改 `check.py`。
  > - 按顺序执行：先运行测试观察失败，再读取 `calc.py`，然后用 edit 只改必要的那一行，再运行 `python check.py` 确认通过，最后 write 并在 read 确认 `notes.txt`。
  > - `notes.txt` 只写修复后的关键代码行原样内容，不含行号。
  > - 沙箱内网络默认不可用；如果权限被拒或工具失败，就换一种做法，不重复同一调用；无法推进时如实说明卡点并交还用户。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `/workspace/calc.py` 中的 off-by-one bug，使 `python check.py` 通过，并把修复后的关键代码行原样写入 `notes.txt`（只写那一行，不含行号）；不得修改 `check.py`。
  > 
  > 2. 已完成步骤：
  > - 运行 `python check.py`，复现 `AssertionError`（`check.py` 第 3 行）。
  > - 读取 `/workspace/calc.py`，定位到第 3 行 `for i in range(n + 1):`。
  > - 已用 edit 将 `/workspace/calc.py` 第 3 行改为 `for i in range(n):`。
  > - 尚未重新运行验证，`notes.txt` 尚未写入。
  > 
  > 3. 必须遵守的约束：
  > - 先复现失败、再读源码、改必要的一行、跑测试验证、最后写 `notes.txt` 并读取确认。
  > - 不修改 `/workspace/check.py`。
  > - `notes.txt` 只写修复后的那一行，不含行号。
  > - 只修改用户指定的内容，不碰工作区之外的文件。
  > - 沙箱内网络默认不可用；工具失败时换一种做法，不重复同一调用；无法推进时如实说明卡点并交还用户。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `/workspace/calc.py` 里的 off-by-one bug，让 `python check.py` 通过；然后把修复后的关键代码行原样写入 `notes.txt`（只写那一行，不带行号）；并且不修改 `check.py`。
  > 
  > 2. 已完成步骤：
  > - 用 bash 运行 `python check.py` 复现失败（退出码 1，`AssertionError`：`sum_first_n([1, 2, 3, 4], 2) == 3`）。
  > - 读取 `/workspace/calc.py`（5 行），定位问题在第 3 行 `for i in range(n + 1):` 多取一个元素。
  > - 用 edit 把 `/workspace/calc.py` 第 3 行改为 `    for i in range(n):`。
  > - 重新运行 `python check.py`，输出 `ok`，退出码 0，验证通过。
  > - 未完成：`notes.txt` 尚未写入、也未读取确认（应只写 `    for i in range(n):`）。
  > 
  > 3. 必须遵守的约束：
  > - 只修改用户指定的内容，不碰工作区之外的文件，不修改 `/workspace/check.py`。
  > - `notes.txt` 只写修复后的那一行代码原样内容，不含行号。
  > - 操作顺序：先复现失败 → 读源码 → 只改必要的一行 → 跑测试确认 → 写 `notes.txt` 并读回确认。
  > - 不编造对话中没有的事实，保留具体路径、命令与错误信息。
  > - 工具失败或被拒绝时换一种做法，不重复同一调用；无法推进时如实说明卡点并交还用户。


### 002-fix-off-by-one · k=5 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 修复 `calc.py` 中的 off-by-one bug，使 `python check.py` 通过，并把修复后的关键代码行原样写入 `notes.txt`（不带行号）。
  > 
  > 2. 已运行 `python check.py`，得到的失败信息是：`assert sum_first_n([1, 2, 3, 4], 2) == 3` 触发 `AssertionError`。尚未读取或修改 `calc.py`，尚未写入 `notes.txt`，也尚未验证修复。
  > 
  > 3. 必须遵守的约束：不要修改 `check.py`；只改 `calc.py` 中必要的那一行；按顺序执行（先运行测试，再读取 `calc.py`，然后用 edit 修复，再运行测试确认，最后写入并读取 `notes.txt`）；`notes.txt` 只写修复后的关键代码行原样、不含行号；不碰工作区外的文件；网络不可用；工具被拒或失败时换方法，不重复同一调用；无法推进时如实说明卡点。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `calc.py` 中的 off-by-one bug，使 `python check.py` 通过；再把修复后的关键代码行原样（不含行号）写入 `notes.txt`。
  > 
  > 2. 已完成步骤：运行 `python check.py`，确认失败（`check.py` 第 3 行断言 `sum_first_n([1, 2, 3, 4], 2) == 3`，抛 `AssertionError`，退出码 1）；已读取 `calc.py`，发现第 3 行 `for i in range(n + 1):` 为疑似 bug。尚未修改 `calc.py`，未复跑测试，未创建 `notes.txt`。
  > 
  > 3. 必须遵守的约束：按顺序执行（先跑测试 → 读 `calc.py` → 用 edit 只改必要的一行 → 复跑测试 → 写 `notes.txt` 并读回确认）；不得修改 `check.py`；`notes.txt` 中只写该关键代码行原样、不含行号；只改用户指定内容，不碰工作区外文件；网络默认不可用；工具失败时换做法、不重复同一调用；无法推进时如实说明卡点。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `calc.py` 中的 off-by-one bug，使 `python check.py` 通过；并把修复后的关键代码行原样写入 `notes.txt`，只写那一行、不含行号。
  > 
  > 2. 已完成步骤：
  > - 已运行 `python check.py`，确认失败用例是 `sum_first_n([1, 2, 3, 4], 2) == 3`，报 `AssertionError`（涉及 `check.py`）。
  > - 已读取 `calc.py`，定位问题在第 3 行 `for i in range(n + 1):`。
  > - 已用 edit 将 `calc.py` 第 3 行改为 `for i in range(n):`。
  > - 尚未复跑测试，尚未创建/写入 `notes.txt`。
  > 
  > 3. 必须遵守的约束：
  > - 不得修改 `check.py`。
  > - 只改必要的那一行，不碰工作区之外的文件。
  > - 修改后须复跑 `python check.py` 确认通过。
  > - `notes.txt` 只写修复后的关键代码行原样，不含行号，并读回确认。
  > - 工具失败或权限被拒时换一种做法，不要重复同一调用；无法推进时如实说明卡点。

- 压缩 #4（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 任务目标：修复 `calc.py` 的 off-by-one bug，使 `python check.py` 通过；再把修复后的关键代码行原样写入 `notes.txt`，只写那一行，不含行号。
  > 
  > 2. 已完成步骤：
  > - 首次运行 `python check.py`，确认失败：`sum_first_n([1, 2, 3, 4], 2) == 3` 触发 `AssertionError`。
  > - 已读取 `calc.py`，定位第 3 行 `for i in range(n + 1):` 为 off-by-one 来源。
  > - 已用 edit 将 `calc.py` 第 3 行改为 `for i in range(n):`。
  > - 再次运行 `python check.py`，已通过（输出 `ok`，退出码 0）。
  > - `notes.txt` 尚未写入。
  > 
  > 3. 必须遵守的约束：
  > - 不要修改 `check.py`。
  > - `notes.txt` 只写修复后的关键代码行原样，不含行号。
  > - 只修改用户指定的内容，不碰工作区之外的文件。
  > - 沙箱内网络默认不可用。
  > - 权限被拒或工具失败时换一种做法，不重复同一调用；无法推进时如实说明卡点并交还用户。

- 压缩 #5（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 check.py, 修复, off-by-one
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 check.py, 失败
  - ✅ 有哪些必须遵守的约束？ — 命中 check.py, 不要

  > 1. 修复 `calc.py` 中的 off-by-one bug，使 `python check.py` 通过；并把修复后的关键代码行原样写入 `notes.txt`（只写那一行，不含行号）。
  > 
  > 2. 已完成：
  > - 运行 `python check.py` 看到失败：`sum_first_n([1, 2, 3, 4], 2) == 3` 触发 `AssertionError`。
  > - 读取 `calc.py`，定位问题在第 3 行 `for i in range(n + 1):`。
  > - 用 edit 将 `calc.py` 第 3 行改为 `for i in range(n):`。
  > - 重新运行 `python check.py`，输出 `ok`，`EXIT: 0`，测试通过。
  > - 重新读取 `calc.py` 确认修改已生效。
  > 
  > 3. 必须遵守的约束：
  > - 严格按顺序：先跑测试、再读 `calc.py`、再用 edit 只改必要一行、再跑测试确认、最后写 `notes.txt` 并读回确认。
  > - 不要修改 `check.py`。
  > - `notes.txt` 中只写修复后的关键代码行原样，不含行号。
  > - 只修改用户指定内容，不碰工作区之外的文件。
  > - 沙箱内网络默认不可用。
  > - 权限被拒或工具失败时换一种做法，不要重复同一调用；无法推进时如实说明卡点并交还用户。


### 003-constrained-append · k=1 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 rules.txt 的规则生成 output.txt，即把 data.txt 的内容按原行序逐行转换为 `<序号>: <原行内容>` 格式并写入 output.txt。
  > 
  > 2. 已完成步骤：已用 read 读取 rules.txt（共 4 行，得到 4 条规则）。其余未完成：尚未 read data.txt，尚未 write output.txt 第一行，尚未逐行 edit 追加，尚未 read output.txt 确认。
  > 
  > 3. 必须遵守的约束：
  > - 只修改 output.txt，不得修改 data.txt，不碰工作区之外的文件。
  > - output.txt 必须保留 data.txt 的原始行序；每行格式 `<序号>: <原行内容>`，序号从 1 开始。
  > - 不得使用 bash，只能用 read/write/edit。
  > - 操作纪律：一次只做一个动作不合并；顺序为 read rules.txt → read data.txt → write 第一行 → 每次 edit 只追加一行（不重写整个文件）→ 最后 read output.txt 确认。
  > - 权限被拒或工具失败时换一种做法，不重复同一调用；无法推进时如实说明卡点。


### 003-constrained-append · k=3 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号（跨段：序号）
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 严格按 `rules.txt` 的规则处理 `data.txt`，生成 `output.txt`。
  > 
  > 2. 已完成：已读取 `rules.txt`（4 条规则）。`data.txt` 尚未读取，`output.txt` 尚未写入或编辑。
  > 
  > 3. 必须遵守：
  > - 只修改 `output.txt`，不得修改 `data.txt`。
  > - `output.txt` 保留 `data.txt` 原始行序。
  > - 每行格式为 `<序号>: <原行内容>`，序号从 1 开始。
  > - 不得用 bash，只用 read/write/edit。
  > - 一次只做一个动作，不合并；先用 `write` 写第一行，再用 `edit` 逐行追加，最后 `read` 确认。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 `rules.txt` 生成 `output.txt`，保留 `data.txt` 原始行序，每行格式为 `<序号>: <原行内容>`，序号从 1 开始。
  > 
  > 2. 已完成步骤：
  > - 已读取 `rules.txt`，确认全部 4 条规则。
  > - 已读取 `data.txt`，获得 4 行内容：red、green、blue、yellow。
  > - 尚未修改 `output.txt`。
  > 
  > 3. 必须遵守的约束：
  > - 只能修改 `output.txt`，不得修改 `data.txt`。
  > - 必须保留 `data.txt` 的原始行序。
  > - 每行格式为 `<序号>: <原行内容>`，序号从 1 开始。
  > - 不得使用 bash，只能使用 read/write/edit 工具。
  > - 一次只做一个动作；先写第一行，再用 edit 逐行追加，最后 read 确认。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 `rules.txt` 生成 `output.txt`，保留 `data.txt` 原始行序，每行写成 `<序号>: <原行内容>`，序号从 1 开始。
  > 
  > 2. 已完成步骤：已 `read rules.txt`（4 条规则）；已 `read data.txt`（4 行：red、green、blue、yellow）；已用 `write` 将第一行 `1: red` 写入 `output.txt`。
  > 
  > 3. 必须遵守的约束：只改 `output.txt`，不改 `data.txt`；保持原始行序与指定格式；禁用 bash，只用 read/write/edit；一次只做一个动作、不合并；先用 `write` 写第一行，再用 `edit` 每次只追加一行且不重写整个文件；最后 `read output.txt` 确认；不碰工作区外文件；失败时换做法、不重复同一调用，无法推进时如实说明并交还用户。


### 003-constrained-append · k=5 · rep=1

- 压缩 #1（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 目标：严格按 rules.txt 的规则生成 output.txt，也就是给 data.txt 的每一行加上“序号: ”前缀，并保持原始行序。
  > 
  > 2. 已完成：
  > - 已 read rules.txt，其中包含 4 条规则：只能改 output.txt；保留 data.txt 原始行序；格式为 `<序号>: <原行内容>`，序号从 1 开始；禁用 bash，只能用 read/write/edit。
  > - 尚未 read data.txt，尚未 write 或 edit output.txt，尚未确认结果。
  > 
  > 3. 约束：
  > - 只能修改 output.txt，不得修改 data.txt。
  > - output.txt 必须保留 data.txt 的原始行序。
  > - 每行格式为 `<序号>: <原行内容>`，序号从 1 开始。
  > - 不得使用 bash，只能使用 read/write/edit。
  > - 一次只做一个动作，不要合并；先 read rules.txt，再 read data.txt，然后用 write 写入第一行，再用 edit 逐行追加其余各行（每次只追加一行，不要重写整个文件），最后 read output.txt 确认。

- 压缩 #2（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 rules.txt 的规则，把 data.txt 的内容逐行转成 `<序号>: <原行内容>` 格式写入 output.txt，最后读取 output.txt 确认。
  > 
  > 2. 已完成步骤：
  > - 已 read `rules.txt`（4 行规则）。
  > - 已 read `data.txt`（4 行：red / green / blue / yellow）。
  > - `output.txt` 尚未创建或写入。
  > 
  > 3. 必须遵守的约束：
  > - 只能修改 `output.txt`，不得修改 `data.txt`，并保留其原始行序。
  > - 每行格式为 `<序号>: <原行内容>`，序号从 1 开始。
  > - 不得使用 bash，只能用 read/write/edit。
  > - 先用 write 写入第一行，再用 edit 每次只追加一行，追加前不要重写整个文件；最后 read `output.txt` 确认。
  > - 一次只做一个动作，不要合并；不碰工作区之外的文件；工具失败时换一种做法，无法推进时如实说明卡点。

- 压缩 #3（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 rules.txt 的规则，在 output.txt 中生成每行格式为 `<序号>: <原行内容>` 的内容，并保留 data.txt 的原始行序。
  > 
  > 2. 已经完成的步骤：已 read 读取 rules.txt（已知全部 4 条规则）；已 read 读取 data.txt（内容为 red、green、blue、yellow，共 4 行）；output.txt 尚未创建或写入。
  > 
  > 3. 必须遵守的约束：只能修改 output.txt，不得修改 data.txt；保留 data.txt 的原始行序；序号从 1 开始；不得使用 bash，只能使用 read、write、edit 工具；一次只做一个动作，不要合并；先用 write 写入第一行，再用 edit 逐行追加其余各行，且每次 edit 只追加一行；追加前不要重写整个文件；最后 read 读取 output.txt 确认。

- 压缩 #4（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号（跨段：序号）
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 rules.txt 规则生成 output.txt——先 read rules.txt，再 read data.txt；用 write 写入第一行；用 edit 逐行追加其余行（每次只追加一行）；最后 read output.txt 确认。
  > 
  > 2. 已完成步骤：
  > - 已 read `rules.txt`，确认 4 条规则。
  > - 已 read `data.txt`，内容为 1 red、2 green、3 blue、4 yellow。
  > - 已用 write 将第一行 `1: red` 写入 `output.txt`（7 字符，新建文件）。
  > 
  > 3. 必须遵守的约束：只修改 `output.txt`，不得修改 `data.txt`；保留 `data.txt` 原始行序；每行格式为 `<序号>: <原行内容>`，序号从 1 开始；禁止 bash，仅用 read/write/edit；一次只做一个动作，不合并；每次 edit 只追加一行，追加前不重写整个文件；最后 read `output.txt` 确认；不碰工作区外文件；权限被拒或工具失败时换做法，无法推进则如实说明卡点。

- 压缩 #5（结构化）：3/3 通过
  - ✅ 任务目标是什么？ — 命中 output.txt, data.txt, 序号
  - ✅ 已经完成哪些步骤？（请带上涉及的文件名） — 命中 rules.txt, read
  - ✅ 有哪些必须遵守的约束？ — 命中 data.txt, 不得, bash

  > 1. 任务目标：严格按 rules.txt 的规则处理 data.txt，生成 output.txt；每行格式为 `<序号>: <原行内容>`，并且保留原行序。
  > 
  > 2. 已完成步骤：
  >    - read rules.txt（4 条规则）
  >    - read data.txt（red、green、blue、yellow 共 4 行）
  >    - write 向 output.txt 写入第一行 `1: red`
  >    - edit 向 output.txt 追加第二行 `2: green`
  > 
  > 3. 必须遵守的约束：只修改 output.txt，不改 data.txt；保留 data.txt 原始行序；每行格式为 `<序号>: <原行内容>`，序号从 1 开始；不得使用 bash，只能用 read/write/edit；一次只做一个动作，不要合并；每次 edit 只追加一行，追加前不要重写整个文件；最后 read output.txt 确认；不碰工作区之外的文件。


## 人工标注

- 标注表：`annotations.csv`（问题、自动判定、完整答案）。
- 规则：在 `human_pass` 列填 `1`（通过）/ `0`（不通过）/ 留空（未标注）。
- 优先复核 `auto_pass=0`、`misplaced` 非空与 `structured=False` 的行；确定性评分是主口径，人工分在 CSV 里单列。
- v0 基线的人工分由作者在跑数后填写；未填写不影响确定性报表。

## 方法与口径

- **强制压缩**：注入 `CompactionPolicy`，在每次请求前若已落盘的 compaction 少于 k，就按硬触发压到最小保留集；k 次压缩需要至少 k 个 turn，达不到的案例标为无效。
- **checkpoint**：每次压缩后用压缩后的上下文追加一次无工具提问，答案只用于评分，不写回会话，不污染被测轨迹。
- **确定性评分**：每个问题预定义若干事实组，每组给可接受的替代表述；事实在整段回答中出现即算保留；只出现在别的编号段时记 `misplaced`，不扣保留率。编号段解析失败时整段兜底并标记。
- **局限**：关键词比对是代理指标，不等于语义等价；k=0 之外没有消融实验；v0 每个点只重复一次，随机性只能靠重复次数扩大。

## 复现

```bash
codelotte eval compaction --k 0,1,3,5 --out evals/runs
```

原始轨迹：`sessions/`；最终工作区：`workspaces/`；逐条 checkpoint：`checkpoints.jsonl`；机器可读报表：`report.json`。
