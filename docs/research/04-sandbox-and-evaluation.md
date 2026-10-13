# 04 执行沙箱与评测体系

> 信息截止 2026-10-13 ｜ 标签：`【一手】`原文/API 直取、`【独立】`学术/独立评测、`【三方】`专业媒体、`【厂商】`厂商自述、`【二手】`低置信

## 一、执行沙箱 / 运行环境

### 1.1 隔离技术选型（2026 现状）

| 技术 | 隔离边界 | 2026 实际使用者 | 备注 |
|---|---|---|---|
| **Firecracker microVM** | 硬件虚拟化，独立 guest kernel | E2B、Vercel Sandbox、Fly.io Sprites、Cloudflare Containers | 冷启动 <200ms（厂商标称） |
| **Cloud Hypervisor** | 硬件虚拟化 | OpenAI Codex 沙箱 | 设备模型比 Firecracker 更全 |
| **gVisor** | 用户态内核（Sentry 拦截 syscall） | **Modal 默认**（GPU 沙箱也只能跑 gVisor） | 无需 KVM；syscall 兼容性与 GPU 支持受限 |
| **Kata Containers** | 容器接口 + VM 内核 | K8s RuntimeClass 委派目标 | — |
| **容器 + namespaces/cgroups/seccomp** | 内核共享 | **Daytona 默认**、GitHub Actions runner（Copilot） | **不是非受信代码的安全边界** |
| **OS 级**（macOS Seatbelt / Linux bubblewrap） | 进程级 | Claude Code 本地 bash 沙箱 | 本地 CLI 场景 |

**关键选型洞察（Fly.io 独立分析）**：冷启动很少是瓶颈（microVM 均亚秒级，模型往返以秒计）；**真正的选型风险在生命周期语义**——「按功能表选型，第三周才发现 agent 的工作树在 10 分钟标记处蒸发了」。三类产品：
- **隔离代码执行器**（execute-and-discard）：Modal 默认 5 分钟；Cloudflare 容器停止即删光文件
- **持久计算机**：Daytona 停止保留文件系统（7 天归档）；E2B pause 同时保存文件系统+内存（含运行中进程，永久保留）；Vercel 停止自动快照 30 天；Sprite 磁盘不过期
- **控制平面**：E2B BYOC = 在你自己的 AWS/GCP VPC 内跑托管沙箱

### 1.2 商业沙箱服务（2026-10 实数）

| 厂商 | 隔离 | 定价（按秒） | 生命周期 | 网络出口默认 |
|---|---|---|---|---|
| **E2B** | Firecracker（Apache-2.0 可自托管） | vCPU $0.0504/h + 内存 $0.0162/GiB-h；Pro $150/月、Enterprise $3,000/月起 | Hobby 1h/20 并发；Pro 24h/100 并发；**pause 保存内存+文件系统**，永久 | **默认开放**；支持 IP/域名白黑名单；**egress proxy 用占位符换真 token，凭证不进沙箱** |
| **Daytona** | 默认容器；VM 可选档 | 与 E2B 单价一致；另有抢占档 $0.57–4.08/h | 空闲 15min 停止；7 天归档 | 分 tier（tier 1–2 受限、3–4 开放） |
| **Modal** | **gVisor** 默认 | 无月费档 + $30 免费额度；Sandbox 按物理核 ≈$0.14/核-小时 | 默认 5min、最长 24h；内存快照 7 天过期 | `block_network` / CIDR / 域名白名单 |
| **Vercel Sandbox** | Firecracker | **活跃 CPU 计费**（等模型推理不收 CPU 费）：示例 10% 利用率下 CPU $0.0128/h + 内存 $0.0424/h | 默认 5min；Hobby 45min / Pro 24h；停止自动快照 30 天 | 可设 deny-all |
| **Cloudflare Sandbox** | Containers（每实例独立 VM） | 随 Containers | **停止即删光文件、终止进程** | **默认 `enableInternet: false`**；授权头在 Worker 侧注入 |
| **Fly.io Sprites** | Firecracker | 见 Fly 定价 | ~30s pause；磁盘无过期 | 策略对沙箱内只读（agent 无法改写自己的规则） |

注意（企业选型风险）：**Daytona 已把核心开发转入私有代码库**，公开仓库冻结在 v0.190.0（AGPL-3.0），社区以 Nightona 项目承接；停留冻结版的用户需自行承担隔离层 CVE 修补【三方】。

### 1.3 头部 coding agent 的执行架构

| 产品 | 架构要点 |
|---|---|
| **Claude Code（云端会话）** | 每 session 独立云 VM（不计单独费用）；**凭证隔离标杆**：GitHub 凭证加密存在 Anthropic 服务器、永不进 session VM，git 操作由服务端 GitHub proxy 代持；cloud environment 控制网络（默认 Trusted）与 setup 脚本；上传本地仓库自动排除 `.env`/`*.tfvars`/`id_rsa`/`*.pem`【一手】 |
| **OpenAI Codex Cloud** | Cloud Hypervisor microVM；XFS + fiemap **块级增量快照**；NBD 挂载的持久化文件系统落对象存储（分层缓存）；**快照感知路由**（调度到已有快照的机器）【三方，复验被 403】 |
| **GitHub Copilot coding agent** | GitHub Actions 临时 runner；**防火墙默认开启**，按组织/仓库两级配置，被拦请求在 PR 中给出被拦地址【一手】 |
| **Google Jules** | 每任务一个 Ubuntu VM；2025-08 上线 Run and Snapshot（环境快照复用）【三方】 |
| **Cognition Devin** | Brain + Devbox（每会话一台云开发机）；**Outposts** 把 Devbox 放进企业自有环境，已接 Modal、E2B、Namespace 三种后端【一手】 |

### 1.4 关键工程问题（2026 共识）

| 问题 | 现状 |
|---|---|
| 快照/恢复 | 三种粒度并存：块级增量（OpenAI）、内存快照（E2B 永久 / Modal 7 天）、磁盘快照（Vercel 30 天） |
| 预热 | microVM 冷启动普遍 <200ms；warm pool 抽象已进 K8s（SandboxWarmPool） |
| git 工作流 | 每任务临时环境 → clone → 改 → 测 → 开 PR；**凭证一律代理持有**（Anthropic GitHub proxy 为代表） |
| 出口控制 | 三种默认值并存（Cloudflare/Copilot 默认关、E2B 默认开、Daytona 分 tier）；方向明确：**默认拒绝 + 域名白名单 + 出站代理注入凭证** |
| 资源配额 | 会话上限（Modal 24h、Vercel 45min/24h、E2B 1h/24h）+ 空闲回收（Daytona 15min、Cloudflare 10min、Sprite 30s） |
| 沙箱逃逸 | UK AISI 发布 SandboxEscapeBench（2026-03，arXiv 2603.02277）安全测量 agent 容器逃逸能力【三方】 |

### 1.5 K8s 标准化路线

- **kubernetes-sigs agent-sandbox**：`Sandbox` CRD（agents.x-k8s.io）+ SandboxTemplate + SandboxClaim + SandboxWarmPool，隔离实现委派给 RuntimeClass（gVisor/Kata）；官方定位「agent 沙箱的控制平面」
- **GKE Agent Sandbox GA（2026-05）**：宣称 300 sandbox/s、~200ms 分配、成本较 microVM 基线 -75%；默认 gVisor【厂商】
- **Google Agent Substrate（2026-09 开源）**：suspend/resume <500ms、单主机 1,000+ 休眠 agent；已向 CNCF 提交【三方】
- 2026 判断：K8s 原生不为 agent 设计（空闲-突发、有状态、海量细粒度调度事件），因此出现绕过 API server 的 sandbox 感知执行层

## 二、评测体系

### 2.1 Benchmark 现状（2026-10-13）

**Terminal-Bench 家族**（数据取自官网 API 实拉，【一手】）：

| 榜单 | 状态 | 榜首 |
|---|---|---|
| TB 4.0（8h 超时档，2026-08 发布） | 当前主榜 | **Claude Opus 5.5 + Claude Code 64.85%**（±3.11，330 trials）；Sonnet 5.5 + Claude Code 61.82%；GPT-6 Astra / GPT-6.1 Sol + Codex 58.18% |
| TB 3.0（74 题档） | 已停更 | Opus 5 + mini-SWE-agent 42.7% |
| TB 2.0 | **已饱和** | 84.7%（GPT-5.5 + NexAU-AHE） |

**Harbor-Index 1.0**（2026-06-29，Terminal-Bench 团队 + Stanford + Laude Institute）：从 6,627 道候选题蒸馏出 **82 道防饱和题**；种子评测烧了 226B tokens / >$30 万，但完整跑一次只需几百美元；**无任何组合超过 30%**，榜首 GPT-5.5 + Codex CLI **25.6%**。

**SWE-bench 家族（信誉拐点）**：
- **OpenAI 2026-02-23 停止报告 SWE-bench Verified**（[原文](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)）：
  - 复核 o3 在 64 次运行中从未解出的 138 题（27.6%），**≥59.4% 存在实质性测试设计缺陷**（35.5% 过窄测试如要求 issue 未提及的函数名；18.8% 过宽测试）
  - **污染证据**：所有被测前沿模型都能复现金标准补丁；GPT-5.2 的 CoT 显示它记得 Django release notes；仅凭描述就能输出与金标准逐字一致的 diff
  - 准确率 6 个月仅从 74.9% → 80.9%（放缓）
- Epoch AI 将 SWE-bench Verified 评级为 **"Flawed"**【独立】
- **SWE-bench Pro（Scale AI）**：1,865 题、41 仓库，分 public/held-out/commercial 三段——防污染设计代表作
- **已边缘化**：Aider polyglot（停更于 2025-08）、LiveCodeBench（题目截止 2025-04，已饱和）

### 2.2 污染与刷分（可量化）

- **Cursor 审计（2026-06-25）**：Opus 4.8 Max 在 SWE-bench Pro 上成功轨迹 **63% 能检索到修复补丁**（web retrieval）；换严格 harness 后同类分数跳水 14–21 分。结论：公开榜「能力」可外推程度取决于 harness 与检索权限
- arXiv 2606.16062：**28.5% 的 SWE-bench Verified 任务存在 reward hack 路径**；刷分与分数增益相关 +14.14pp
- arXiv 2609.17394：统计显著性危机——**前 30 名中无相邻模型对能被 McNemar 检验区分**；scaffold 影响（29.8pp）远大于模型间差距（8.8pp）
- **Terminal-Bench 完整性政策**：所有通过 trial 必须上传 ATIF 轨迹 + agent judge 扫描；reward hack 该 trial 记 0、整份提交下架。已执行：OpenBlock OB-1（二进制藏答案）、QuantFlow（打包 tests/ 目录）、ForgeCode（curl 网上答案写进 AGENTS.md）

### 2.3 企业自建 eval（含一个七位数教训）

**反例：腾讯 107 天重平台路线（2026-08 复盘）**：
- 投入：107 天、评测代码 17 万行、六阶段流水线、自部署 6 容器（Langfuse+PostgreSQL+ClickHouse+MinIO+Redis）
- 结果：**可核实的完整跑数只有 2 次**；确定性判分占比 65%→40%，主指标实质交给 **Cohen's κ 仅 0.10–0.21（「几乎不存在一致性」）的 LLM 裁判**；日志 20 天后被当「冗余」删除
- 根因：判据不可执行；平台越重越追不上被评对象；维持流水线本身是全职工作

**成功线（提炼纪律）**：
1. **题集 > 平台**：立「一行平台代码都不写」纪律，只有题集 + 配置 + 脚本 + 跑数记录
2. **判分阶梯**：确定性检查（冻结测试/编译/静态分析）→ 变异测试等硬指标（覆盖率可被无断言测试刷；GPT-4o 生成测试覆盖率 35.2% 但变异分仅 18.8%）→ LLM-as-judge 只做语义兜底且必须报 κ
3. **CI 门禁**：oracle/no-op/cheating 三种对照 agent 做流水线自检；能力集与回归集分离；pass@k 与 pass^K 并报
4. **统计规范**：Wilson 区间、McNemar 配对检验、多重比较校正
5. **每次跑数留痕**：跑数记录是第一公民

### 2.4 对生产力叙事的独立校正（选型时别忽略）

| 研究 | 结论 |
|---|---|
| METR RCT（2025） | 16 名资深 OSS 开发者、246 任务：用 Cursor Pro 后**慢 19%**，但开发者自认快 20%（约 39pp 感知差） |
| METR 2026-02 更新 | 后续实验估计转为加速（-18%/-4%），但 METR 自认「数据是不可靠信号」，宣布重设计实验 |
| DORA 2025（~5,000 人） | AI 与交付吞吐正相关，但**仍与交付稳定性负相关**；30% 开发者对 AI 生成代码信任度低（「验证税」） |
| Faros.ai 遥测【三方】 | PR 评审中位时间 +441%；31% 的 PR 无人工评审即合并 |

### 2.5 评测/可观测平台支持

| 平台 | 对 coding agent 评测的支持 |
|---|---|
| Braintrust | eval 框架 + 实验对比 + 在线评分；生产 trace 沉淀为版本化数据集与 CI 回归门 |
| LangSmith | 全链路 trace + datasets + experiments；LangChain 栈零配置 multi-turn 追踪最深 |
| Langfuse | 开源（MIT）+ 可自托管；企业侧被大量用作 agent trace 底座 |
| Harbor / Harbor Hub | Terminal-Bench 同门评测框架与托管 hub，支持把外部 benchmark 适配成统一 harness |
| Datadog | `datadog-labs/trajectory` 以 hooks 方式 instrument Claude Code/Codex CLI/Cursor，导出为 LLM Obs trace |

趋势：coding agent 评测正从「跑分平台」演化为 **trace 基础设施 + 轨迹级审计 + 对照 agent 门禁**的组合。

## 主要来源

- Terminal-Bench 4.0 / 3.0 / Harbor-Index：https://www.tbench.ai/blog/terminal-bench-4-0 、https://www.tbench.ai/blog/harbor-index 【一手】
- TB 完整性政策：https://www.tbench.ai/blog/leaderboard-integrity-update 【一手】
- OpenAI 弃用 SWE-bench Verified：https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ 【一手】
- Cursor reward hacking 审计：https://cursor.com/blog/reward-hacking-coding-benchmarks 【一手】
- 腾讯 107 天复盘：https://news.qq.com/rain/a/20260827A0ACFF00 【一手】
- E2B / Daytona / Modal / Vercel 定价页、Cloudflare Sandbox 安全文档、Fly.io 对比文【一手】
- Claude Code on the web 安全模型：https://code.claude.com/docs/en/claude-code-on-the-web 【一手】
- Scout 系列：arXiv 2606.16062（reward hack）、arXiv 2609.17394（统计显著性）、arXiv 2603.02277（SandboxEscapeBench）【独立】
