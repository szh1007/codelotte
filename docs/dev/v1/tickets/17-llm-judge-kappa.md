# 17: LLM judge 兜底（κ 校准）

**What to build:** 遇到"标准答案不好写"的任务时，引入 LLM 阅卷兜底：按评分卡（明确维度 + 理由输出）对结果打分；同时用 ≥20 条人工标注样本计算 judge 与人工的一致性 κ——κ 低于阈值时该验收器被标记"不可靠"并告警。纪律：确定性验收仍然优先，judge 仅在任务显式声明时启用；judge 的分数与理由连同 κ 一起进运行报告。

🗣 大白话：有些题目没法用脚本判对错（比如"这个修复方案合理吗"），只能再请一个模型当阅卷人——但得先证明阅卷人靠谱：拿 20 份人工判过的卷子对照，算一致性（κ），一致性太低就承认"这题验收不可靠"，而不是装作没看见。

**Blocked by:** 15（评测 runner）

**Status:** done（2026-10-18；机制、校准、报表与真实跑数完成；20 条标注为作者草拟 `author-draft`，待作者复核后重跑）

- [x] judge 接口与评分卡模板落地（每个维度给出分数与理由）
- [x] κ 计算与报告：≥20 条人工标注样本对照，结果文档化（**当前 20 条为作者草拟，`labeler=author-draft`，待复核**）
- [x] 低一致性验收器的告警机制（报告中标红/警告）
- [x] 默认确定性优先：未声明 judge 的任务不走 judge（有测试）

**实现记录**：

- **任务声明**：`[verifier.judge]` 支持 `dimensions` / `rubric` / `pass_threshold` /
  `kappa_threshold` / `samples` / `calibration`。judge-only 任务合法；确定性检查失败时
  绝不调用 judge。judge 任务放在 `evals/judge-tasks/`，避免 `eval controls` 依赖模型。
- **评分卡**：judge 收到任务指令、rubric、确定性检查结果与最终工作区文本（有长度上限）；
  必须返回 `{"scores": {...}, "reasons": {...}}`，每个维度 0–1 分 + 一句理由；
  `overall = 均值`，`overall >= pass_threshold` 才算通过。解析严格：缺维度、越界分数、
  空理由都记 judge 失败。
- **执行管线**：`execute_harness` 在确定性 `verify()` 通过后才跑 judge；judge 调用走
  同一个 `StreamingClient`（`tools=None`），成本按项目峰谷价目表计入案例总成本；
  模型调用数与 judge 成本单独记录（`judge_calls` / `judge_cost`）。
- **κ 校准**：`codelotte eval judge` 读 `samples.jsonl`（每行 `id` / `submission` /
  `human_pass` / `labeler`），逐条跑 judge，算 Cohen's κ 与一致率，写
  `calibration.json` + `calibration.md`；少于 20 条直接拒绝。运行时只读校准结果，
  不会为每条案例重跑校准样本。
- **可靠性告警**：κ 缺失、样本 <20、κ < `kappa_threshold`、或标注者带 `draft`
  都会在报表标 ⚠ 并写警告；judge 分数仍保留，不静默丢弃。`eval judge` 在任一
  可靠性检查失败（含草稿标注）时退出码 1。
- **校准绑定**：`calibration.json` 记录 `task_id`、`model`、`judge_fingerprint`
  （任务指令 + 维度 + rubric + 阈值）与 `labels_sha256`；运行时任一字段与当前任务
  不一致，旧 κ 标 ⚠ 并提示重跑，避免换模型/改 rubric 后仍复用旧校准。
- **报表**：`report.md` 新增 judge 列与“LLM judge”段（每个维度的分数/理由/κ/⚠）；
  `report.json` 的 case 里带全部 `judge_*` 字段；judge 成本计入总成本。
- **真实证据**：
  - 校准：20 条样本（`labeler=author-draft`），κ=**1.000**，一致率 100%，
    成本 ¥0.033613；文件 `evals/judges/006-code-review/calibration.json/.md`。
    **因为标注是草稿，报表把这次校准标为 ⚠**（κ 高但未复核）。
  - judge 任务：`006-code-review` 一次通过，judge overall **1.00**（阈值 0.70），
    4 次模型调用（3 agent + 1 judge），¥0.003675；报表同时显示“草稿标注”警告：
    `evals/runs/20261018T123909Z-5264236/report.md`。
  - **天花板效应**：20 条样本刻意清晰（10 好/10 坏），κ=1.0 证明管线可用，不代表
    judge 在模糊样本上也可靠；作者复核标注后应重跑，并加入 borderline 样本。
- **测试**：新增 `test_eval_judge.py`（评分卡解析/κ/校准/绑定校验）、
  `test_eval_judge_execution.py`（确定性优先/judge-only/成本合并/低 κ 警告）、
  CLI 的 `eval judge --dry-run` 与 judge 评测端到端；全量 **528 passed**
  （8 个 Docker 集成用例 deselect，另跑 8 passed）。
- **已知局限**：judge 只看最终工作区文本，不读完整轨迹；标注者字段目前是
  `author-draft`，不是作者已复核的人工标签；judge 任务不参与控制组自检。
