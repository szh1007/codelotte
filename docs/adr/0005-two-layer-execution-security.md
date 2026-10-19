# 执行安全：权限层与沙箱层相互独立（沙箱默认 Docker 长驻容器）

Status: accepted (2026-10-13)

安全模型刻意分两层且互不依赖：

- **权限层**：工具级 + 命令模式级 allow / ask / deny 规则；破坏性动词禁止通配；headless 模式 fail-closed。它决定「是否允许」。
- **沙箱层**：每会话一个 Docker 长驻容器 + `docker exec` 复用；bind mount 工作区；网络默认 deny + 域名白名单。它限制「实际后果」。

任一层的失效不导致全盘失守（defense in depth）。设计立场是「审批弹窗不是安全边界」。

沙箱默认 Docker 的原因：

- 开发机是 Windows，OS 级隔离（seatbelt / bubblewrap）不可用。
- Docker 是唯一能落地的强隔离路径。
- `--no-sandbox` 本地模式仅是显式逃生门。

死循环三层防御（工具层重复/无进展检测 → 推理层迭代熔断 → 规划层约束重注入）作为一等模块。

被否备选：纯权限层（无沙箱——教程式 `subprocess(shell=True)` 的风险面）、纯沙箱（无规则层——无法表达「同工具不同参数不同授权」）。
