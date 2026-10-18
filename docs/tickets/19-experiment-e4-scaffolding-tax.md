# 19: 实验 E4：scaffolding tax 对照

**What to build:** 正式跑一次三组对照实验（codelotte / mini-swe-agent / 裸 API），量化两个问题：①"工具循环本身"值多少（vs 裸 API）；②"我们的 harness 相对参照 harness 的增量"值多少（vs mini-swe-agent）。按实验报告标准交付：任务集说明 / 基线 / 干预 / 指标（成功率、成本、时长、失败分布）/ 轨迹样本 / 复现脚本，跑数记录实际计费时段。

🗣 大白话：回答面试官必问的"成绩里多少是模型的功劳、多少是你系统的功劳"——用三组同题对照的数据说话。这是证明"我的 harness 有工程价值"的最硬证据。

**Blocked by:** 16（对照组 + 控制 agent 自检）

**Status:** done（2026-10-18；任务集扩到 9 条，三组 repeat 2 完整跑数，实验报告与 README 数据表已更新）

- [x] 三组同任务集完整跑数（含计费时段记录与原始轨迹）
- [x] 实验报告齐备：任务集 / 基线 / 干预 / 指标 / 轨迹 / 复现脚本
- [x] 结论（含不确定性说明）整理为 README 数据表素材

**实现记录**：

- **任务集扩充**（用户要求“先写更复杂/更有质量的 tasks 和 judge-tasks”）：
  - `006-multi-bug-pipeline`：3 个 bug 分布在 3 个模块，必须跑 `check.py`、读多文件、
    写 `fixes.md`；正式 run 每条 8 次调用，verifier 还检查三条修复行确实写进 `fixes.md`。
  - `007-refactor-tokenizer`：按 `spec.md` 重写 tokenizer，无可见测试；6–10 次调用。
  - `008-settlement-policy`：21 行 CSV + 8 条结算规则，产出两个精确格式文件；5–9 次调用。
  - `009-buffer-edge-cases`：可见测试只测 happy path，规格暗含空队列边界与 `clear()`；
    6–8 次调用。B 桶。
  - 原有 5 条保留；9 条任务均通过 oracle/no-op/cheating 自检。
  - 新增 judge 任务 `101-concurrency-review`（并发 lost-update review）与
    `102-api-design-tradeoffs`（批量支付 API 取舍）；各 20 条 `author-draft` 样本，
    Cohen's κ=1.000，校准成本 ¥0.071073 / ¥0.083567。真实 judge 跑数 3/3 通过，
    overall 均 1.00，报表标 ⚠ 草稿。
- **E4 正式跑数**：`eval run --repeat 3`（9 任务，27/27，pass^3 9/9，188 调用，
  ¥0.205832，349.0s，Docker）；`eval compare --repeat 2`（codelotte 18/18、mini 18/18、
  raw 0/18）；`eval controls`（oracle 9/9、no-op 0/9、cheating 0/9 且 9/9 标记）。
- **对照结论**：两个有工具的 harness 成功率打平（18/18 vs 18/18，pass^2 9/9 vs 9/9）。
  codelotte 相对 mini：成本 **+15.4%**（¥0.128218 vs ¥0.111146），调用 **+26.3%**
  （125 vs 99），每条案例耗时 **−33.5%**（13.9s vs 20.9s）。001–005 codelotte 更便宜，
  006–009 mini 更便宜；7/9 条任务 codelotte 更快，007/008 更慢。裸 API 0/18 是“无工具”的
  结构下界。**结论是成本–时延取舍，不是成功率增量。**
- **实验报告**：`docs/experiments/e4-scaffolding-tax.md`（任务集/基线/干预/指标/
  失败分布/轨迹样本/复现命令/不确定性）；README 数据表已更新。
- **实现修复**（跑数中发现）：
  - mini 适配器的 `--mini-python` 相对路径在子进程 cwd（临时工作区）下找不到，
    已统一转绝对路径；
  - `.mini-venv` 需要额外安装 litellm 的启动期依赖 `mcp`，否则 mini 以
    `ModuleNotFoundError` 启动失败（calls=0）；
  - **Windows shell**：mini 的 `LocalEnvironment` 用 `shell=True`，Windows 上落到
    `cmd.exe`，与它假设的 bash 不符；`mini_runner.py` 在 Windows 上把命令改走
    Git Bash（`bash -lc`），否则 007 会被误判为超时失败（修复前 267s/超时，修复后
    4 次调用/约 22s 通过）。最终 E4 数字使用修正后的 shell。
- **已知局限**：9 条自建任务、2 次重复、一个模型，无置信区间；成功率天花板使
  “谁更可靠”无法回答；codelotte 走 Docker、mini 走本地，隔离不完全对称；
  本轮 codelotte 无失败，五类归因段为空，归因证据仍来自单独语料。
