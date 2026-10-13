# 技术栈：Python 3.13 + uv（而非 TypeScript）

Status: accepted (2026-10-13)

作品用 Python 而非模仿对象 pi 的 TypeScript：本人经验全部在 Python（后端；做过从零 agent runtime 与 RAG 全链路），国内目标岗位 JD 中 Python 覆盖率近 100%，前端/UI 能力由成熟 TUI 库与 AI 辅助补齐。放弃 TS 的代价：失去 agent 工具链的「母语」生态（MCP 官方 SDK、node 系 TUI），且拿不到 IDE 客户端方向（VS Code Extension）的加分——若目标是客户端方向，以薄壳扩展单独补。包管理与运行统一用 uv（uv init / add / run / lock；uv tool install 分发），不用 pip 直装。

被否备选：TypeScript（工具链原生、CLI/Web 演示一体，但熟练度低一档，违背「熟练度 > 招聘口味」原则）。
