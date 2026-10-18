# codelotte v1 开发票据（Tickets）

> 由 [SPEC.md](../../SPEC.md) 拆分的 **23 张曳光弹票据**：每张是贯穿全栈（界面 → 循环 → 工具 → 会话 → 测试）的一条窄而完整的小路，独立可演示、可验证，按依赖顺序推进。
> 发布形式：随仓库提交。`Status: ready-for-agent` 表示该票据可被实现者（人或 agent）直接认领。

## 阶段总览

| 阶段 | 票据 | 对应里程碑 |
|---|---|---|
| 0 骨架上电 | 01–02 | W1 上半 |
| 1 工具循环 | 03–04 | W1 下半 |
| 2 交互与记录 | 05–08 | W2 |
| 3 安全与压缩 | 09–13 | W3 |
| 4 MVP 收口 + 投递 | 14 | W4 |
| 5 评测与实验 | 15–21 | W5 |
| 6 材料收口 | 22 | W6 |
| Stretch（砍单第一位） | 23 | — |

## 依赖层级（每层内的票可并行）

| 层 | 票据（← 表示被谁阻塞） |
|---|---|
| 1 | 01（无阻塞） |
| 2 | 02（←01） |
| 3 | 03（←02） |
| 4 | 04（←03）· 06（←03） |
| 5 | 05（←04）· 09（←04）· 10（←04）· 11（←04）· 23stretch（←04） |
| 6 | 07（←05）· 08（←06,07）· 12（←06,07） |
| 7 | 13（←12）· 14（←08,12）· 15（←10,12） |
| 8 | 16（←15）· 17（←15）· 18（←15） |
| 9 | 19（←16）· 20（←13,15）· 21（←18,11） |
| 10 | 22（←14,19,20,21） |

## 票据列表

| # | 标题 | Blocked by | 状态 |
|---|---|---|---|
| [01](01-project-scaffold-cli-ci.md) | 项目骨架 + 可安装 CLI + 测试与 CI 底座 | None | ✅ done（CI 已验证） |
| [02](02-first-end-to-end-roundtrip.md) | 一次真实的一问一答（全链路首穿） | 01 | ✅ done（真机验收通过） |
| [03](03-agent-loop-read-tool.md) | Agent 循环 + read 工具 | 02 | ✅ done（真机验收通过） |
| [04](04-write-edit-bash-tools.md) | write / edit / bash 工具 + 本地执行器 | 03 | ✅ done（真机验收通过） |
| [05](05-tui-v1.md) | TUI v1（Textual 终端界面） | 04 | ✅ done（真机验证通过） |
| [06](06-session-tree-fork.md) | 会话树与分支 / fork | 03 | ✅ done（真机验证待做） |
| [07](07-cost-ledger.md) | 成本记账与展示 | 05 | ✅ done（真机对账通过） |
| [08](08-html-export-v1.md) | HTML 会话导出 v1 | 06, 07 | ✅ done（真机样例待做） |
| [09](09-permission-layer.md) | 权限层（规则 + 审批 + trust） | 04 | ✅ done（真机 TUI 审批 + 与票据 10 沙箱联训均通过） |
| [10](10-docker-sandbox.md) | Docker 沙箱 | 04 | ✅ done（真机 Docker Desktop 验证通过） |
| [11](11-loop-guardrails.md) | 死循环三层防御 | 04 | ✅ done（自动化全绿；三层均有剧本化触发测试） |
| [12](12-compaction-v1.md) | 压缩 v1（双触发 + 结构化摘要） | 06, 07 | ✅ done（自动化全绿；含压缩后续跑） |
| [13](13-compaction-regression-suite.md) | 专用测评 - 压缩回归 v0 | 12 | ✅ done（自动化全绿；基线 12 案例入库） |
| [14](14-readme-and-dogfood.md) | README v1 + 演示材料 + dogfood 启动 | 08, 12 | ✅ done（2026-10-18；录屏与 ≥3 天 dogfood 暂时忽略，作者后续补充） |
| [15](15-eval-runner.md) | 评测 runner（任务格式 + pass^k + CI 冒烟） | 10, 12 | ✅ done（2026-10-18；CI eval-smoke 全绿） |
| [16](16-baselines-and-control-agents.md) | 对照组 + 控制 agent 自检 | 15 | ✅ done（2026-10-18；三组对照与 oracle/no-op/cheating 自检均跑通） |
| [17](17-llm-judge-kappa.md) | LLM judge 兜底（κ 校准） | 15 | ✅ done（2026-10-18；20 条 `author-draft` 样本 κ=1.000，待作者复核标注后重跑） |
| [18](18-failure-attribution.md) | 失败归因分类器（D5） | 15 | ✅ done（2026-10-18；五类规则 + 失败分布进报表 + 失败 → 回归任务；15 条 `author-draft` 语料 15/15，待复核真实失败） |
| [19](19-experiment-e4-scaffolding-tax.md) | 实验 E4：scaffolding tax 对照 | 16 | ✅ done（2026-10-18；任务集扩到 9 条、新增 2 条 judge 任务；三组 repeat 2：codelotte 18/18、mini 18/18、raw 0/18；成功率打平，成本 +15.4%、耗时 −33.5%） |
| [20](20-experiment-e1-e2-compaction-cost.md) | 实验 E1+E2：压缩回归 + 成本曲线 | 13, 15 | ready-for-agent |
| [21](21-experiment-e3-e5-attribution-defense.md) | 实验 E3+E5：归因准确率 + 防御有效性 | 18, 11 | ready-for-agent |
| [22](22-materials-pack.md) | 材料包：治理文档 + 面试脚本 + 数据刷新 | 14, 19, 20, 21 | ready-for-agent |
| [23](23-stretch-mcp-stdio.md) | （Stretch）MCP stdio 最小客户端 | 04 | ready-for-agent（可延后） |

## 使用方式

- **认领**：挑一张「所有 Blocked by 都已完成」的票据，按验收标准实现；完成后勾选验收项并更新本表状态。
- **顺序纪律**：依赖表即施工顺序；跳过阻塞边会返工。
- **术语**：以 [CONTEXT.md](../../CONTEXT.md) 为准；技术背景见 [SPEC.md](../../SPEC.md) 与 [PLAN.md](../../PLAN.md)。
