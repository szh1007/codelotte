# 09: 权限层（规则 + 审批 + trust）

**What to build:** 在"模型请求执行"与"真实执行"之间加一道规则闸门。规则语法 `tool(pattern)`（如 `bash(git diff *)`、`read(src/**)`），判定三档：allow / ask / deny，冲突时 deny > ask > allow。**破坏性动词保护**：`rm -rf`、`push --force`、`reset --hard`、`chmod -R`、`clean -fd` 等模式不允许被通配规则（如 `bash(*)`）自动放行——只能精确规则或逐次审批。规则来源分层：命令行 > 项目级 > 用户级；**项目级规则首次生效需"信任确认"**（防打开陌生仓库即被其规则劫持）。审批四档：本次 / 本会话 / 始终（写用户级规则文件，绝不写进项目）/ 拒绝。无头模式（`-p`）fail-closed：未授权一律拒绝。每次判定作为记录写入会话（审计可查，HTML 导出可见）。

🗣 大白话：门禁系统——哪些事随便做、哪些要问你、哪些永远不行；陌生仓库要先"验明正身"；你只说一次"这个命令以后放行"，它也只记在你自己名下，不污染项目。

**Blocked by:** 04（write / edit / bash 工具 + 本地执行器）

**Status:** done（2026-10-16；自动化全绿；真机 TUI 审批交互 2026-10-17 已验，含同日与票据 10 Docker 沙箱联训，见文末）

- [x] 规则匹配单元测试完整：三档优先级、通配与精确规则、破坏性动词不被通配放行
- [x] TUI 审批四档交互可用；「始终允许」写入用户级规则文件（有测试证明不写项目文件）
- [x] 未信任仓库的项目级规则被忽略且有提示；执行一次信任确认后规则生效（`codelotte trust`）
- [x] 无头模式未授权操作一律拒绝（fail-closed），原因写入会话
- [x] 每次判定落会话（规则命中或人工审批），HTML 导出中可见

## 实施记录（2026-10-16）

- **判定语义（对 §G 两条看似冲突句式的解读，写明在此）**：三档判定**全局合并**（deny > ask > allow，SPEC 原文"冲突时 deny > ask > allow"），来源分层决定**信任门槛与审计出处**——"任一来源的 deny 不可被更低层级放行"落实为更强的一刀：deny 不被**任何**来源放行（含 CLI，宁严勿松；恶意仓库的通配 allow 压不过用户文件里的 deny，测试钉死）。无规则命中默认 **ask**（"未命中 allow 的调用一律拒绝"是 headless fail-closed 的前提）。
- **规则语法**（[permissions.py](../../src/codelotte/permissions.py)）：`tool(pattern)` 或裸 `tool`；pattern 是 shell 风格通配（`*` 跨路径分隔符）；匹配主体 = 工具的主参数（bash→command，read/write/edit→path）。规则文件每行 `[allow|ask|deny] 规则`（缺省 allow、# 注释、坏行跳过并汇报不静默）；CLI `--allow/--ask/--deny` 可重复。
- **破坏性动词保护**：独立扫描器对**整条命令**逐模式扫描（`rm` 的 r+f 各种写法、`git push --force/-f`、`reset --hard`、`chmod -R`、`clean -fd`、`mkfs`/`dd of=/dev`、关机重启——藏在中段也抓）；通配 allow 对它一律不适用（跳过该规则 → 落到 ask），精确规则/逐次审批仍可放行（SPEC §G 的"只能精确规则或逐次审批"）。
- **信任**：`codelotte trust` 子命令（显示规则文件内容 → y/N 确认 → 写 `~/.codelotte/trusted`）；未信任时项目规则被忽略——headless 打 stderr 提示、TUI 在对话流顶部挂提示条（复用 §G 的"提示"验收）。信任表按**目录**记录（Windows 大小写不敏感归一）。
- **审批四档（TUI）**：`ApprovalScreen` 弹层（y/s/a/n + 按钮，Esc=拒绝）；「本会话」加**精确规则**（通配字符转义，`echo *` 不会变成通配）、「始终」同名规则**写用户级文件**（多行命令降级为本会话，避免撑破规则文件）；本次/拒绝不留规则。弹层上按 Ctrl+C = 该调用拒绝 + 回合取消（弹层稳妥关闭，测试覆盖）。审批者以回调注入 loop（`agent.approver`）——无头没有审批者，ask 一律 fail-closed。
- **审计**：每次放行/拒绝都落一条 `permission` 记录（toolCallId 关联调用、subject、verdict、命中规则与来源、人工决策、allowed、一句话 reason——与回传模型的错误文本同源）；**记录先于执行**。拒绝以工具错误回传模型让它换做法（SPEC §D 口径），不是异常。导出 HTML/Markdown 均渲染权限标记（⛔ 红 / 🔓 中性，票据 08 的标记层就此补上第一类真实标记）。
- 既有无头 e2e 全部改用 `--allow read/write/edit/bash` 显式授权（fail-closed 的必然要求——测试从"默认能跑"改为"显式放行才跑"，这本身就是验收的活证明）。测试：新增 40 项（匹配矩阵/破坏性清单参数化 14 例/来源信任/审批落规则/组件路径 fail-closed-审批-会话规则-e2e 与导出可见/TUI 弹层四档与 Ctrl+C/trust CLI）。**自动化总 269 项全绿**；ruff / pyright 干净。
- **两轴代码审查（Standards / Spec）后的修正——Spec 轴对抗实测抓到 4 条可复现的绕过/越权路径，全部修复并加回归测试**：
  ① **自证信任整链绕过**：仓库自带 `.env`（`CODELOTTE_HOME=./.evil`）+ `.evil` 里一份相对路径 `trusted` 条目（"."）→ 打开即"已信任"，项目规则直接生效。修：项目级 `.env` 不得设置 `CODELOTTE_HOME`（信任锚只认用户环境；`load_env_files` 加项目级禁键表）+ 信任表只认**绝对路径**条目。e2e 回归：完整复刻攻击链，断言规则被忽略、提示可见、`rm -rf` 未被放行。（2026-10-17 后续：`.env` 层与 `CODELOTTE_HOME` 均已整体移除——用户级目录固定为系统家目录，这条攻击链在结构上不再可能。）
  ② **裸工具规则击穿破坏性保护**：`--allow bash`（与 `allow_all`——已改名 `allow_builtin_tools`，名字如实）让 `rm -rf /` 直接放行——裸规则是最宽的通配。修：保护对 `pattern=None` 同样生效。
  ③ **「始终允许」写出更宽的规则**：subject 含 `\r` 等断行控制符时写出的行会裂成多条（实测 `echo a\rallow bash\r# ` 落成裸 `allow bash`）；无主参数时直接写裸工具规则。修：按 `splitlines()` 判多行（覆盖全部断行字符，不只 `\n`）+ NUL 拒写 + 无主参数不落规则（降级本次）+ 通知。
  ④ **扫描器漏抓 7 种形态**（`rm dir1 -rf`、`rm -f a -r b`、`git -C x push --force`、`chmod -cR`、`chmod u+w -R`、`rm --rec -f` 等）：重写为"命令词到分隔符整段收集旗标 + GNU 长旗标前缀宽认"；参数化回归 23 例。
  ⑤ 附加：审批中被 Ctrl+C 会留审计断链（有 tool_call 无 permission）→ 取消路径补记 `permission`（reason=审批未完成）；`_normalized` 只在 Windows 大小写归一（Linux/macOS 上 trust `~/proj` 不再连带 `~/PROJ`）。Standards 轴的清理：扫描器旗标解析去重、cli 三参数结块收成 `rules` 一次解析、`_close_approval` 收拢、BINDINGS 字面量注释、去死守卫。
- 测试：审查轮 +17（攻击链 e2e 1、破坏形态参数化 23 例、裸规则/控制符/NUL/无主参数/相对信任条目各 1、项目 .env 信任锚 1、TUI `s` 档与取消审计链等）。**自动化总 286 项全绿**；ruff / pyright 干净。

## 规则文件格式与写入子命令（2026-10-17，用户提出）

- **规则文件改为 JSON**（用户指定形状，取代最初的行式文本）：
  ```json
  {"allow": ["read", "bash(git diff*)"], "ask": ["bash(git push*)"], "deny": ["bash(curl*)"]}
  ```
  读取纪律不变：整份坏 JSON → 忽略全部规则（安全方向）并汇报；单条坏规则/未知键 → 跳过并汇报，绝不静默。手编或用子命令写都行。
- **新增三个写入子命令**（把"永久"从"手动编辑文件/TUI 按 a"扩展为命令行直达）：
  `codelotte allow|ask|deny <规则>…`——默认写**用户级** `~/.codelotte/permissions.json`；`--project` 写本项目 `.codelotte/permissions.json` 并提示需 `codelotte trust`。读-改-写 JSON、不重复追加、保留文件中其他键、**损坏文件拒绝写入**（报"先手动修好"，绝不覆盖）；规则先整体校验、坏一条一条都不写。TUI「始终允许」与它共用同一个 `append_rules`，行为一致。
- 测试 +12（JSON 读取矩阵/坏 JSON/坏条目/未知键、append 去重与保键、五个 CLI 用例含 --project/坏规则/损坏文件拒写）；**自动化总 293 项全绿**；ruff / pyright 干净。

## 真机验证记录

**2026-10-17 用户真机通过（TUI 四档审批手感）**：两个真实会话（`~/.codelotte/sessions/--D--__WorkSpace__-codelotte--/20261016T2210…、2211…`，审计可查）覆盖了闸门四条路径——

- **命中规则自动放行**：`ls -la …` / `ls -R | head -100` 由用户级 `bash(ls*)` 放行，`permission` 记录带命中规则与来源；用户规则里的裸 `read` 同样直通（PLAN.md / CHANGELOG.md）。
- **ask 弹层「始终允许」**：`pwd; ls -la` 审批后落 `decision=always, allowed=true`，且用户级 `permissions.json` **精确新增** `bash(pwd; ls -la)`——审批写文件与 `codelotte allow` 子命令同源（`append_rules`）在真机对齐，不动项目文件。
- **ask 弹层「拒绝」**：`read CONTEXT.md` 被拒（`decision=deny, allowed=false`），以工具错误回传模型、回合继续，审计无断链。
- 两个会话的 `permission` 记录数 = `tool_call` 记录数（3/3、4/4）：**记录先于执行**在真机无遗漏。

**与票据 10 的 Docker 沙箱联训（2026-10-17 真机已验）**：真实 TUI 会话
`~/.codelotte/sessions/--D--__WorkSpace__-codelotte--/20261017T095217Z_9534b0a6.jsonl`
覆盖了「权限判定 → Docker 执行 → 审计 → 清理」整链——

- 用户级规则 `bash(ls*)` 命中直通：`permission` 记录 `verdict=allow, allowed=true,
  source=user, rule="bash(ls*)"`，reason 为「规则放行（bash(ls*)）」。
- 同一次调用在 Docker 沙箱执行：`tool_call` 与 `tool_result` 均为 `env=docker`，
  `ls -la` 结果 `ok=true`——权限层放行的对象和实际执行环境在审计里对得上。
- 会话退出后 `docker ps -a --filter label=codelotte.sandbox=true` 为空：容器随会话清理，
  权限审计没有跟着留下长驻容器。

本轮实测的是「规则 allow 直通 Docker」；ask 弹层与 deny 两档沿用同日此前的 TUI 真机记录
（上文 3/3、4/4 审计链）与自动化覆盖，未在本轮重放。结论：票据 09 的判定/审批与票据 10
的执行/清理在同一真实会话中无断链。
