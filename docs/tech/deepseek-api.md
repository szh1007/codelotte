# DeepSeek API 事实笔记（2026-10-13）

> 用于：codelotte 的 LLM adapter 设计（第 2 轮 Q7）与成本工程（D3）｜ 方法：官方文档直取（api-docs.deepseek.com 各页）+ 本机 pi 内置目录交叉核对 ｜ 除标注外均为高置信度

## 1. 可用模型（只有 2 个）

| 项 | `deepseek-flash` | `deepseek-v4-pro` |
|---|---|---|
| 版本 | DeepSeek-V4.1-Flash | DeepSeek-V4-Pro-0813 |
| 上下文 | 1M（1,048,576） | 同 |
| 最大输出 | 393,216；`max_tokens` **默认 8K（非思考）/ 64K（思考）/ 128K（effort=max）** | 同 |
| 思考模式 | 支持，**默认开启**（默认 effort=high） | 同 |
| 视觉 | ✓ text+image | ✗ |
| 并发上限 | 2,500 | 500 |

- `deepseek-chat` / `deepseek-reasoner` 已于 **2026-07-24 完全退役**（确认下线，不是未找到）
- 旧名 `deepseek-v4-flash` 等仍被接受但路由到 V4.1-Flash 按 Flash 计费

## 2. 定价（USD / M tokens，峰 / 谷）

| | flash | v4-pro |
|---|---|---|
| 输入 · 缓存命中 | **0.006 / 0.003** | 0.044 / 0.022 |
| 输入 · 缓存未命中 | **0.30 / 0.15** | 1.32 / 0.66 |
| 输出 | **1.20 / 0.60** | 3.96 / 1.98 |

- **off-peak = 峰价 50%**；高峰期（UTC）：周一至五 01:00–04:00、06:00–10:00（北京时间 9–12、14–18 点），**不含中国法定节假日**；其余时段（含周末）全为空闲价
- 无缓存写入费

## 3. 上下文缓存机制

- **自动**磁盘 KV 缓存，无需改代码（`cache_control` 被忽略；不支持 `prompt_cache_key`）
- 命中条件：请求前缀完整匹配已持久化的 cache prefix unit；多轮对话前缀天然命中；仅公共前缀需第 3 次请求才命中；**best-effort，无 TTL 承诺**（通常几小时到几天）
- 观测字段：`usage.prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`（等价 `cached_tokens`）
- `user_id` 提供 KVCache 隔离（影响命中率与隐私）

## 4. 协议与能力

- **OpenAI-compatible**（`/`）；**Anthropic-compatible**（`/anthropic`，`claude-*` 模型名自动映射）；另有 Responses API（为 Codex 适配）
- Tool Calls ✓；Json Output ✓（仅 `json_object`，无 json_schema）；strict 工具 schema 为 Beta，需 `/beta` 端点
- 流式：SSE + `[DONE]`；`stream_options.include_usage=true` 每 chunk 带 usage
- 思考字段：`reasoning_content`（流式在 `delta.reasoning_content`）；控制用 `thinking` + `reasoning_effort`（low/high/max）
- **三条关键约束（agent 循环最易踩）**：
  1. **带 `tools` 时，历史所有 assistant 的 `reasoning_content` 必须回传，否则 400**
  2. 思考模式下 `temperature` 等参数无效；`tool_choice=required/指定工具` 返回 400（仅 none/auto 可用）——与 Anthropic 5.5 的迁移约束同构
  3. 并行工具调用默认开启且**不可关**

## 5. 限流

- **只有并发限制**（flash 2,500 / v4-pro 500，按账号计，与 Key 数无关），无公开 RPM/TPM；超限 429；可免费申请扩容
- keep-alive：流式回 `: keep-alive`；请求 10 分钟未开始推理则服务端断连

## 6. 对 adapter / 成本工程的直接结论

1. adapter 只需实现 **2 个 model id**，兼容面大幅收窄
2. **缓存命中价 = 未命中的 1/50（flash 峰值）→ 命中率是第一成本杠杆**；成本表必须**按时段**建模——pi 目录只建峰价，谷时报账会高估 2×
3. 思考默认开启且 `max_tokens` 默认仅 8K/64K → adapter **必须显式设置输出上限**，否则长输出被截断（`finish_reason=length`）
4. `reasoning_content` 回传规则写进适配层 + 单元测试（这是"真踩过的坑"类面试素材）
5. 限流按并发 → 实现「在途请求信号量」即可，无需 TPM 估算器
6. **两个可演示的成本干预**（D3 实验素材）：缓存命中率提升；非紧急任务调度到 off-peak（省 50%）

## 7. 与 pi 内置目录的交叉核对

- 一致：model id / 成本（峰价）/ contextWindow、maxTokens（pi 取整偏保守）/ `maxTokensField=max_tokens` / `thinkingFormat=deepseek` / `requiresReasoningContentOnAssistantMessages=true`
- 不一致：pi **只建模峰价**（无 off-peak，谷时高估 2×）；v4-pro 的 `thinkingLevelMap` 缺 `low` 档（条目偏旧）；`supportsStrictMode=true` 但内置 baseUrl 非 `/beta`（中置信度存疑）
