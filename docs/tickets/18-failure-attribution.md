# 18: 失败归因分类器（D5）

**What to build:** 从会话轨迹自动判断一次失败"病在哪一层"：模型误判（理解/决策错）、工具 schema（工具没被正确使用/参数错）、上下文丢失（压缩/装配导致信息缺失）、循环（打转被拦）、环境（沙箱/网络/依赖）。输出失败分布报告（进 pass^k 报告），并提供"失败轨迹一键转回归任务"的命令——修过的坑变成永久的测试用例。归因准确率用人工标注样本对照报告（首版给基线即可）。

🗣 大白话：教系统"看病"——任务挂了不再只说"它没做出来"，而是能说清"这次是模型理解错了 / 工具没用对 / 上下文丢东西了"。病历写多了，就知道该修哪儿；每个确诊的失败还能自动变成体检项目（回归用例），防止复发。

**Blocked by:** 15（评测 runner）

**Status:** done（2026-10-18；分类规则、准确率报告、失败 → 回归任务与报表段完成；
15 条语料为作者草稿 `author-draft`，待作者复核真实失败轨迹后重测）

- [x] 分类特征/规则文档化；对样本失败轨迹能给出五类归因之一
- [x] 归因准确率首版报告（人工标注对照；**当前 15 条为作者构造，`labeler=author-draft`，待复核**）
- [x] 「失败 → 回归任务」转换命令可用（生成可跑的任务文件）
- [x] 归因结果进 pass^k 报告（失败分布段）

**实现记录**：

- **五类**：`model`（模型误判，兜底）/ `tool_schema` / `context_loss` / `loop` /
  `environment`。规则优先级：运行错误里的环境/预算信号 → 轨迹缺失 → guardrail/
  迭代上限 → 工具参数畸形 → 压缩后重读 → 模型兜底。每条归因带 `evidence` 与
  机器可读 `signals`；纯规则、不调用模型。文档：`evals/attribution.md`。
- **自动归因**：`run_harness_case` 在失败后用会话轨迹归类，字段写进
  `EvalCaseResult`（`failure_class` / `failure_confidence` / `failure_evidence` /
  `failure_signals`）；只对 codelotte harness 归因，mini/raw 的轨迹格式不同，
  计入“未归因”。
- **报表**：`report.md` 新增“失败归因”段（五类计数/占比/含义 + 逐条证据）；
  `report.json` 的 cases 带 `failure_*` 字段。归因不增加模型调用与成本。
- **准确率**：`codelotte eval attribute` 读 `evals/attribution/labels.jsonl`
  （15 条，五类各 3 条，含缺失轨迹/ Docker 错误/验收器崩溃等环境样本），
  写 `attribution-report.md/.json`（准确率、混淆矩阵、逐条证据）。当前
  **15/15（100%）**，标注者 `author-draft`，报告标 ⚠、命令退出码 1。
- **失败 → 回归任务**：`codelotte eval regression --run <run> --task <id>` 保留原任务
  的 setup/verifier/checkpoints/预算/参考解，只换 `id`，加来源头；默认写到
  `evals/regressions/`（不参与默认 `eval run`），绝不覆盖已有文件，写盘后再用
  `load_task` 校验。示例由 raw 对照的真实失败生成；非 codelotte 轨迹的归因段如实
  写“不可用”。
- **测试**：新增 `tests/test_eval_attribution.py`（五类规则、优先级、语料校验、
  混淆矩阵）、`tests/test_eval_attribution_cli.py`（两个命令端到端）、
  `tests/test_eval_promote.py`（TOML 生成/防覆盖）；runner 与报表测试补归因断言。
- **已知局限**：`context_loss` 用“压缩后重读同一文件”作代理，会漏判；模糊失败
  容易落到 `model` 兜底；语料是构造样本，准确率有天花板效应，真实失败上的
  准确率尚未测量。
