# 10: codelotte 专用沙箱镜像 + git

**What to build:** 新增 Dockerfile：基于 `python:3.13-slim`，装 git、curl、wget、ca-certificates、ripgrep、fd-find、jq、yq、unzip、less、procps、build-essential、sqlite3、file、Node 22、uv；不装 Go/Rust。`/etc/gitconfig` 写 codelotte 身份、`safe.directory /workspace`、`autocrlf=false`、`init.defaultBranch=main`。POSIX 上容器以宿主 UID:GID 运行（Windows 保持默认），避免 root 属主的 `.git`。`settings.json` 新增 `sandbox.image`；`codelotte sandbox build`；GHCR tag 绑定版本；CI PR build、tag push，并在 Linux runner 跑 `-m docker`。仅保证本地 git；远程 git 在 `--network none` 下不可用，错误提示 `--no-sandbox`。

🗣 大白话：沙箱里终于有 git 和日常开发工具；镜像固定版本、能本地重建、CI 会真的跑一遍容器测试。

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Dockerfile + 版本 tag + GHCR
- [ ] `sandbox.image` 配置；`codelotte sandbox build`
- [ ] 非 root 用户映射（POSIX）与 Windows 兼容
- [ ] git 本地操作测试：status/diff/log/add/commit/branch
- [ ] 无宿主 git 凭据；`.git` 属主正确
- [ ] CI build + `-m docker` 集成测试
- [ ] 远程 git 失败提示与文档
- [ ] README/SECURITY/SPEC 更新
