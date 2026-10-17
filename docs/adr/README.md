# 架构决策记录（ADR）

> 一条决策一个文件，状态写在文件头的 `Status:` 行。新决策从 0006 起编号；
> 改变已接受的决定时新增一条，并在旧文末标注 `superseded by NNNN`，不改写历史。

| # | 决策 | 状态 | 日期 | 一句话后果 |
|---|---|---|---|---|
| [0001](0001-portfolio-positioning.md) | 定位为「可验证的 harness 工程」（实验报告形态） | accepted | 2026-10-13 | 深度押 D1 评测 / D2 安全 / D4 压缩 / D5 归因，用数据而不是功能清单交付 |
| [0002](0002-python-over-typescript.md) | Python 3.13 + uv，不跟 TypeScript | accepted | 2026-10-13 | 放弃 node 系 agent 生态，换熟练度与国内岗位覆盖率 |
| [0003](0003-session-model.md) | append-only JSONL 树 + 压缩即条目 | accepted | 2026-10-13 | 消息、工具调用、usage、压缩、分支同源；导出 / 评测 / 归因共用一份轨迹 |
| [0004](0004-self-built-llm-adapter.md) | 自研薄 adapter（httpx2 + 内联 SSE），不用 SDK / litellm | accepted | 2026-10-13 | 缓存命中与峰谷计价字段可见；openai-completions / anthropic-messages 双协议可测 |
| [0005](0005-two-layer-execution-security.md) | 权限层与沙箱层相互独立 | accepted | 2026-10-13 | 审批弹窗不是安全边界；bash 默认进 Docker 长驻容器 |

## 如何新增

1. 复制任一 ADR 的结构：标题、`Status: proposed | accepted | superseded`、日期、正文
   （决策 + 理由 + 被否备选）。
2. 文件命名 `NNNN-kebab-title.md`，在上表加一行。
3. 被取代的旧 ADR 不改正文，只在状态行加 `superseded by NNNN`。
