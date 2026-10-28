# Contributing to codelotte

codelotte 是一个个人求职作品，同时按可协作的开源仓库维护。Issue 与 PR 都欢迎，
但响应是尽力而为，没有 SLA。改动前请先读 [CONTEXT.md](CONTEXT.md)（术语）、
[docs/dev/v1/SPEC.md](docs/dev/v1/SPEC.md)（v1 技术规格，归档）与 [docs/adr/](docs/adr/README.md)（已定的架构决策）。

## 环境

| 依赖 | 版本 / 说明 |
|---|---|
| Python | 3.13（见 `.python-version`） |
| [uv](https://docs.astral.sh/uv/) | 0.13+；仓库用 `uv.lock` 锁依赖 |
| Docker | 可选；`bash` 默认在 Docker 沙箱里跑，没有 Docker 可用 `--no-sandbox` 做本地开发 |
| 模型 API key | 只有真实运行与真实评测需要；单元测试不需要 |

```bash
git clone https://github.com/szh1007/codelotte.git
cd codelotte
uv sync --locked
```

真实运行前创建用户级配置（**这两份文件永不提交**）：

- `~/.codelotte/models.json`：provider、`baseUrl`、`apiKey`、模型条目
- `~/.codelotte/settings.json`：`defaultProvider` / `defaultModel` 等

字段说明见 [docs/tech/configuration.md](docs/tech/configuration.md)。主程序不从环境变量读取
provider / 模型 / API key 配置，也不内置 key；评测适配器会把现有环境传给子进程
（例如 `PYTHONUTF8`），但不会从环境读取密钥。不要把 key 写进任务 TOML、测试、文档或 issue。

## 常用命令

| 目的 | 命令 |
|---|---|
| 跑测试（默认跳过 Docker 组） | `uv run pytest -q` |
| 跑 Docker 集成测试 | `uv run pytest -m docker` |
| Lint | `uv run ruff check .` |
| 类型检查 | `uv run pyright` |
| 启动 TUI | `uv run codelotte` |
| 无头单次运行 | `uv run codelotte -p "..." --allow read` |
| 校验任务集（不花钱） | `uv run codelotte eval run --dry-run` |
| 校验压缩任务集（不花钱） | `uv run codelotte eval compaction --dry-run` |
| 离线自检评测器 | `uv run codelotte eval controls` |

提交前至少跑：`ruff check .`、`pyright`、`pytest -q`。改动涉及 Docker、权限或沙箱时，
再加跑 `pytest -m docker`；涉及 serve 层时加跑 `pytest -m serve`（需要先起 compose）。

## 代码地图

```
src/codelotte/
├── loop.py            Agent 循环、事件流、run 生命周期
├── guardrails.py      死循环三层防御（纯状态机）
├── providers/         wire protocol 适配（已实现 openai-completions；anthropic-messages 预留）
├── tools/             read / write / edit / bash（Minimal Core 只有四个）
├── permissions.py     规则解析、判定、审批落规则、项目 trust
├── sandbox/           Docker 长驻容器 / 本地逃生门
├── compaction/        双触发、结构化摘要、约束重注入
├── session/           append-only JSONL 树、活动分支重建
├── cost.py            峰谷价 + 缓存命中/未命中的逐次记账
├── export.py          HTML / Markdown 单文件导出（纯函数）
├── evals/             任务加载、执行、验收、报表、对照、归因、防御
├── serve/             服务化运行层：配置、中间件客户端工厂、依赖自检（可选依赖组 serve）
└── tui/               Textual 界面（只呈现事件，不放业务逻辑）
```

设计原则：**一切经过 Session**。消息、工具调用、usage、压缩、权限判定、护栏事件都是
同一条 JSONL 树里的 entry；回放、记账、评测与导出共用这一份数据源。

## 改动流程

1. **先对齐问题。** 小修可以直接提 PR；行为变化、接口变化或新实验先开 issue 或更新
   [docs/dev/v2/tickets/](docs/dev/v2/tickets/README.md)（当前）或
   [docs/dev/v3/tickets/](docs/dev/v3/tickets/README.md)（顺延）中的票据，说清楚验收标准。
2. **测试先行。** 修 bug 先写复现测试；新功能先写行为测试。测试名描述行为
   （`test_returns_401_when_token_expired` 风格），一个测试只验证一件事。
3. **最小改动。** 不顺手重构无关代码，不引入未使用的依赖或抽象；匹配现有风格。
4. **跑相关测试，再跑全量。** 提交前全量测试应绿；Docker 组单独跑。
5. **更新证据。** 改了指标口径、任务集或 harness 行为时，同步更新 README 数据表、
   实验报告与票据状态；数字必须来自报表，不手抄、不估算。

### 测试约定

- 单元测试不得访问网络、不得使用真实 API key；用脚本化 Provider / 假 harness 驱动。
- 需要真实模型的验证放在 `evals/`（有明确的任务、预算与报表），不放普通单测。
- Docker 集成测试用 `@pytest.mark.docker` 标记；默认 `pytest -q` 会跳过。
- serve 集成测试用 `@pytest.mark.serve` 标记；默认同样跳过。跑之前先 `cd deploy && docker compose up -d`，
  并 `uv sync --extra serve` 装好可选依赖，再用 `pytest -m serve`。
- 不依赖测试执行顺序；不 mock 本项目自己的核心逻辑（mock 外部边界）。

### 评测约定

- 新任务放 `evals/tasks/NNN-slug.toml`，验收器优先确定性检查；无法确定性验收时才用
  `[verifier.judge]`，并按 [evals/run.md](evals/run.md) 的要求提供 ≥20 条标注样本与 κ。
- 新跑数落 `evals/runs/<UTC时间>-<短 git ref>/`；目录里保留 `report.md`、`report.json`、
  `sessions/` 与必要的工作区快照。**已入库的 run 不修改**，修正时新增一轮。
- 注入/死循环等对抗任务放独立目录（`evals/defense-tasks/`、`evals/loop-tasks/`），
  不要混进主任务集改变历史 pass^k 口径。
- 跑数前先看 [evals/README.md](evals/README.md)；成本与复现命令见各命令的手册。

## 代码风格

- Python 3.13；4 空格缩进；行宽 120（ruff `E501` 已启用）。
- 命名：类 `PascalCase`、函数/变量 `snake_case`、常量 `UPPER_SNAKE_CASE`、私有成员 `_leading`。
- 类型注解优先用 `X | None`，不用 `Optional`/`Union`；公共函数写 Google Style docstring。
- 注释与文档用中文，代码标识符用英文；注释解释「为什么」，不是复述「是什么」。
- 异常处理要具体，不裸 `except Exception`；错误信息带足够上下文，不静默吞异常。
- 日志用标准 `logging`，不要用 `print()` 做运行日志（CLI 的用户可见输出除外）。

## Commit 与 PR

- Commit message 用 Conventional Commits，英文祈使句，首行 ≤72 字符：
  `feat: add ...` / `fix: ...` / `docs: ...` / `test: ...` / `refactor: ...`。
- 一个 commit 做一件事；不要在一次提交里混入无关格式化。
- 分支名建议 `<type>/<short-description>` 或 `issue-<id>`；不要 force push 到共享分支。
- PR 描述写清楚：问题、改法、验证方式（命令与结果）、对评测数字的影响。
- 提交前用 `git diff --staged` 检查是否带入了 key、`.env`、会话文件或私有代码。

## 文档与决策

- 架构决策记录在 [docs/adr/](docs/adr/README.md)：新增/推翻一个关键决策时先写 ADR。
- 票据是施工单元：开始实现时把状态改为进行中，完成后更新验收项与
  [docs/dev/v2/tickets/README.md](docs/dev/v2/tickets/README.md)、
  [docs/dev/v3/tickets/README.md](docs/dev/v3/tickets/README.md) 的状态表；v1 票据已归档在
  [docs/dev/v1/tickets/](docs/dev/v1/tickets/README.md)。
- 数字（成功率、成本、拦截率、测试数）只从报表与命令输出更新；实验结论必须写明
  「证明了什么、不证明什么」。

## 安全问题

不要用公开 issue 报告漏洞。流程见 [SECURITY.md](SECURITY.md)。

## License

提交贡献即表示同意以 [MIT](LICENSE) 许可发布。
