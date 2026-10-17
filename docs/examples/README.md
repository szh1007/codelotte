# 会话导出样例

这里放的是**真实跑出来的会话**导出的 HTML / Markdown，不是手写示意图。HTML 是单文件、
零外链、断网可开；Markdown 用于终端或编辑器直接读。

| 文件 | 来源 | 说明 |
|---|---|---|
| `session-demo-fix-bug.html` / `.md` | 2026-10-18 的真实运行 | 修 `docs/demo/sample` 的 off-by-one：read → edit → bash → write；7 次模型调用，约 9 秒，¥0.004394（40 条记录） |
| `session-001-audit-report-k5.html` / `.md` | 压缩回归基线 `20261017T173510Z-037104e` 的 `001-audit-report` k=5 | 强制压缩 5 次的任务轨迹；11 次模型调用；任务成本 ¥0.0266 + checkpoint 探针 ¥0.0112 |

## 重新生成

### 演示会话（当前目录的最近一次会话）

```bash
cd docs/demo/sample
# 先按 docs/demo/README.md 跑一次任务，然后：
uv run codelotte export --html -o ../../examples/session-demo-fix-bug.html
uv run codelotte export --md   -o ../../examples/session-demo-fix-bug.md
```

`export` 读的是**当前目录对应的会话存储**（`~/.codelotte/sessions/<项目键>/`），
所以必须在会话发生时的工作目录里执行。

### 基线案例（会话在 `evals/runs/` 里，不在用户会话存储中）

```bash
uv run python -c "
from pathlib import Path
from codelotte.cost import load_catalog
from codelotte.export import render_session_html, render_session_markdown
from codelotte.session.store import load_branch

p = Path('evals/runs/20261017T173510Z-037104e/sessions/'
         '--D--__WorkSpace__-codelotte-evals-runs-20261017T173510Z-037104e-workspaces-001-audit-report-k5-r1--/'
         '20261017T173602Z_cc9fde5e.jsonl')
entries = load_branch(p)
for suffix, render in (('html', render_session_html), ('md', render_session_markdown)):
    Path(f'docs/examples/session-001-audit-report-k5.{suffix}').write_text(
        render(entries, load_catalog(), session_name=p.name),
        encoding='utf-8', newline='\n',
    )
"
```

`render_session_*` 是纯函数（同样输入逐字节同输出），每次重新生成都会得到相同文件；
若导出格式升级，重新跑上面的命令刷新样例即可。
