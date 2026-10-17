# 16: 对照组 + 控制 agent 自检

**What to build:** 给考场配两样东西。① **对照组（baseline）**：用同一个任务集分别跑 mini-swe-agent（现成的开源教学级 agent，经适配接同一个 DeepSeek 模型）与裸单轮 API（无工具循环直接作答）——用来区分"模型自身的功劳"和"我们 harness 的增量"（scaffolding tax 意识：不比较的数字没有意义）。② **控制 agent 自检**：用三种"假 agent"检验评测系统本身是否可信——oracle（总能做对，评分应 100%）、no-op（什么都不做，应 0%）、cheating（试图作弊，应被检测/记 0）。这是对"评测系统自己会不会骗人"的防线。

🗣 大白话：给考场配"对照组"和"防作弊检查"——考分要横向比较才有意义；而且先证明考场本身不瞎打分，再相信它打出的分。

**Blocked by:** 15（评测 runner）

**Status:** done（2026-10-18；三组对照与控制 agent 自检均已真实跑通）

- [x] mini-swe-agent 经适配跑通同任务集（同模型、同任务、同次数）
- [x] 裸单轮 API 对照跑通
- [x] 三种控制 agent 结果符合预期：oracle 100%、no-op 0%、cheating 被标记且记 0
- [x] 对照报告可导出：任务级三组并列对比表（成功率/成本/时长）

**实现记录**：

- **Harness 缝**：新增 `evals/harness_types.py`（`Harness` 协议 + `HarnessExecution`）与
  `execute_harness`——所有被测 agent 共用"准备 → 跑 → 验收 → 保护文件检查 → 落轨迹"管线。
  codelotte 的 loop 抽成 `CodelotteHarness`；压缩回归仍走 `execute_task` 兼容入口。
- **对照组**：`codelotte eval compare`。默认三组 `codelotte` / `mini-swe-agent` / `raw`
  （裸单轮 API：一条 user 消息、无 tools）；`--harness` 可重复选择；`--repeat` 三组同值；
  `--dry-run` 校验任务/快照/mini 可用性。父目录写任务级并列对比
  （成功率 · pass^N · 成本 · 平均耗时），各组明细在 `harnesses/<组名>/report.md`。
- **mini-swe-agent 适配**：不把重依赖塞进项目。`evals/mini_runner.py` 由装了
  mini-swe-agent 的独立解释器直接执行，绕开它 CLI 的 prompt_toolkit 控制台依赖；
  内部装配它自己的 `DefaultAgent` + `LocalEnvironment` + `LitellmModel`，保留其提示词、
  bash 工具、步数/墙钟限制与轨迹格式。`--mini-python` 指定解释器；
  不指定时从 PATH 上的 `mini` 推同环境 Python，或当前解释器能 import 则用它。
- **安全与记账**：`evals/mini_proxy.py` 是本地录制代理。mini 子进程只拿到假 key
  （`codelotte-eval-proxy`）和代理地址，真实 key 只在 codelotte 进程内存里注入上游；
  代理同时记录每次调用的真实 usage 与时刻，成本按本项目峰谷价目表计算，不依赖
  litellm 是否认识 DeepSeek 模型。`reasoning_effort` 通过 `model_kwargs` 对齐。
- **控制 agent**：`codelotte eval controls`（离线、零模型调用、不需要密钥/Docker）。
  - `oracle`：落 `[control.oracle.files]` 参考解；缺省时从 `equals`/`contains` 期望推导。
  - `no-op`：什么都不做。
  - `cheating`：写假成功内容 + 篡改所有 `unchanged` 保护文件。
  - 报表顶部“自检结论”逐条给预期/实际/结论；任一不符 CLI 返回 1。
- **Windows 路径修复**：嵌套对照 run 的会话目录原本把完整工作区绝对路径编码进去，
  在 Windows 上超过 260 字符（`git add` 直接失败）。`SessionStore.start` 增加
  `directory_name` 参数，eval 会话用短案例名（如 `003-constrained-append-r1`）做目录；
  生产路径不传，`--continue/--resume` 的项目目录约定不变。
- **任务加固**：为每条 shipped 任务补 `[control.oracle.files]` 参考解，并给只读输入
  （`a/b/c.txt`、`check.py`、`input/policy.txt`、`protected.txt`）加 `unchanged = true`；
  `tests/test_eval_tasks.py` 强制每条任务都有参考解和至少一个保护文件。原 002/005
  只验最终内容、不验“不要改 check.py”的缺口由此补上。
- **真实证据**：
  - 对照：`evals/runs/20261017T223658Z-f2320a8-compare/report.md`（5 任务 × 1 次，
    三组同模型 `deepseek-flash` / `high`；codelotte 与 mini-swe-agent 均 5/5，
    裸单轮 API 0/5）。
  - 自检：`evals/runs/20261017T223904Z-f2320a8-controls/report.md`（oracle 5/5、
    no-op 0/5、cheating 0/5 且 5/5 标记）。
  - 对照跑数使用 `--no-sandbox`，与 mini 的本地环境对齐；成本/耗时口径见报表“口径与限制”。
- **测试**：新增 `test_eval_harnesses.py`（raw/oracle/no-op/cheating 与防篡改标记）、
  `test_eval_mini_baseline.py`（录制代理 + 假 mini 进程 + 轨迹/usage 解析）、
  `test_eval_compare.py`（三组并列报表与自检判定）；CLI 端到端覆盖 `eval controls`
  与 `eval compare`（含 raw 基线）。全量测试从 476 增至 498。
- **文档**：[evals/run.md](../../evals/run.md) §4.5/§4.6（对照与自检操作、mini 安装、
  口径与限制）、[evals/record.md](../../evals/record.md)（新目录布局与跑数记录）、
  [SPEC.md](../../SPEC.md) 测试缝段补充“评测 harness 缝不属于生产测试开关”。
- **已知局限**：v0 任务太短，codelotte 与 mini 都是 5/5，这一轮证明对照管线与成本口径
  可用，还不足以证明 scaffolding tax；更难的任务集与正式 E4 在票据 19/20。
  另：任务里的“执行纪律”（必须用 read/write）不在验收范围内，三组不是同策略 A/B。
