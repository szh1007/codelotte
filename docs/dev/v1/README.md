# v1 开发资料（归档）

> 对应 codelotte 0.1.x。2026-10-20 归档；v0.2.0 起的开发资料在 [../v2/](../v2/README.md)。
> 这些文档保持 v1 原貌，不再更新；历史链接已随目录迁移修正。

## 文档

| 文档 | 内容 |
|---|---|
| [PLAN.md](PLAN.md) | v1 开发方案：里程碑、实验计划、作品定位 |
| [SPEC.md](SPEC.md) | v1 技术规格与实现决策 |
| [ROADMAP.md](ROADMAP.md) | v1 路线图、明确不做的事 |
| [tickets/](tickets/README.md) | v1 的 22 张票据与验收状态 |

## ADR

| # | 决策 | 状态 |
|---|---|---|
| [0001](../../adr/0001-portfolio-positioning.md) | 定位为「可验证的 harness 工程」 | accepted |
| [0002](../../adr/0002-python-over-typescript.md) | Python 3.13 + uv，不跟 TypeScript | accepted |
| [0003](../../adr/0003-session-model.md) | append-only JSONL 树 + 压缩即条目 | accepted |
| [0004](../../adr/0004-self-built-llm-adapter.md) | 自研薄 adapter，不用 SDK / litellm | accepted（部分实现） |
| [0005](../../adr/0005-two-layer-execution-security.md) | 权限层与沙箱层相互独立 | accepted |

累计索引：[docs/adr/README.md](../../adr/README.md)。项目入口：[README.md](../../../README.md)
