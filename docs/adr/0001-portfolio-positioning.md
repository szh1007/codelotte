# 作品定位：可验证的 harness 工程（实验报告形态）

Status: accepted (2026-10-13)

codelotte 放弃功能广度路线，深度押四个差异化窗口——评测闭环（D1）、权限/沙箱治理（D2）、上下文压缩质量（D4）、轨迹级失败归因（D5）；以「实验报告 + 真实自用数据」形态交付：任务集 / baseline / 干预 / 指标 / 轨迹 / 复现脚本，叙事是「我把 X 的成本/成功率/失败率从 A 改到 B，并知道为什么」，而非「我实现了 X」。依据：生态调研显示四工具 agent 循环已被教程彻底商品化、信号值 ≈ 0，而招聘方公开筛选标准点名 evals 与 attribution 能力（docs/research/portfolio-differentiation.md）。dogfood 驱动是其中一部分：开发期起用 codelotte 开发 codelotte。

被否备选：功能广度演示（同质化，面试官一眼识破）；多 agent 编排炫技（招聘方公开不建议作为首个作品）。
