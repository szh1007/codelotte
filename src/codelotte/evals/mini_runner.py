# pyright: reportMissingImports=false
"""独立运行的 mini-swe-agent 适配入口（票据 16）。

由"装了 mini-swe-agent 的解释器"直接执行，不导入 codelotte：
    python mini_runner.py --model deepseek-flash --task ... --output traj.json ...

为什么不用 `minisweagent.run.mini`：它的 CLI 在模块导入时创建 prompt_toolkit
会话，Windows 无控制台（stdout 被重定向）会直接抛 NoConsoleScreenBufferError。
这里直接装配 mini 自己的 `DefaultAgent` + `LocalEnvironment` + `LitellmModel`，
保留它的提示词、工具解析、步数/成本限制与轨迹格式，只绕开交互层。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run mini-swe-agent non-interactively")
    parser.add_argument("--model", required=True, help="模型 id（不带 provider 前缀）")
    parser.add_argument("--task", required=True, help="任务指令")
    parser.add_argument("--output", required=True, help="轨迹输出路径")
    parser.add_argument("--workspace", required=True, help="工作区目录")
    parser.add_argument("--step-limit", type=int, default=0, help="最多模型调用次数")
    parser.add_argument("--wall-time", type=int, default=0, help="最多墙钟秒数")
    parser.add_argument(
        "--reasoning-effort", default="high", help="思考档位（与 codelotte 对齐）"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.config import get_config_from_spec
        from minisweagent.environments.local import LocalEnvironment
        from minisweagent.models.litellm_model import LitellmModel
    except Exception as exc:  # 解释器没装 mini-swe-agent
        print(
            f"codelotte mini_runner: 无法导入 mini-swe-agent：{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        config = get_config_from_spec("mini.yaml")
        model_config = dict(config.get("model") or {})
        model_config["model_name"] = f"openai/{args.model}"
        model_kwargs = dict(model_config.get("model_kwargs") or {})
        model_kwargs["reasoning_effort"] = args.reasoning_effort
        model_config["model_kwargs"] = model_kwargs
        model = LitellmModel(**model_config)

        environment_config = dict(config.get("environment") or {})
        environment_config["cwd"] = args.workspace
        environment = LocalEnvironment(**environment_config)

        agent_config = dict(config.get("agent") or {})
        for key in ("mode", "confirm_exit", "agent_class"):
            agent_config.pop(key, None)
        agent_config.update(
            {
                "step_limit": args.step_limit,
                "cost_limit": 0,  # 成本由 codelotte 代理记账，不让 litellm 的估算误停
                "wall_time_limit_seconds": args.wall_time,
                "output_path": Path(args.output),
            }
        )
        agent = DefaultAgent(model, environment, **agent_config)
        result = agent.run(args.task)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
