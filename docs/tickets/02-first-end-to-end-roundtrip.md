# 02: 一次真实的一问一答（全链路首穿）

**What to build:** 打通"命令行 → 模型 API → 流式解析 → 会话落盘"的最小完整链路。用户执行 `codelotte -p "问题"`（非交互模式）后：请求经自研适配层按 OpenAI 兼容协议发往 DeepSeek，回答以流式方式逐字打印；每次调用的 token 用量（输入/输出/缓存命中）作为结构化记录写入 append-only 的 JSONL 会话文件。这是第一条贯穿所有层的"曳光弹"——后面的每张票据都在这个链路上加宽。关键实现点：内联 SSE 解码器（不用现成的 httpx-sse）；API Key 仅从环境变量读取；网络 5xx/429 做指数退避重试。

🗣 大白话：让程序第一次真的"对上话"——你说一句、模型答一句；而且这场对话被"记账"了：说了多少字、花了多少 token，全部记录在案。

**Blocked by:** 01（项目骨架 + 可安装 CLI + 测试与 CI 底座）

**Status:** done（2026-10-14；含真机验收：`codelotte -p` 实测 exit=0、会话落盘含 usage、UTF-8 输出修正）

- [x] `codelotte -p "用一句话解释递归"` 流式打印回答后正常退出（退出码 0）—— 真机实测两轮通过（DeepSeek 实际调用）
- [x] API Key 仅从环境变量读取；缺失时给出可读的错误提示而非堆栈 —— 无 Key 时退出码 2 + 中文提示（有测试）
- [x] 会话 JSONL 文件生成：含 session 头（schema 版本/工作目录）与 message 记录 —— 实测落盘 `~/.codelotte/sessions/--D--__WorkSpace__-codelotte--/`
- [x] usage 记录完整（输入 token / 输出 token / 缓存命中 token）—— 实测 `in=34 out=114 hit=0 miss=34`
- [x] SSE 解码器有单元测试，覆盖分片乱序、空回复、`[DONE]` 边界 —— 8 个用例（含逐字节切分、跨分片多字节 UTF-8、CRLF、keep-alive、多行 data）
- [x] 429/5xx/网络错误有指数退避重试且可测（不改变请求前缀，保持缓存友好）—— 3 个重试用例，含"重试请求体逐字节相同"断言；已输出内容后不再重试
