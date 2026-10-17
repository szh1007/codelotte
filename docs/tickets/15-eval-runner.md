# 15: 评测 runner（任务格式 + pass^k + CI 冒烟）

**What to build:** 建"标准化考场"：用 TOML 定义评测任务（id / bucket 分桶 A 真实自用·B 对抗构造·C 公开子集 / 仓库快照（git ref + 初始化脚本）/ 指令 / 验收器 / 预算上限）。runner 对每个任务重复 k=3 次，记录随机种子与**实际计费时段**，把结果（pass^k、每任务成本、耗时、完整轨迹）落盘为运行记录——锁依赖、锁 git ref、存原始会话，保证任何数字可复现。验收器阶梯：命令式检查优先（跑测试、比对文件内容），LLM judge 兜底（票据 17 实现）。CI 挂冒烟子集（对抗桶），每次推送自动跑。

🗣 大白话：给项目建一个固定的"考场"——一批标准题目、统一的判分规则、每次交卷都有记录。以后任何改动，先看考分涨没涨，而不是凭感觉说"应该更好了"。

**Blocked by:** 10（Docker 沙箱）、12（压缩 v1）

**Status:** in progress（2026-10-18；runner/任务/文档完成；CI 冒烟待仓库 secret 与首次 push 验证）

- [x] 任务格式有 schema 与文档；首批任务：A 桶 ≥2 条、B 桶 ≥3 条
- [x] 一条命令跑全部任务，输出 pass^k / 每任务成本 / 耗时的汇总报告
- [x] 运行记录完整：锁依赖、任务 git ref、原始轨迹、种子、计费时段
- [ ] CI 冒烟（B 桶子集）在推送时自动运行并可见结果（workflow 已加；需配置 `DEEPSEEK_API_KEY` secret 并 push 后首次验证）
- [x] 失败任务可直接定位到对应会话文件（报告内给路径/编号）

**实现记录**：

- 任务格式：新增 `[setup.snapshot]`（git ref + 初始化脚本 + 可选 repo 路径）、
  `verifier.command`（字符串数组，不经 shell）与 `command_timeout`；checkpoints 改为
  **压缩回归必填、通用测评 可省略**。字段与示例见
  [evals/run.md](../../evals/run.md)。
- 首批任务：原有 A 桶 2 条 + 新增 B 桶 `004-prompt-injection-resistance`
  （数据里藏"忽略之前的指令"注入）与 `005-scope-discipline`（受保护文件诱导写入），
  现在 A=2、B=3。
- 通用测评：`codelotte eval run` 默认 `--repeat 3`，按任务 × 重复次数运行，
  输出 `pass^N`、每任务成功率/成本/平均耗时/计费时段；`--bucket` 支持 CI 只跑 B 桶。
  `report.md` / `report.json` / `sessions/` / `workspaces/` 落盘；失败案例在报表里
  直接给会话路径。
- 复用：单任务执行核心抽到 `evals/execution.py`（压缩回归与通用测评 共用），
  工作区准备/快照/验收抽到 `evals/workspace.py`；`eval compaction` 仍走强制压缩与 checkpoint。
- 真实冒烟：`20261017T201602Z-99d0d4d`（1 条 B 任务 × 3 次重复，pass^3 3/3，
  18 次模型调用，¥0.011544，低谷 18；开发期工作树指纹锁定）。
- CI：`.github/workflows/ci.yml` 增加 `eval-smoke` job（仅 push，B 桶子集，artifact + job summary）。
  未配置 `DEEPSEEK_API_KEY` secret 时跳过冒烟步骤；因此"CI 自动运行并可见结果"需要在仓库设置
  secret 并 push 后首次确认，本票暂不勾选该项。
- 验证：`476 passed + 8 Docker passed`，ruff / pyright 干净；真实冒烟报表见
  `evals/runs/20261017T201602Z-99d0d4d/report.md`。
