# 10: Docker 沙箱

**What to build:** 把 bash 命令的执行从宿主机搬到 Docker 容器。

- 每会话一个长驻容器（命令用 `docker exec` 复用，避免每条命令冷启动）。
- 工作目录读写挂载，**家目录不进容器**（宿主的密钥、`.ssh`、`.env` 永远看不见）。
- 网络默认拒绝（`--network none`），被拦请求以明确错误回传模型。
- 容器有内存/CPU/超时限额（超时杀死进程组）。
- `--no-sandbox` 为显式逃生门（打印风险警告，且该回合每次执行在会话中标记 `env=local` 供审计）。
- 容器生命周期跟随会话（启动/复用/清理）。

🗣 大白话：把 agent 请进"防爆箱"里干活——就算它被骗着执行了危险命令，损失也被关在盒子里，碰不到你的真实文件系统和密钥。

**Blocked by:** 04（write / edit / bash 工具 + 本地执行器）

**Status:** done（2026-10-17；单元 11 + 集成 8 全绿；默认镜像 `python:3.13-slim` 真机跑通，
见文末实施记录）

- [x] 容器生命周期跟随会话：启动、命令复用、会话结束清理（有集成测试）
- [x] 宿主敏感路径（家目录、.ssh、.env）在容器内不可见（测试证明）
- [x] 网络默认拒绝；被拦请求回传明确错误信息
- [x] 内存/CPU/超时限额生效；超时时进程组被整体杀死
- [x] `--no-sandbox` 下执行在会话中标记 `env=local` 且启动时提示风险
- [x] 沙箱集成测试为独立套件（本地 CI 可选执行，不阻塞冒烟）

## 实施记录（2026-10-17）

**实现**：`sandbox/docker.py` 的 `DockerExecutor`（默认），`LocalExecutor` 退为 `--no-sandbox`
逃生门。容器惰性启动（第一次 bash 才 `docker run`），`sleep infinity` 作主进程，后续命令
`docker exec` 复用；`close()` 在 `-p`/TUI 会话结束时由 `cli` 统一调用（`docker rm -f`）。

**容器参数即安全契约**（改动等于改边界，单元测试钉死 argv）：
`--network none`、`--read-only` + 仅 `/tmp` tmpfs、工作区是唯一 bind mount（家目录不挂）、
`--memory/--memory-swap` 同值、`--cpus`、`--pids-limit`、`HOME=/tmp`；
`--label codelotte.sandbox=true` 便于清理遗留容器。

**超时**：`docker exec` 里跑 `timeout --signal=KILL <秒> bash -c <命令>`，杀的是容器内的
整个进程组。真机踩坑：KILL 模式下 `timeout` 自己也在被杀组里，`docker exec` 返回 **137**
而不是 124（首次集成测试实测）——判定改为「124，或 137 且已到点」；不到点的 137 视为
OOM/外部杀，不误报超时。宿主侧另有 `timeout + 10s` 兜底：容器内哨兵失灵时直接停容器。

**网络拒绝的明确错误**：`--network none` 下 Docker 只给 "Network is unreachable" /
"Temporary failure in name resolution"；执行器识别这些文本并追加一句
「网络访问被沙箱拒绝……如确需联网，请用 --no-sandbox」（模型能理解原因）。

**审计如实标记**：`Tool` 新增 `exec_env`（bash 随执行器 = docker/local；read/write/edit
始终在宿主上跑 = local）。`--no-sandbox` 下全部工具 `env=local`，启动时 `-p` 打 stderr、
TUI 进启动提示。

**验证**：
- 单元：`tests/test_docker_executor.py` 11 个——网络拒绝、根文件系统只读、容器标签/命名、
  唯一挂载、限额、容器内超时入口、网络提示、124/137 判定、close 无副作用。
- 集成：`tests/test_docker_sandbox.py` 8 个（marker `docker`，无 daemon/镜像即 skip）——
  工作区读写、容器复用、宿主家目录/.ssh/.env 不可见（在宿主家目录放唯一标记后容器内全盘
  grep）、网络拒绝提示、内存上限、CPU/内存配置、超时杀整个进程组、关闭清理。
- 默认冒烟：`uv run pytest` → `349 passed, 8 deselected`（`addopts = -m 'not docker'`，
  Docker 组是独立套件，默认不跑、也不付探测 daemon 的时间）。
- 真机命令：`uv run pytest -q -m docker tests/test_docker_sandbox.py` → `8 passed`
  （默认镜像 `python:3.13-slim`，2026-10-17 本机 Docker Desktop 实测）。
- **与票据 09 权限层联训（2026-10-17 真机）**：真实 TUI 会话
  `20261017T095217Z_9534b0a6.jsonl` 中，用户级 `bash(ls*)` 规则放行 `ls -la` →
  `tool_call`/`tool_result` 均 `env=docker`、`ok=true`；退出后按标签查询无遗留容器。
  权限判定、Docker 执行、审计与生命周期清理四段在同一会话中对齐。

**已知边界**：
- 域名白名单档未实现，本票只做默认 deny-all；SPEC §H 已同步改为"v1 只做 deny-all"。
- 只有 bash 进容器；read/write/edit 按票据 04/本票范围仍在宿主执行（权限层负责放行）。
- 镜像暂为常量（`python:3.13-slim`），未做成配置项；Docker Desktop 的文件共享需包含
  项目所在盘符。
- 容器内路径固定 `/workspace`；模型若拿 `pwd` 的绝对路径去调 read/write/edit 会失配，
  相对路径不受影响（后续若要统一路径映射，另立票据）。
- 进程被强杀（SIGKILL、关控制台、清理期间第二次 Ctrl+C）时 `--rm` 不会触发，容器会
  遗留；可按标签清理：`docker ps -aq --filter label=codelotte.sandbox=true | xargs -r docker rm -f`。
  不做启动时自动清扫——多个会话可能并发，按标签清扫会误杀别人的容器。
- 从家目录启动时家目录就是工作区，其内容（含 `.ssh`/`.env`）会被挂载；应在项目子目录启动。
