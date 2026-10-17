"""Sandbox 组件（SPEC §A）：命令执行的统一接口与实现。

默认 DockerExecutor（票据 10：每会话一个长驻容器；--no-sandbox 时退回 LocalExecutor）。
工具层只依赖 Executor 协议——换实现时工具代码零改动。
"""

from codelotte.sandbox.docker import DockerExecutor
from codelotte.sandbox.executor import ExecResult, Executor
from codelotte.sandbox.local import LocalExecutor

__all__ = ["DockerExecutor", "ExecResult", "Executor", "LocalExecutor"]
