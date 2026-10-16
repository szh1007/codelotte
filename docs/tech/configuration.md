# 配置系统（事实笔记，2026-10-17 定稿）

> 对应 SPEC §M。一句话：**配置只从用户级 `~/.codelotte/` 的文件里读，没有任何环境变量来源，
> 也没有内置默认**——模型、密钥、端点缺哪个就报错指路，不替用户猜。

## 文件清单（全部在用户级 `~/.codelotte/`；目录固定为系统家目录，无重定位开关）

| 文件 | 作用 | 对应票据 |
|---|---|---|
| `settings.json` | 运行设置：模型、端点、会话目录、思考输出、bash 超时（**顶层字段直读，无包层**） | 2026-10-17 |
| `models.json` | pi 风格 `providers` 结构：provider 级 `baseUrl`/`apiKey`/计费规则（峰谷/节假日/货币）+ `models` 列表 | 07 + 2026-10-17 扩展 |
| `permissions.json` | 权限规则（`allow`/`ask`/`deny` 三个数组），见票据 09 | 09 |
| `trusted` | 已信任的项目目录表（权限规则的信任门槛） | 09 |

**为什么一律用户级**：`settings.json`/`models.json` 能决定"请求发往哪里"（baseUrl）与"用哪把钥匙"——
放进项目目录等于让陌生仓库改你的请求去向；用户级目录又是固定的系统家目录，没有任何开关能
把它重定位到别处。权限规则的项目级文件是唯一的例外，走 `codelotte trust` 显式信任。

## 优先级（同一设置多来源时的胜负）

```
命令行参数（如 -r）                ← 最高
  > settings.json 顶层字段         ← 每个设置一个字段，直接读取
  > models.json provider 条目      ← 仅 apiKey / baseUrl 两项兜底
  > 必填报错指路                    ← 没有内置默认
```

**没有任何环境变量来源（2026-10-17）**：`.env` 文件层、settings 的 `env` 包层、`CODELOTTE_*`
环境变量全部移除。任意第三方环境变量（如代理 `HTTPS_PROXY`）仍照常来自 shell/CI——那是
进程环境的事，不进本项目配置。

## settings.json

```json
{
  "model": "deepseek-flash",
  "baseUrl": "https://api.deepseek.com",
  "sessionDir": "D:/codelotte-sessions",
  "showReasoning": false,
  "commandTimeoutSeconds": 120
}
```

| 键 | 类型 | 行为 | 必填？ |
|---|---|---|---|
| `model` | string | 使用的模型 id | **是**（缺了报错指路，没有默认模型） |
| `baseUrl` | string | API 端点（可由 models.json 的 provider `baseUrl` 兜底） | 二者之一 |
| `sessionDir` | string | 会话文件目录（缺省 `~/.codelotte/sessions`） | 否 |
| `showReasoning` | bool | `-r` 的默认值（思考过程输出到 stderr） | 否（默认 false） |
| `commandTimeoutSeconds` | int | bash 工具的默认超时（1–600） | 否（默认 120） |

- 未知键：忽略并在启动时提示（不静默）；已知键类型写错：直接报错退出（配置错误要响）。
- 权限规则**不在这里**（单独 `permissions.json`，两处放同一件事会互相打架）；密钥也不在这里。

## models.json（pi 风格 providers 结构）

随包目录在 **`src/codelotte/providers/models.json`**（provider 的数据随 providers 包走），
**用户的 `~/.codelotte/models.json` 只放自己的东西**——最省事就是一把钥匙：

```json
{ "providers": { "deepseek": { "apiKey": "sk-…" } } }
```

随包文件的形状（与 pi 的 `~/.pi/agent/models.json` 同构；**DeepSeek 专属的计费规则也挂在
provider 下**——峰谷窗口、节假日、货币都是这家 provider 的事实）：

```json
{
  "schema": "models/v2",
  "providers": {
    "deepseek": {
      "baseUrl": "https://api.deepseek.com",
      "currency": "CNY",
      "timezone": { "utcOffsetHours": 8 },
      "peakDays": "weekdays",
      "peakWindows": [ { "start": "09:00", "end": "12:00" }, { "start": "14:00", "end": "18:00" } ],
      "offPeakMultiplier": 0.5,
      "holidays": ["2026-10-01"],
      "models": [
        {
          "id": "deepseek-flash",
          "name": "DeepSeek Flash",
          "contextWindow": 1048576,
          "maxTokens": 393216,
          "vision": true,
          "peakPricePerMillion": { "inputCacheHit": 0.04, "inputCacheMiss": 2, "output": 8 }
        }
      ]
    }
  }
}
```

- 合并规则：provider 逐字段合并（`baseUrl`/`apiKey`/计费规则都可单独覆盖）；provider 的
  `models` 列表**按 `id` 合并**——只写想改的字段，未写的保留随包值。
- 层级：`apiKey`/`baseUrl` 放 provider 级管全部模型，模型条目可单独覆盖。
- 没有多余的 `api` 字段：代码写死走 `/chat/completions`（第二条 wire protocol 落地时再引入）。
- **密钥只放用户级**：随包文件带密钥会被测试拦下（会进公开仓库）。
- 读取/校验纪律与随包同一套：坏 JSON/坏字段 → 启动报错（配置错误要响）。

## 写入方式

```bash
# 权限规则（permissions.json 由工具维护）
codelotte allow|ask|deny <规则>… [--project]

# models.json / settings.json：手动编辑（模型参数与设置的形状随版本演进，工具不做全量写手）
```
