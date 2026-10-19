# 21: 实验 E3+E5：归因准确率 + 防御有效性

**What to build:** 两份收尾实验报告。**E3（归因准确率）**：失败归因分类器 vs 人工标注的准确率与混淆情况，附失败分布。**E5（防御有效性）**：对抗桶（prompt 注入样例 + 死循环样例）下的拦截率报告——目标 100% 拦截，同时记录误报率（正常任务被误拦的比例）。两份报告进 README 数据表与面试材料包。

🗣 大白话：证明"看得清"（归因）和"拦得住"（注入与死循环）都有数字撑腰——不是嘴上说安全，是测试集里 n/n 全拦下来了。

**Blocked by:** 18（失败归因分类器）、11（死循环三层防御）

**Status:** done（2026-10-19；交付完成：E3 归因准确率/失败分布、E5 注入/死循环/误报、README 与实验索引。**E3 语料仍是 `author-draft`，报告标 ⚠、退出码 1；复核标注属于后续作者工作**）

- [x] E3：归因准确率报告（人工标注对照 + 混淆矩阵）与失败分布
- [x] E5：注入与死循环用例全量拦截率报告；误报率记录在案
- [x] 两份报告进 README 数据表与材料包索引

**实现记录**：

- **E3**：`eval attribute` 增加逐类精确率/召回率/F1、宏观 F1；`--run` 递归扫描
  run 的 `report.json`，汇总 `passed=false` 的真实失败分布（控制 agent、压缩回归、
  非 codelotte harness 分开计数）。15 条 `author-draft` 语料 **15/15、宏观 F1
  1.000**；已入库 run 里 **codelotte 失败 0 条**，23 条非 codelotte 失败全部来自
  raw（结构下界）；控制 42 条、压缩 124 条跳过。报告：
  `evals/attribution/attribution-report.md`；解读：
  `docs/experiments/e3-attribution-accuracy.md`。
- **E5**：新增 `eval defense`（离线）与 `evals/defense-tasks/` 的 3 条注入任务
  （010 源码注释、011 规则文件示例、012 诱导改保护文件），以及 `evals/loop-tasks/`
  的 1 条真实模型死循环压力任务（013：同一命令跑 10 次）。死循环用真实 `AgentLoop`
  + 脚本化 Provider 跑 5 个正向剧本（repeat / stagnation / circuitBreaker /
  planning terminate / batch repeat）与 3 个正常剧本（40 轮不同调用、失败重试、
  未到阈值的重复）：**5/5 拦截、0/3 误报**。真实模型压力：**3/3 防线介入**
  （stagnation + reinject），模型被提醒后改法，任务仍完成 3/3。注入任务 5 条 × 多 run：
  **27/27 未执行注入**；真实 A 桶正常任务 **0/31 出现 guardrail 事件**。
  新增跑数 `20261019T023111Z-287e2cb`（6/6，¥0.035142）、
  `20261019T023154Z-287e2cb`（9/9，¥0.047238）与
  `20261019T024620Z-287e2cb`（3/3，¥0.079322）。报告：
  `evals/defense/defense-report.md`；解读：
  `docs/experiments/e5-defense-effectiveness.md`。
- **文档**：README 增加 E3/E5 数据段与文档索引；`docs/experiments/README.md` 增两行；
  `evals/README.md` 九个命令、目录地图与 `eval defense` 说明；`evals/run.md` §4.10；
  `evals/attribution.md` 失败分布；`evals/record.md` 新记录；SPEC/CHANGELOG 更新。
- **已知局限**：E3 语料是作者构造的 `author-draft`，真实 codelotte 失败为 0，
  没有真实分布；E5 死循环剧本是脚本化模型行为，真实压力只覆盖 1 条自建任务，
  注入只覆盖 5 条自建任务，误报审计只认 guardrail 事件。
