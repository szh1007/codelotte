# 3 分钟演示录屏：脚本与拍摄清单

> 目标：让第一次看到这个仓库的人在 3 分钟内明白——它是什么、怎么用、钱花在哪、
> 以及「压缩后还记得任务」这件事是怎么被量化出来的。
>
> **状态：脚本与演示工程已就绪，录屏待作者完成。** 录好后把链接填进
> [README.md](../../README.md) 的演示段。
> 快速开始的实测记录见 [quickstart-validation.md](quickstart-validation.md)（本地 clone 17 秒；热缓存 + 作者配置）。

## 1. 录制前准备

| 项 | 要求 |
|---|---|
| 终端 | Windows Terminal，约 120×32，字号 16，深色主题 |
| 模型 | `~/.codelotte/models.json` 配好 `deepseek-flash`；为录制流畅可把 `reasoning_effort` 设为 `low` |
| Docker | Docker Desktop 已启动（bash 默认进容器；read/write/edit 在宿主机执行） |
| 工作目录 | `docs/demo/sample`（一个故意写坏的 `calc.py` + 验收脚本 `check.py`） |
| 干净起点 | 工作区干净（`git status --short` 无输出）；录完用 `git checkout -- docs/demo/sample` + `rm -f docs/demo/sample/notes.txt` 还原 |
| 隐私 | 不出现 API key、`~/.codelotte/models.json` 内容、终端历史、浏览器标签 |

演示任务（直接粘贴）：

```text
Fix the off-by-one bug in calc.py. First read calc.py and check.py. Then use edit to change the loop so it sums exactly the first n elements. Run 'python check.py' to confirm it passes. Then create notes.txt containing exactly the text 'for i in range(n):' followed by one newline (no indentation). Do not modify check.py.
```

## 2. 分镜（总长约 3:00）

### 0:00–0:15 一句话开场

画面：仓库根目录。

> "codelotte 是一个终端 coding agent。这个演示只讲三件事：它怎么干活、成本怎么看、
> 压缩后的记忆怎么被验证。"

### 0:15–0:40 启动与任务

```bash
cd docs/demo/sample
uv run codelotte
```

启动后先停留 2 秒展示启动横幅：版本、当前模型、思考档位、沙箱、上下文窗口、
工作目录与会话状态（新建/恢复）。然后在 TUI 输入演示任务。让流式输出完整走一小段，
不要剪掉"正在思考"的停顿。

### 0:40–1:30 工具调用与审批

会依次出现：

1. `read calc.py` / `read check.py`；
2. `edit calc.py` —— **审批弹层**出现时，展示四个选项，选"本会话允许"（或"本次允许"）；
3. `bash python check.py` —— 再展示一次审批，选允许；输出 `ok`。

讲解点：模型只输出"想调用什么"，真正执行的是 harness；权限层决定放不放行，
bash 在 Docker 容器里跑。

### 1:30–1:55 完成与成本

`write notes.txt` 后任务结束。把镜头对准 TUI 底部状态栏：

- token / 缓存命中；
- 本次运行与会话累计费用（人民币元）；
- 会话文件路径。

> "每一次模型调用都记了 token、缓存命中、峰谷价。参考值：演示任务 7 次调用、约 9 秒、¥0.0044。"

### 1:55–2:30 压缩后还记得吗（打开已生成的真实样例）

```bash
# 浏览器打开（无需服务器；单文件、断网可开）
docs/examples/session-001-audit-report-k5.html
```

滚动展示：

- 5 个 compaction 折叠块（摘要 + 保留边界）；
- 每次压缩后的 checkpoint 问答；
- 成本面板。

再打开 `evals/runs/20261017T173510Z-037104e/report.md`，指出结论表：
k=0/1/3/5 完成率、状态保留率、成本。

> "这是 v0 基线：12 条案例、112 次调用、¥0.265。任务太短，两个指标都到了天花板——
> 它证明的是管线和数据可复现，不是压缩无损。E1 已经拉长任务并做了策略 × 模板矩阵：
> 长任务保留率 93.3% vs 87.8%、成本 −23.1%，但仍是单次重复，不能当无损结论。"

### 2:30–2:55 导出刚才的会话

在 `docs/demo/sample` 里：

```bash
uv run codelotte export --html -o demo-export.html
```

打开生成的 HTML：时间线、工具调用折叠块、成本面板。强调"零外链、断网可开、
内容逐字来自会话记录"。

### 2:55–3:00 收尾

> "代码、任务集、基线轨迹和复现命令都在仓库里。README 里先放数据，再放功能。"

## 3. 录完做什么

1. 上传到 Bilibili / YouTube / GitHub Release（不要把视频提交进仓库）。
2. 把链接填进 README 的“30 秒演示”段。
3. 删除临时导出：`rm -f docs/demo/sample/demo-export.html`。
4. 还原演示工程：`git checkout -- docs/demo/sample && rm -f docs/demo/sample/notes.txt`。
5. 如果要展示**实时**压缩而不是回放样例：把用户级 `models.json` 的 `contextWindow`
   临时下调到 8000 左右，跑一个步骤更多的任务；录完删掉该键（恢复随包默认 1048576），或改回 1048576。

## 4. 可选：不录屏也能用的终端演示

README 里的 30 秒演示来自一次真实运行：

```bash
cd docs/demo/sample
uv run codelotte -p "Fix the off-by-one bug in calc.py. First read calc.py and check.py. Then use edit to change the loop so it sums exactly the first n elements. Run 'python check.py' to confirm it passes. Then create notes.txt containing exactly the text 'for i in range(n):' followed by one newline (no indentation). Do not modify check.py." \
  --allow read --allow edit --allow write --allow 'bash(python check.py)'
```

无头模式是 fail-closed：没有 `--allow` 的工具调用会被拒绝并回传模型。上例只放行了
这一次演示需要的规则；`python check.py` 被放行，随后一条 `cd . && od -c ... && git diff ...`
没匹配到规则被拒绝，模型改用 `read` 验证——这是权限层真实工作的证据。
