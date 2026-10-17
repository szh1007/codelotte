# 快速开始验证记录（2026-10-18）

> 目的：按 README 的「快速开始」从零走一遍，确认陌生人能在 20 分钟内跑通。
> **这是模拟**：本机 uv 缓存已热、已有 Python 3.13 与 Docker、使用作者已有的 `~/.codelotte` 配置与 API key。
> 冷机器（无缓存、无配置）会多花安装时间；公开仓库的 clone 取决于网络。

## 方法

1. 把当前工作树（含票据 14 的改动）复制到临时目录，`git init` + 提交，得到一个包含改动的最小仓库快照。
2. `git clone` 该快照到另一个空目录（模拟「克隆」）。
3. 在 clone 里严格按 README 的命令执行。

## 结果

| 步骤 | 命令 | 耗时 | 结果 |
|---|---|---|---|
| clone | `git clone <snapshot> clone` | <1 秒 | 216 个文件 |
| 安装 | `uv sync --locked` | 3 秒 | 退出 0，安装 28 个包 |
| 版本 | `uv run codelotte --version` | 1 秒 | `codelotte 0.1.0` |
| 任务校验 | `uv run codelotte eval compaction --dry-run` | 1 秒 | 3 任务 × 4 个 k = 12 条案例，退出 0 |
| 真实任务 | `-p` 修复 `docs/demo/sample` 的 off-by-one | 12 秒 | 退出 0，8 次模型调用，¥0.005663 |
| **合计** | | **17 秒** | `python check.py` 输出 `ok`；`notes.txt` 内容正确 |

## 说明

- 计时为墙钟秒数，单次测量；uv 全局缓存已热，冷缓存会多几分钟（仍远低于 20 分钟）。
- 使用作者已有的 DeepSeek 配置与 API key；配置文件的创建步骤见 README。
- Docker 已启动；`read` / `edit` / `write` 在宿主机执行，`bash` 在容器执行。
- 公开仓库的 clone 路径需要在本票提交并 push 后再复验一次（当前 `origin/main` 还没有 README）。
- 覆盖了安装、配置读取、单次运行、dry-run、真实工具链与确定性验收；未覆盖冷机器 Python 安装、网络代理与全新 API key 申请。
