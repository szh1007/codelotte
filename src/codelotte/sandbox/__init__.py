"""Sandbox 组件（SPEC §A）：命令执行的统一接口与实现。

本票只有本地执行器；Docker 实现是票据 10——届时新增一个实现模块并在装配处替换，
协议本身也要扩展（长驻容器随会话起停的生命周期，SPEC §H），工具层代码不变。
"""

from codelotte.sandbox.executor import ExecResult, Executor
from codelotte.sandbox.local import LocalExecutor

__all__ = ["ExecResult", "Executor", "LocalExecutor"]
