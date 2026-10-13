# 16: 对照组 + 控制 agent 自检

**What to build:** 给考场配两样东西。① **对照组（baseline）**：用同一个任务集分别跑 mini-swe-agent（现成的开源教学级 agent，经适配接同一个 DeepSeek 模型）与裸单轮 API（无工具循环直接作答）——用来区分"模型自身的功劳"和"我们 harness 的增量"（scaffolding tax 意识：不比较的数字没有意义）。② **控制 agent 自检**：用三种"假 agent"检验评测系统本身是否可信——oracle（总能做对，评分应 100%）、no-op（什么都不做，应 0%）、cheating（试图作弊，应被检测/记 0）。这是对"评测系统自己会不会骗人"的防线。

🗣 大白话：给考场配"对照组"和"防作弊检查"——考分要横向比较才有意义；而且先证明考场本身不瞎打分，再相信它打出的分。

**Blocked by:** 15（评测 runner）

**Status:** ready-for-agent

- [ ] mini-swe-agent 经适配跑通同任务集（同模型、同任务、同次数）
- [ ] 裸单轮 API 对照跑通
- [ ] 三种控制 agent 结果符合预期：oracle 100%、no-op 0%、cheating 被标记且记 0
- [ ] 对照报告可导出：任务级三组并列对比表（成功率/成本/时长）
