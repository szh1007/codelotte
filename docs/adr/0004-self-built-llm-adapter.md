# LLM 接入层：自研薄 adapter（httpx2 + 内联 SSE），不用 SDK / litellm

Status: accepted (2026-10-13)

不用 openai SDK 或 litellm，自研约 200-300 行 adapter：**httpx2**（httpx stable 停更 22 个月，OpenAI/Anthropic 官方 SDK 均已迁移 httpx2）+ **内联 SSE 解码器**（httpx-sse 不兼容 httpx2），按 wire protocol 抽象——v1 实现 `openai-completions` 与 `anthropic-messages` 两条路径，两者都能用 DeepSeek 自家端点端到端验证（OpenAI 兼容 `/` + Anthropic 兼容 `/anthropic`），Responses 留作扩展。

理由：① D3 成本工程需要 per-call 的 cache hit/miss 与峰谷时段自记账，现成库遮住这些字段；② 作品信号——「懂协议」高于「会调库」；③ 多协议抽象直接对应面试考点（model routing / protocol）。已知约束写进适配层与测试：带 tools 时 `reasoning_content` 必须回传否则 400；思考模式下 `tool_choice=required` 不可用；`max_tokens` 必须显式设置；并发用信号量（flash 2500 / v4-pro 500）。

被否备选：litellm（黑盒、字段不可见；如未来需要可接入作对照）、openai SDK（仅留作测试对照）。
