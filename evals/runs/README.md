# evals/runs

每轮压缩回归一个目录：`<UTC 时间>-<git ref 前 7 位>/`。目录里是报表与原始证据
（会话 JSONL、最终工作区、checkpoint、人工标注表），不手工编辑——要新数字就重跑。

操作入口：[evals/README.md](../README.md)；任务写法：[evals/tasks/README.md](../tasks/README.md)。

| run | 说明 |
|---|---|
| `20261017T173510Z-037104e` | v0 基线：3 任务 × k=0/1/3/5 × 1 次，DeepSeek flash，见 `report.md` |

方法与口径：[docs/tech/compaction-regression.md](../../docs/tech/compaction-regression.md)。
