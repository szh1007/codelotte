# 失败归因准确率（首版）

> 语料：`evals/attribution/labels.jsonl` · 15 条失败样本；规则见 `evals/attribution.md`。

## 结论速览

- 准确率：15/15（100.0%），阈值 80%
- 标注者：包含 `draft`（作者草稿），⚠ **本轮准确率只证明规则按文档工作，不是人工复核后的泛化结论**。
- 判定：⚠ 未达标/待复核

| 类别 | 命中 / 样本 |
|---|---|
| 模型误判 | 3 / 3 |
| 工具 schema | 3 / 3 |
| 上下文丢失 | 3 / 3 |
| 循环 | 3 / 3 |
| 环境 | 3 / 3 |

## 混淆矩阵

| 人工 \ 规则 | 模型误判 | 工具 schema | 上下文丢失 | 循环 | 环境 | 样本 |
|---|---|---|---|---|---|---|
| 模型误判 | 3 | 0 | 0 | 0 | 0 | 3 |
| 工具 schema | 0 | 3 | 0 | 0 | 0 | 3 |
| 上下文丢失 | 0 | 0 | 3 | 0 | 0 | 3 |
| 循环 | 0 | 0 | 0 | 3 | 0 | 3 |
| 环境 | 0 | 0 | 0 | 0 | 3 | 3 |

读法：行是人工标注，列是规则判定；对角线是命中。没有样本的类别记 0，不代表规则在该类别上可靠。

## 逐条结果

| 样本 | 人工 | 规则 | 置信度 | 证据 |
|---|---|---|---|---|
| `model-wrong-edit` | 模型误判 | 模型误判 ✅ | 低 | 确定性验收失败：内容不符：notes.txt 缺少 for i in range(n): |
| `model-ignored-constraint` | 模型误判 | 模型误判 ✅ | 中 | 保护文件被改动（模型越界）：内容不符：check.py 被改动 |
| `model-no-tool-use` | 模型误判 | 模型误判 ✅ | 低 | 确定性验收失败：内容不符：out.txt 不存在 |
| `schema-malformed-json` | 工具 schema | 工具 schema ✅ | 高 | 工具参数不是合法 JSON（最近一次：edit） |
| `schema-missing-argument` | 工具 schema | 工具 schema ✅ | 中 | 工具参数错误：错误：缺少必需参数 old_string（应为非空字符串） |
| `schema-unknown-tool` | 工具 schema | 工具 schema ✅ | 中 | 调用了未知工具：search |
| `context-reread-a` | 上下文丢失 | 上下文丢失 ✅ | 高 | 压缩 1 次后重新读取 a.txt（这些内容压缩前已经读过） |
| `context-reread-two` | 上下文丢失 | 上下文丢失 ✅ | 高 | 压缩 1 次后重新读取 notes.txt（这些内容压缩前已经读过） |
| `context-reread-hard` | 上下文丢失 | 上下文丢失 ✅ | 高 | 压缩 1 次后重新读取 requirements.txt（这些内容压缩前已经读过） |
| `loop-repeat-block` | 循环 | 循环 ✅ | 中 | 工具层拦截：重复调用 read(a.txt) 3 次 |
| `loop-iteration-limit` | 循环 | 循环 ✅ | 高 | 触发迭代上限（模型/工具循环未在预算内收敛） |
| `loop-planning-terminate` | 循环 | 循环 ✅ | 高 | 规划层终止：连续 3 次重复操作 |
| `env-missing-trajectory` | 环境 | 环境 ✅ | 中 | 运行错误指向基础设施（FileNotFoundError）：FileNotFoundError: 轨迹文件缺失 |
| `env-docker-error` | 环境 | 环境 ✅ | 中 | 运行错误指向基础设施（Docker）：RuntimeError: Cannot connect to the Docker daemon at unix:///var/run/docker.sock |
| `env-verifier-crash` | 环境 | 环境 ✅ | 高 | 验收设施失败：验收异常：FileNotFoundError: python 不在 PATH |

## 口径与局限

- 分类器是**规则版 v0**：只读会话记录（工具调用/结果、guardrail、压缩、迭代上限）与案例级错误，不调用模型，不读最终工作区内容。
- 优先级：环境 > 循环 > 工具 schema > 上下文丢失 > 模型兜底；先命中的规则胜出，置信度随证据强度变化。
- 首版语料是作者按五类构造的失败轨迹（`labeler=author-draft`），存在天花板效应；真实失败上的准确率需要作者用真实跑数复核。
- 归因只对 codelotte harness 的轨迹有意义；mini-swe-agent / 裸 API 的轨迹格式不同，报表里不归因。
