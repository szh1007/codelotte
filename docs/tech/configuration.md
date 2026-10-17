# 配置系统（事实笔记，2026-10-17 定稿 v4）

> 对应 SPEC §M。一句话：**配置只从用户级 `~/.codelotte/` 的文件里读，没有任何环境变量来源，
> 也没有替你猜的默认**——provider/模型/超时/端点/密钥必填，缺哪个就报错指路；只有窗口与输出
> 上限（只能下调）、展示名与思考强度有随包默认值。

## 三份配置的分工（v3：随包与用户级彻底分家）

| 文件 | 角色 | 内容 |
|---|---|---|
| 随包 `src/codelotte/providers/models.json` | **计费 / 展示 / 上限参考**（纯函数用） | 价目（峰谷三档）、峰谷窗口、节假日、货币、官方端点提示、每模型的展示名与窗口/输出**默认值**（兼上限）、思考强度默认档 |
| 用户级 `~/.codelotte/models.json` | **运行参数的唯一来源** | provider 级 `baseUrl` / `apiKey` + `models` 清单（选哪些模型、可下调的窗口与输出、显示名、思考强度 `reasoning_effort`） |
| 用户级 `~/.codelotte/settings.json` | **运行设置** | 选哪个 provider / 哪个模型、bash 超时、更新提示的版本水位 |

另有 `permissions.json`（权限规则）与 `trusted`（信任表），见票据 09。

**为什么运行参数只从用户级读**：`baseUrl`/`apiKey` 能决定"请求发往哪里、用哪把钥匙"——放进
项目目录等于让陌生仓库改你的请求去向；随包文件会进公开仓库，更不能放密钥（有测试守卫）。
**为什么随包文件不参与请求**：它随版本走，只能当"事实与默认值"——价目、模型上限、展示名。

## settings.json（文件键与 `Settings` 字段一一对应）

```json
{
  "lastChangelogVersion": "0.1.0",
  "defaultProvider": "deepseek",
  "defaultModel": "deepseek-flash",
  "commandTimeoutSeconds": 120,
  "guardrailRepeatLimit": 3,
  "guardrailStagnationLimit": 2,
  "guardrailFailureLimit": 3,
  "guardrailPlanningLimit": 2,
  "compactionSoftThreshold": 0.60,
  "compactionHardThreshold": 0.85
}
```

| 键 | 字段 | 行为 | 必填？ |
|---|---|---|---|
| `lastChangelogVersion` | `last_changelog_version` | 启动时与当前版本比对：落后就打印 `CHANGELOG.md` 里的新增条目并写回；首次/一致/回退只记不报 | 否（自动维护） |
| `defaultProvider` | `default_provider` | 选用户级 models.json 里的 providers 条目 | **是** |
| `defaultModel` | `default_model` | 选该 provider 的 models 条目（必须是随包目录里已适配的 id） | **是** |
| `commandTimeoutSeconds` | `command_timeout` | bash 工具默认超时（**1–600 秒，超范围报错**） | 否（默认 120） |
| `guardrailRepeatLimit` | `guardrail_repeat_limit` | 连续同名同参调用第 N 次被工具层拦截（**2–100**） | 否（默认 3） |
| `guardrailStagnationLimit` | `guardrail_stagnation_limit` | 同名同参连续 N 次返回相同结果后，拦截下一次调用（**2–100**） | 否（默认 2） |
| `guardrailFailureLimit` | `guardrail_failure_limit` | 连续 N 次工具失败（含权限拒绝/沙箱错误/参数畸形/工具层拦截）后熔断回合（**2–100**） | 否（默认 3） |
| `guardrailPlanningLimit` | `guardrail_planning_limit` | 工具层累计拦截 N 次后，规划层温和终止回合（**2–100**；首次拦截批次总是先重注入任务目标与硬约束，之后的批次累计到 N 次才终止） | 否（默认 2） |
| `compactionSoftThreshold` | `compaction_soft_threshold` | 压缩软触发比例（**0.2–0.9**；与 hard 至少相差 0.2） | 否（默认 0.60） |
| `compactionHardThreshold` | `compaction_hard_threshold` | 压缩硬触发比例（**0.2–0.9**；与 soft 至少相差 0.2） | 否（默认 0.85） |

- 未知键：忽略并在启动时提示（不静默）；已知键类型写错：直接报错退出。
- 死循环三层防御（票据 11）：工具层（同名同参重复 / 结果无进展）→ 推理层（连续工具失败熔断，禁用工具请模型总结）→ 规划层（重注入任务目标与硬约束；累计拦截到阈值则温和终止）。每次拦截写一条 `event`（kind=guardrail）进会话，TUI 与导出高亮；四个阈值按**run**计数，上一轮不牵连新任务。
- 压缩双阈值（票据 12）：软/硬触发比例必须满足 **0.2 ≤ soft < hard ≤ 0.9** 且 **hard - soft ≥ 0.2**；只改一边时另一边用默认值，按生效值校验（例如只配 soft=0.75、默认 hard=0.85，差距只有 0.10，会直接报错）。硬触发直接压到最小保留集，软触发只在任务边界压。
- 会话目录不在这里：固定为 `~/.codelotte/sessions`。
- 权限规则、密钥、计费规则都不在这里（各归各的文件）。

## 用户级 models.json（运行参数的唯一来源）

```json
{
  "providers": {
    "deepseek": {
      "baseUrl": "https://api.deepseek.com",
      "apiKey": "sk-…",
      "models": [
        { "id": "deepseek-flash", "name": "DeepSeek Flash", "contextWindow": 500000, "maxTokens": 8192, "reasoning_effort": "none" }
      ]
    }
  }
}
```

| 字段 | 行为 |
|---|---|
| provider `baseUrl` | 请求端点（必填；缺了报错会提示官方端点） |
| provider `apiKey` | 请求密钥（必填；不进仓库） |
| `models[].id` | 要用的模型；**必须在随包目录里已适配**（没适配的 id 直接报错——codelotte 只支持自己适配过的模型） |
| `models[].name` | 可选，显示名（TUI 状态栏）；不写用随包的 |
| `models[].contextWindow` | 可选，≤ 随包默认值（官方上限；只能下调不能上调）；影响 TUI 状态栏的上下文占用百分比（真正的压缩阈值是票据 12） |
| `models[].maxTokens` | 可选，≤ 随包默认值；**进请求体 `max_tokens`** |
| `models[].reasoning_effort` | 可选，默认随包的 `high`：**直接进请求体**（`none` 关闭思考——不产生思考内容、不落盘、不花这笔 token；其余档位 `minimal/low/medium/high/xhigh/max/ultra` 开启思考并控制强度，接口按官方映射表自行折算）。展示总是跟随开关：开启时思考既落盘又展示（`-p` 打 stderr、TUI 暗色块），**没有单独的展示配置** |

- 其他多写的字段（计费规则、价格、vision 等）一律**忽略**——钱的事以随包文件为准。
- 配置整体校验（所有 provider、所有条目）：一处写坏就报错并指出位置，不半可用。
- 随包默认值：两个 DeepSeek 模型都是 `contextWindow=1048576`、`maxTokens=393216`（官方上限）、`reasoning_effort=high`（官方默认档）；官方调窗口时改随包文件即可，上限规则自洽。

## 随包 models.json（计费 / 展示 / 上限）

```json
{
  "schema": "models/v2",
  "providers": {
    "deepseek": {
      "baseUrl": "https://api.deepseek.com",
      "currency": "CNY",
      "timezone": {"utcOffsetHours": 8},
      "peakDays": "weekdays",
      "peakWindows": [{"start": "09:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
      "offPeakMultiplier": 0.5,
      "holidays": ["2026-10-01"],
      "priceNote": "官方定价页 …（2026-10-16 核对）",
      "models": [
        {
          "id": "deepseek-flash",
          "name": "DeepSeek Flash",
          "contextWindow": 1048576,
          "maxTokens": 393216,
          "reasoning_effort": "high",
          "vision": true,
          "peakPricePerMillion": {"inputCacheHit": 0.04, "inputCacheMiss": 2, "output": 8}
        }
      ]
    }
  }
}
```

每个字段的去向（"不允许有遗漏"）：`baseUrl` → 用户文件缺端点时的报错提示；`currency` →
金额符号与账单文案；`timezone`/`peakDays`/`peakWindows`/`offPeakMultiplier`/`holidays` →
峰谷判定与计价（纯函数）；`priceNote` → 导出账单脚注的出处；`models[].id` → 与用户文件 join
的键 + 价目查表键；`name` → 展示名默认；`reasoning_effort` → 思考强度默认档；
`contextWindow`/`maxTokens` → 默认值与上限。
**不参与逻辑、供开发人员阅读的标记**（代码不解析，写在这里是记录）：`schema`、`vision`、
`priceUnit`、`holidaysNote`（节假日的法条出处与调休口径说明）。

## 取值链（谁盖谁）

```
命令行参数（如 --allow）          ← 最高：覆盖运行行为（权限规则）
  ↓
~/.codelotte/settings.json        ← 选择：用哪个 provider、哪个模型、bash 超时
  ↓
~/.codelotte/models.json          ← 取值：端点、密钥、模型条目（窗口/输出/名字/思考强度）
  ↓
随包目录（providers/models.json）  ← 窗口/输出：默认值兼上限（只能下调）；展示名、思考强度：纯默认值（可自由覆盖）
  ↓
缺了就报错指路                     ← 没有替你猜的默认（provider/模型/端点/密钥）
```

settings 与 models **不是同一字段的两层**（字段不相交）：settings 只做"选谁"，models 提供
"用什么"。真正发生覆盖的只有一处：用户模型条目 vs 随包默认值（有界覆盖）。

**没有任何环境变量来源**：`.env` 文件层、settings 的 `env` 包层、`CODELOTTE_*` 环境变量
全部移除（2026-10-17）。任意第三方环境变量（如代理 `HTTPS_PROXY`）仍照常来自 shell/CI——
那是进程环境的事，不进本项目配置。

## 更新提示（lastChangelogVersion）

`CHANGELOG.md` 在仓库根，每条以 `## [x.y.z]` 开头。**只在真的开始一次运行（`-p` / TUI）时处理**：
落后当前版本 → 打印更新条目（`-p` 走 stderr，TUI 挂进对话流）并写回版本号；首次运行（无字段）
→ 静默记下当前版本；一致 → 不动（幂等）；**回退 → 也不动**（跑过新版本再回到旧版，水位不能被
拉低，否则再升级会重放整段更新）；认不出的值（手误/乱码）→ 修正为当前版本（唯一例外，自愈）。
只读命令（`export`/`--resume`/`trust`…）不改用户文件。写回是读-改-写（保留其他键）+ 临时文件
原子替换（写一半被打断不会留下截断的 settings.json），没有 settings.json 不凭空创建。

## 写入方式

```bash
# 权限规则（permissions.json 由工具维护）
codelotte allow|ask|deny <规则>… [--project]

# settings.json / models.json：手动编辑（lastChangelogVersion 由启动时自动维护）
```
