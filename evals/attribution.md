# 失败归因与回归任务（票据 18）

> 一次失败不再只说“它没做出来”，而是给出**病在哪一层**：模型误判、工具 schema、
> 上下文丢失、循环、环境。归因是规则版 v0：确定性、可解释、零额外成本。
>
> 操作入口：`codelotte eval attribute`（准确率）与 `codelotte eval regression`
> （失败 → 回归任务）；报表里的“失败归因”段自动出现。

## 1. 五类病位

| 类别 | 含义 | 典型证据 |
|---|---|---|
| `model`（模型误判） | 理解/决策/执行错；**兜底类别**，置信度最低 | 确定性验收失败，轨迹里没有别的信号 |
| `tool_schema`（工具 schema） | 工具没被正确使用：参数畸形、缺必需参数、调了不存在的工具 | `tool_call.parseError`、`缺少必需参数`、`未知工具` |
| `context_loss`（上下文丢失） | 压缩/装配导致信息缺失 | 压缩后重新读取压缩前读过的文件 |
| `loop`（循环） | 打转被拦或预算耗尽 | `guardrail` 事件、`iterationLimit`、`ModelCallBudgetExceeded` |
| `environment`（环境） | 沙箱/网络/依赖/验收设施坏了 | 运行错误含 Docker/连接/依赖标记、验收异常、轨迹缺失 |

## 2. 规则与优先级

一条失败只给一个类别。先命中的规则胜出：

1. **运行错误**里的确定性信号：
   - `ModelCallBudgetExceeded` / `max_model_calls` → `loop`（高）
   - Docker/连接/依赖/权限等基础设施标记 → `environment`（中）
   - 超时：期间 ≥3 次工具结果 → `loop`（中）；否则 → `environment`（中）
   - 验收器自身异常或工作区准备失败 → `environment`（高）
2. **轨迹不可用**（没有轨迹文件、文件不存在、读不动）：先看案例级错误里的
   预算/基础设施信号；都没有才归 `environment`（高）。
3. **循环**：`iterationLimit` 或 `guardrail` 事件 → `loop`。
   `planning` / `reasoning` 层的熔断/终止记高置信；工具层单次拦截记中置信。
4. **工具 schema**：参数畸形（高）> 调了不存在的工具（中）> 参数错误
   （出现 ≥2 次记高，否则中）。
5. **上下文丢失**：会话里发生过压缩，且之后又读取了压缩前读过的文件（`read` 工具、
   同一路径）。只压缩、没有重读，不归入这一类。
6. 以上都不命中：有保护文件作弊标记 → `model`（中）；否则 `model`（低）。

证据（`evidence`）写进报表与 JSON，`signals` 保留机器可读信号
（如 `guardrail:tool:repeat`、`reread:a.txt`、`parse_error:edit`）。

### 2.1 为什么是这个优先级

- 环境错误会让整轮运行失去意义，先于轨迹内容判断；
- guardrail/迭代上限是**系统已经认定**的循环，比“看起来像丢了上下文”更硬；
- 工具参数错误是协议级缺陷，模型连调用都没组织好，先于内容判断；
- 压缩后重读是“信息确实丢过”的可观测代理，但不等于最终失败一定由它导致，
  所以排在 schema/loop 之后；
- `model` 是兜底，不把“没证据”包装成“已确诊”。

## 3. 归因怎么进报表

`eval run` 的 `report.md`，以及 `eval compare` / `eval controls` 的每组 harness
明细 `report.md` 新增“失败归因”段（对照/自检的父报表只做并列汇总，不含该段）：

- 五类计数与占已归因失败的比例；
- 逐条失败：任务、重复序号、类别、置信度、证据；
- 未归因的失败单独计数（非 codelotte harness，轨迹格式不同）。

`report.json` 的每个 case 带 `failure_class` / `failure_confidence` /
`failure_evidence` / `failure_signals`。归因在跑完案例后自动计算，不额外调用模型、
不增加成本。

## 4. 准确率语料（首版）

- 文件：`evals/attribution/labels.jsonl`；会话：`evals/attribution/sessions/*.jsonl`。
- 每行字段：

  ```json
  {"id": "loop-repeat-block", "session": "evals/attribution/sessions/loop-repeat-block.jsonl",
   "human_class": "loop", "labeler": "author-draft", "note": "重复 read 被工具层拦截",
   "verifier_detail": "内容不符：任务未完成", "flagged": false}
  ```

  可选 `case_error`（模拟运行错误）；`session` 相对仓库根。
- 15 条样本，五类各 3 条；其中 `env-missing-trajectory` 故意指向不存在的轨迹文件。
- 命令：

  ```bash
  uv run codelotte eval attribute --dry-run   # 只校验类别/数量
  uv run codelotte eval attribute             # 跑分类器，写 attribution-report.md/.json
  ```

- 退出码：`0` = 准确率达标且标注已复核；`1` = 准确率低于阈值或标注含 `draft`；
  `2` = 样本/路径配置错误。

**首版结果**：15/15（100.0%），阈值 80%；**标注者是作者草稿
（`labeler=author-draft`），所以报告标 ⚠、命令退出码 1**。语料按五类构造，存在
天花板效应——它证明规则按文档工作，不代表真实失败上的泛化能力。作者复核后应把
`labeler` 改成真实标注者，并补充从真实跑数里截取的失败轨迹。

## 5. 失败 → 回归任务

```bash
# 先预览（不写文件）
uv run codelotte eval regression \
  --run evals/runs/<run-id> --task 002-fix-off-by-one --dry-run

# 生成到默认目录 evals/regressions/
uv run codelotte eval regression --run evals/runs/<run-id> --task 002-fix-off-by-one

# 生成的文件可以直接跑（单独目录，不混进默认任务集）
uv run codelotte eval run --tasks evals/regressions --dry-run
```

- 保留原任务的 `setup` / `verifier` / `checkpoints` / 预算 / 参考解，只替换 `id`；
  文件头写来源 run、任务、重复序号、归因与失败详情。
- 新 id 默认 `regression-<原 id>`，冲突时追加 `-2`、`-3`。
- **绝不覆盖**已有文件；写盘后会再用 `load_task` 校验一遍。
- `evals/regressions/` 不参与默认 `eval run`（默认目录是 `evals/tasks`），避免
  回归任务改变历史任务集的指纹与 pass^k 口径。
- 当前示例 `evals/regressions/regression-002-fix-off-by-one.toml` 来自 raw 对照的
  真实失败；raw 没有 codelotte 轨迹，所以归因段如实写“不可用”。

## 6. 已知局限

- 规则版 v0 只看会话与案例级事实，不看最终工作区内容、不读完整轨迹语义；
  模糊失败容易落到 `model` 兜底。
- 上下文丢失的代理是“压缩后重读同一文件”；模型没重读但确实因压缩丢信息时，
  规则会漏判。
- 归因只对 codelotte harness 有意义；mini-swe-agent / 裸 API 的轨迹格式不同，
  报表里不归因（不是“环境”）。
- 语料是作者构造的 15 条，`author-draft`；尚无真实失败上的准确率。
- 循环的语义检测仍由 guardrails 负责；归因只报告“系统拦了/预算耗尽”，不重新判定
  模型是否在语义上打转。

## 7. 代码地图

| 文件 | 职责 |
|---|---|
| `src/codelotte/evals/attribution.py` | 五类分类器、样本科普、混淆矩阵报告 |
| `src/codelotte/evals/promote.py` | 失败案例 → TOML 回归任务 |
| `src/codelotte/evals/runner.py` | 跑完案例后自动归因 |
| `src/codelotte/evals/eval_report.py` | 报表“失败归因”段 |
| `evals/attribution/` | 标注语料与首版准确率报告 |
| `evals/regressions/` | 生成的回归任务（不参与默认任务集） |
| `tests/test_eval_attribution.py` | 分类规则、优先级、语料校验 |
| `tests/test_eval_attribution_cli.py` | `eval attribute` / `eval regression` 端到端 |
