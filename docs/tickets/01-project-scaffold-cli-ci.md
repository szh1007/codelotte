# 01: 项目骨架 + 可安装 CLI + 测试与 CI 底座

**What to build:** 建立整个项目的工程底座，让后续每一张票据都能"装得上、跑得起、测得了"：用 uv 管理项目与依赖，代码采用 src 布局并产出 `codelotte` 命令行入口（本票只需支持 `--version`）；pytest 测试骨架就位并跑绿；GitHub Actions 在每次推送时自动运行测试；`pyproject.toml` 声明 `[project.scripts]` 入口与 `uv_build` 后端，保证未来 `uv tool install` 可分发的形态不变；`.gitattributes` 统一行尾为 LF；`.env.example` 提供 API Key 占位符模板。

🗣 大白话：这是给房子装地基和电闸——项目能安装、能跑起来、还有"自动质检员"（CI）守着。之后每加一块功能，都踩在这块地基上。

**Blocked by:** None（可立即开始）

**Status:** ready-for-agent

- [ ] `uv run codelotte --version` 输出正确版本号并正常退出（退出码 0）
- [ ] `uv run pytest` 全绿；至少含一个冒烟测试（断言 `--version` 的输出）
- [ ] `uv.lock` 已生成并纳入版本控制；`pyproject.toml` 含 `[project.scripts]` 入口
- [ ] 推送后 GitHub Actions 自动运行测试工作流且通过
- [ ] `.gitattributes` 强制 LF 行尾；`README` 尚不存在属正常（W4 建立）
- [ ] `.env.example` 含 `DEEPSEEK_API_KEY=your-key-here` 占位符，且无任何真实密钥入库
