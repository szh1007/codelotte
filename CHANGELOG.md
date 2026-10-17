# CHANGELOG

所有值得一提的变更都记在这里；条目按版本倒序，与 `settings.json` 的
`lastChangelogVersion` 配合：启动时落后就提示，一致就不打扰。

## [Unreleased]

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
