# 面试材料包

> 面向 codelotte 的 Agent 工程岗求职。这里只放**面试用**的材料；
> 仓库治理文档在根目录：[SECURITY.md](../SECURITY.md) · [CONTRIBUTING.md](../CONTRIBUTING.md) ·
> [ROADMAP.md](../docs/dev/v1/ROADMAP.md)。
>
> 数据快照：**2026-10-19**（版本 `0.1.1`；票据 01–22 均标记 done，
> 其中录屏、dogfood 连续记录、整场口述计时为作者待补项）。

## 文件

| 文件 | 用途 | 什么时候用 |
|---|---|---|
| [data-sheet.md](data-sheet.md) | 一页纸数据表：仓库、评测可信度、E1–E5、演示 | 面试时屏幕共享；写 JD 对应材料时查数 |
| [walkthrough.md](walkthrough.md) | 20 分钟动线：数据表 → 现场演示 → 代码走读 → 失败分析；含追问答案与兜底 | 面试前演练；面试中按时间轴讲 |
| [resume.md](resume.md) | 四条简历 bullet + 每个数字的来源与边界 | 投递前更新；面试前对照 |
| [project-experience-v1.md](project-experience-v1.md) | 简历版项目经历 v1：概述+指标、5 条技术介绍、技术栈、关键词索引 | 写简历项目经历；面试前按索引预习 |
| [pi-agent-and-claude-code.md](pi-agent-and-claude-code.md) | Pi agent 极简主义介绍、codelotte 的参考点、与 Claude Code 的横向对比 | 准备「为什么用 Pi 的理念」「和 Claude Code 比怎么样」 |
| [rehearsal-session-20261019.md](rehearsal-session-20261019.md) | 2026-10-19 现场演示段的真实会话导出（12.3s、7 次调用、¥0.009622、缓存 87%） | 核对演示数字；现场失败时的回放证据 |

## 先读哪一份

- **投简历**：先看 [project-experience-v1.md](project-experience-v1.md) 的概述与指标，
  再从 [resume.md](resume.md) 摘 bullet。第 4 条（dogfood）当前是 0 天 / 0 PR，暂不投递。
- **理解设计来源**：读 [pi-agent-and-claude-code.md](pi-agent-and-claude-code.md)，
  准备「为什么用 Pi 的极简理念」「和 Claude Code 比怎么样」两类问题。
- **面试前 1 天**：读一遍 [project-experience-v1.md](project-experience-v1.md) 的关键词索引，
  按 [walkthrough.md](walkthrough.md) §0 的检查清单准备，至少把现场演示跑一遍。
- **面试中**：共享 [data-sheet.md](data-sheet.md)，按 walkthrough 的时间轴讲。

## 三条必须主动说出的限制

材料里的每个数字都配了「不能证明什么」。面试时不要等对方问，主动说：

1. **任务集有天花板**：正式评测 27/27，9 条任务 × 3 次；说明失败还没被任务集逼出来。
   长任务压缩保留率已降到 83–97%，这是下一轮加长任务链的依据。
2. **部分标注是作者草稿**：judge 的 κ=1.000、归因的 15/15 都基于 `author-draft` 语料，
   规则与样本同源；报表标 ⚠、命令退出码 1。独立复核前不当作泛化结论。
3. **成本节省是反事实**：E2 的 80.8% 是从 usage 重算「无缓存 + 全峰价」，
   不是关掉缓存重跑的 A/B；E1/E4 多数只有 1–2 次重复，没有置信区间。

另外两条事实边界：

- 当前只实现 `openai-completions`，`anthropic-messages` 是协议抽象预留；
- dogfood 连续记录尚未开始（0 天 / 0 个自产 PR），不写进已完成成果。

## 数字的刷新方式

所有数字来自入库报表与命令输出，不手抄、不估算：

```bash
# 工程检查
uv run pytest -q                     # 测试数
uv run ruff check . && uv run pyright

# 仓库热度（投递前）
gh api repos/szh1007/codelotte --jq .stargazers_count

# 评测（不需要重跑模型的）
uv run codelotte eval controls --dry-run
uv run codelotte eval cost --run evals/runs/20261018T154112Z-fa9db83 --dry-run
uv run codelotte eval attribute --dry-run
uv run codelotte eval defense --dry-run

# 需要真实模型/花钱的重跑
uv run codelotte eval run
uv run codelotte eval compaction --combo minimal:compact
uv run codelotte eval compare
```

刷新后同步更新：本目录的材料（含 [walkthrough §8](walkthrough.md#8-附录-b演练记录) 的演练记录）、
[README 数据表](../README.md#证据)、[PLAN §8](../docs/dev/v1/PLAN.md)、[CHANGELOG](../CHANGELOG.md)、
[票据 22](../docs/dev/v1/tickets/22-materials-pack.md)。**已入库的 run 不修改**，修正时新增一轮。

## 材料与交付物的对应

| 面试考点 | 材料 | 仓库证据 |
|---|---|---|
| 你怎么验证系统有效？ | data-sheet §1/§4、walkthrough §3/§5.5 | `evals/`、E4 报告、控制 agent |
| 上下文压缩与回归 | data-sheet §2、walkthrough §5.4 | E1 报告、`eval compaction` |
| 死循环 / 异常处理 | data-sheet §6、walkthrough Q6 | `guardrails.py`、E5 报告 |
| 权限与沙箱 / 注入 | data-sheet §6、walkthrough §5.3 | `permissions.py`、`sandbox/`、SECURITY.md |
| 成本工程 | data-sheet §3、walkthrough Q7 | `cost.py`、E2 报告 |
| 轨迹归因 | data-sheet §5、walkthrough §6.1 | `evals/attribution.py`、E3 报告 |
| 为什么这么设计 | walkthrough §5 | ADR 0001–0005 |

## 维护纪律

- 新增实验或重跑后，先更新报表，再更新本目录；不要反过来。
- 任何「证明了什么」旁边都要有「不证明什么」。
- 不把计划（ROADMAP）写成已完成；不把作者草稿写成人工复核。
- 不提交 API key 或含私有代码的会话导出；演示/演练用的公开任务会话可以入库，
  提交前检查是否含密钥、私有路径或他人数据。
