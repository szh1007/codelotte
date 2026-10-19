# CHANGELOG

所有值得一提的变更都记在这里；条目按版本倒序，与 `settings.json` 的
`lastChangelogVersion` 配合：启动时落后就提示，一致就不打扰。

## [Unreleased]

- E3 归因准确率与失败分布：`eval attribute` 增加逐类精确率/召回率/F1、宏观 F1 与 `--run` 真实失败分布（控制 agent / 压缩回归 / 非 codelotte harness 分开计数）；15 条 `author-draft` 语料 15/15、宏观 F1 1.000，15 个 run 里 codelotte 失败 0 条（票据 21）
- E5 防御有效性：新增 `eval defense`（真实 `AgentLoop` + 脚本化 Provider 跑 5 个死循环正向剧本与 3 个正常剧本；汇总真实模型死循环压力、注入任务拦截与 A 桶正常任务误报）、`evals/defense-tasks/` 的 010–012 注入任务与 `evals/loop-tasks/` 的 013 死循环压力任务；结果：死循环剧本 5/5、真实模型压力 3/3 防线介入（任务仍完成）、正常剧本 0/3、注入 27/27、真实正常任务 0/31（票据 21）
- 实验报告 `docs/experiments/e3-attribution-accuracy.md` / `e5-defense-effectiveness.md`
- 评估文档收口：新增 `evals/defense.md`（合并 `defense-tasks/` 与 `loop-tasks/` 的零散 README），重写 `evals/README.md` 为新手入口，统一九个命令的材料/执行/产物说明，并补齐 `run.md` / `record.md` 的目录与链接
- 修复：`codelotte eval --help` 因 help 字符串里的未转义百分号触发 argparse traceback；改为 `%%` 并加 CLI 回归测试
- E1 压缩回归矩阵：摘要模板 `seven`/`compact` 与切点策略 `minimal`/`wide` 的 A/B；`eval compaction --strategy/--template/--combo` 跑 6 任务 × 4 k × 3 组合，报表按组合分组；结果：短任务完成率/保留率 100%（天花板），长任务保留率 83–97%；三节模板短任务 k=5 成本 −22.8%，长任务保留 93.3% vs 87.8% 且成本 −23.1%；wide 只买到短任务高 k 可达性（票据 20）
- E2 成本曲线：`eval cost` 从会话 usage 重算实际 / 无缓存 / 全峰价 / 两者叠加；两轮真实跑数缓存命中率 89.0% / 89.4%，相对无缓存+全峰价总节省 80.8% / 81.4%（票据 20）
- 复盘文 `docs/experiments/retrospective.md`（结论段中英双语）与复现脚本 `scripts/reproduce-e1-e2.sh`
- E4 scaffolding tax 实验：任务集从 5 条扩到 9 条（多文件调试、规格重构、长规则结算、边界条件），新增 2 条主观 judge 任务（并发 review / API 设计取舍，各 20 条 `author-draft` 样本 κ=1.000）；三组 repeat 2 对照：codelotte 18/18、mini-swe-agent 18/18、裸 API 0/18；成功率打平，codelotte 成本 +15.4%、调用 +26.3%、耗时 −33.5%；实验报告 `docs/experiments/e4-scaffolding-tax.md`（票据 19）
- 修复：mini-swe-agent 适配器的 `--mini-python` 相对路径在子进程工作区下找不到，启动前统一转绝对路径；独立 venv 需补装 litellm 启动期依赖 `mcp`，否则 mini 以 `calls=0` 启动失败
- 修复：Windows 上 mini-swe-agent 的 `LocalEnvironment` 落到 `cmd.exe`（与它假设的 bash 不符），适配器在 Windows 上改用 Git Bash 执行命令，避免命令语义失真导致的假失败
- 修复：`007-refactor-tokenizer` 的 `notes.md` 验收要求从“必须出现 spec.md 字面量”改为“必须提到 tokenize”，避免正确实现因措辞被判失败
- 失败归因与回归任务：失败案例自动归入五类病位（模型误判/工具 schema/上下文丢失/循环/环境），带证据与置信度进 `report.md`“失败归因”段与 `report.json` 的 `failure_*` 字段；`codelotte eval attribute` 用标注语料算准确率/混淆矩阵；`codelotte eval regression` 把失败案例转成可直接跑的回归任务（保留原 setup/verifier，只换 id）；规则见 `evals/attribution.md`（票据 18）
- LLM judge 兜底与 κ 校准：任务可声明 `[verifier.judge]` 评分卡（维度分数 + 理由）；确定性检查优先，确定性失败不调用 judge；`codelotte eval judge` 用 ≥20 条人工标注样本算 Cohen's κ，低 κ/样本不足/校准缺失在报表标 ⚠；judge 成本/分数/理由进报表（票据 17）
- 对照组与控制 agent 自检：`codelotte eval compare`（codelotte / mini-swe-agent / 裸单轮 API 同任务集并列对比，任务级成功率/成本/耗时）与 `codelotte eval controls`（oracle 应 100%、no-op 应 0%、cheating 应 0% 且被标记；离线零成本）；抽出 harness 协议，mini-swe-agent 走独立解释器 + 本地录制代理（假 key、真实 usage），任务增加 `[control.oracle.files]` 参考解与只读输入 `unchanged` 保护（票据 16）
- 修复：嵌套评测 run 的会话目录曾把完整工作区绝对路径编码进目录名，Windows 上超过 260 字符；eval 会话改用短案例名目录（`SessionStore.start(directory_name=...)`），生产路径的 `--continue/--resume` 约定不变
- 通用测评：`codelotte eval run`（任务 × 重复次数、pass^k、每任务成本/耗时/计费时段）、TOML 仓库快照与命令验收器、`report.md/json` 与失败会话定位；新增 B 桶任务 004/005；`eval compaction` 明确拒绝无 checkpoint 的通用任务（票据 15）
- CI 增加 B 桶冒烟 job（需 `DEEPSEEK_API_KEY` secret；未配置时跳过）
- 重构：单任务执行核心抽到 `evals/execution.py`，压缩回归与通用测评共用（票据 15）
- README v1：中文版（原计划中英双语；2026-10-18 按用户决定只保留中文版）、真实会话导出样例、v0 基线数据表、架构图与 30 秒演示；新增 ADR 索引 0001–0005、3 分钟演示脚本与示例工程、dogfood 使用日志脚手架（票据 14）
- 专用测评 - 压缩回归 v0：`codelotte eval compaction`（3 任务 × k=0/1/3/5）——强制压缩策略、压缩后 checkpoint 探针（确定性事实比对 + 人工标注表）、完成率/状态保留率报表；锁定 git ref / 种子 / 依赖版本 / 任务指纹，原始轨迹与工作区落盘（票据 13）
- 修复：settings.json 的压缩阈值此前没有真正传进触发判定（票据 13）
- 修复：Docker 模式下文件工具不识别容器路径 `/workspace/...`，模型会把产物写到宿主工作区之外；现在映射回宿主 cwd（票据 13 审查）

## [0.1.0] - 2026-10-17

- 核心循环：流式对话、tool_calls 装配、工具执行与结果回填，会话落盘 JSONL（票据 01–04）
- 会话树：`--continue` / `--resume` / `--fork`，分支成树、前缀逐字节可缓存（票据 06）
- 成本记账：官方价目 + 峰谷时段判定 + 按模型/时段/缓存的分项账单（票据 07）
- 导出：会话转单文件自包含 HTML 或 Markdown（票据 08）
- 权限层：allow/ask/deny 规则、破坏性命令守门、四档审批、无头 fail-closed（票据 09）
- 沙箱：bash 默认在每会话一个 Docker 长驻容器里执行（只挂工作区、`--network none`、内存/CPU/PID/超时限额）；`--no-sandbox` 为显式逃生门（风险警告 + 执行记录 `env=local`）（票据 10）
- 死循环三层防御：重复/无进展拦截、连续失败熔断（禁用工具请模型总结）、任务目标与硬约束重注入与温和终止；阈值可在 settings.json 配置，拦截事件落会话并在 TUI/导出高亮（票据 11）
- 压缩 v1：软/硬触发阈值可在 settings.json 配置（默认 60% / 85%，比例 0.2–0.9 且 gap ≥0.2）；软触发在任务边界、硬触发压到最小保留集；七项结构化摘要、硬约束独立重注入；compaction 记录保留边界、原始记录仍可查，TUI/导出/`-p` 均可见（票据 12）
- 配置：用户级 settings.json / models.json，无环境变量来源、无内置默认（SPEC §M）；思考开关与强度统一在模型条目的 `reasoning_effort`（none 关闭思考；开启时思考总是既落盘又展示）
