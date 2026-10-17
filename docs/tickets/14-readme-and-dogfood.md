# 14: README v1 + 演示材料 + dogfood 启动

**What to build:** 把作品"打扮到能见人"：双语 README（英文主 + 中文镜像），结构为"一句话定位 → 30 秒演示 → 证据数据表 → 架构图 → 快速开始 → 文档索引"——**证据先于功能**；ADR 索引串联 0001–0005；录制 3 分钟演示录屏（任务 → 工具调用 → 审批 → 成本面板 → HTML 导出）；同步启动 dogfood：建立使用日志，从本票起每天用 codelotte 干真实开发任务并记录（任务/结果/翻车/成本）。验收标准是"陌生人 20 分钟克隆跑通"。

🗣 大白话：让面试官能快速看懂作品，并且从今天开始"自己真的每天用它"——之后面试里那句"我每天都在用，这是使用数据"就靠这段时间积累。

**Blocked by:** 08（HTML 会话导出 v1）、12（压缩 v1）

**Status:** in progress（2026-10-18；README / ADR / 样例 / dogfood 脚手架完成，录屏与连续记录待作者）

- [x] 陌生人（模拟）按 README 在 20 分钟内完成克隆→安装→跑通一个任务（本地 git clone 实测 17 秒，含一次真实模型调用；热缓存 + 作者配置）
- [x] README 含至少一个真实导出样例与一张真实数据表（直接用 v0 基线，不是占位）
- [ ] dogfood 日志建立并连续记录 ≥3 天（每条含任务/耗时/翻车/成本）
- [ ] 3 分钟录屏完成并链接进 README
- [x] ADR 索引就位；中文 README 与英文版内容对齐

**实现记录**：

- 双语 README：[README.md](../../README.md)（英文主）与 [README.zh-CN.md](../../README.zh-CN.md)；
  结构为「一句话定位 → 30 秒演示 → 证据数据表 → 架构图 → 快速开始 → 文档索引」。
- ADR 索引：[docs/adr/README.md](../adr/README.md)，串联 0001–0005，并写明新增/取代规则。
- 真实导出样例：[docs/examples/](../examples/README.md)——一次真实修复任务（7 次调用 / 约 9 秒 /
  ¥0.004394）与 v0 基线的 k=5 压缩案例（5 次压缩 / 11 次调用）；HTML 单文件零外链，Markdown 可直接读。
  生成命令与来源会话写在同一目录的 README。
- 演示材料：[docs/demo/](../demo/README.md) 含 3 分钟分镜、可复现的示例工程
  `docs/demo/sample/`、录屏后要改的两处 README 链接、临时导出忽略规则。
- dogfood：[docs/dogfood/README.md](../dogfood/README.md) 与 [log.md](../dogfood/log.md)（起始 2026-10-18；
  表头为空，等待真实任务逐条填写，不预造数据）。
- 快速开始实测：工作树快照 `git init` + 提交后 `git clone` 到空目录（216 个文件）→
  `uv sync --locked` 3 秒 → `--version` 1 秒 → `eval compaction --dry-run` 1 秒 →
  在演示工程跑完整修复任务 12 秒、¥0.005663，退出码 0；总计 17 秒。
  详见 [docs/demo/quickstart-validation.md](../demo/quickstart-validation.md)（本机 uv 缓存已热、
  使用作者已有配置；冷机器与公开 clone 需 push 后复验）。
- 未完成项说明：录屏需要作者本机录制并上传（脚本已就绪，两版 README 留有明确占位）；
  dogfood 连续 ≥3 天只能在真实使用后勾选，日志表已就绪。
