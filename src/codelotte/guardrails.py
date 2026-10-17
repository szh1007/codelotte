"""死循环三层防御（票据 11，SPEC §B）：纯状态机，不碰会话、不发请求。

三层各自独立触发、各自记录事件：

- **工具层**：连续同名同参调用到 `repeat` 阈值 → 拦截；同名同参且连续结果完全相同到
  `stagnation` 阈值 → 更早拦截（结果没变化是更强的打转信号）。被拦的调用不执行，
  拦截说明作为工具结果回给模型。
- **推理层**：连续 `failure` 次**真正执行后失败**的工具调用（工具错误、权限拒绝、
  沙箱错误、参数畸形）→ 熔断当前回合。工具层拦截本身不计入——那是层①的动作，
  让层③去处理，三层保持独立。
- **规划层**：工具层第一次拦截 → 把任务目标与硬约束重注入上下文后继续；累计拦截到
  `planning` 阈值 → 温和终止回合、交还用户（重注入没救回来就不再无限重试）。

## 配置阈值 → 事件动作的对应关系

配置键回答"数到几"，事件 `guard` 回答"数到之后做了什么"；两者不是一一同名：

| 配置键（settings.json） | 默认 | 计数的对象 | 所属层 `layer` | 动作事件 `guard` | 事件阈值字段 |
|---|---|---|---|---|---|
| `guardrailRepeatLimit` | 3 | 连续同名同参调用次数 | `tool` | `repeat` | `threshold` |
| `guardrailStagnationLimit` | 2 | 同一签名连续相同结果次数 | `tool` | `stagnation` | `threshold` |
| `guardrailFailureLimit` | 3 | 连续真正执行后失败的次数 | `reasoning` | `circuitBreaker` | `threshold` |
| `guardrailPlanningLimit` | 2 | 工具层累计拦截次数 | `planning` | 首次 `reinject`；达标 `terminate` | `threshold` |

- 前两行同名，因为"数什么"和"做什么"是同一件事：数到重复就拦、数到无进展就拦。
  同一签名同时满足两个条件时 `stagnation` 优先——结果没变化比单纯重复是更强的打转信号。
- `failure` 是计数器不是动作：每次失败只推进计数，不写 guardrail 事件（`tool_result` 已经
  记录了这次失败）；连续失败到阈值才发生 `circuitBreaker`（禁用工具、请模型总结现状）。
  工具层拦截本身**不计入** `failure`——那是层①的动作，交给层③处理，三层保持独立。
- `planning` 是层名 + 阈值名，不是单一动作：首次拦截批次写 `reinject`（重注入任务目标与
  硬约束，给模型一次改法机会），累计拦截数达到阈值写 `terminate`（温和终止、交还用户）。
- 每条事件自带 `layer` / `guard` / `count`（规划层用 `blocks`）/ `threshold`，即使名字不同，
  记录本身也能自解释是哪一层、数到了什么、阈值多少、做了什么。
- `TurnEnded.guardrail_stop` 用的是第三个视角"回合因哪一层结束"：熔断写 `circuitBreaker`，
  规划层终止写 `planning`（对应最后一条 `guard=terminate` 事件）。

阈值全部来自 settings.json（默认值见 GuardrailLimits），本模块只做判定与计数。
"连续"按**回合**计：每回合开始 reset，上一回合的重复/失败不牵连新任务。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # 只为类型标注：运行时不把纯状态机绑到配置模块
    from codelotte.config import Settings

EVENT_GUARDRAIL = "guardrail"  # 会话 event 记录的 kind

LAYER_TOOL = "tool"
LAYER_REASONING = "reasoning"
LAYER_PLANNING = "planning"

GUARD_REPEAT = "repeat"
GUARD_STAGNATION = "stagnation"
GUARD_CIRCUIT = "circuitBreaker"
GUARD_REINJECT = "reinject"
GUARD_TERMINATE = "terminate"

# TurnEnded.guardrail_stop 的取值（消费方展示用；与事件里的 guard 分开命名：
# guard 是"做了什么"，stop 是"回合为什么结束"）
STOP_CIRCUIT = GUARD_CIRCUIT
STOP_PLANNING = "planning"

GOAL_MAX_CHARS = 1200  # 重注入的任务目标上限（原话可能很长，提醒不该再撑爆上下文）

HARD_CONSTRAINTS = (
    "只修改用户指定的内容，不碰工作区之外的文件；"
    "沙箱内网络默认不可用；"
    "权限被拒或工具失败时换一种做法，不要重复同一调用；"
    "无法推进时如实说明卡点并交还用户。"
)


@dataclass(frozen=True)
class GuardrailLimits:
    """三层防御的触发阈值（settings.json 的 guardrail* 键；这里有默认值）。"""

    repeat: int = 3  # 连续同名同参调用第 N 次拦截
    stagnation: int = 2  # 同名同参连续 N 次结果完全相同后，拦截下一次
    failure: int = 3  # 连续 N 次工具失败后熔断（不含工具层拦截本身）
    planning: int = 2  # 累计拦截 N 次后温和终止（首次拦截批次先重注入）

    @classmethod
    def from_settings(cls, settings: Settings) -> GuardrailLimits:
        """settings.json 的可选覆盖 + 本类默认值（唯一默认值来源）。"""
        defaults = cls()
        return cls(
            repeat=settings.guardrail_repeat_limit or defaults.repeat,
            stagnation=settings.guardrail_stagnation_limit or defaults.stagnation,
            failure=settings.guardrail_failure_limit or defaults.failure,
            planning=settings.guardrail_planning_limit or defaults.planning,
        )


@dataclass(frozen=True)
class ToolBlock:
    """工具层对一次调用的拦截结论。message 直接作为工具结果回传模型。"""

    guard: str
    count: int
    threshold: int
    detail: str
    message: str


@dataclass(frozen=True)
class PlanningAction:
    """规划层在一个工具批次结束后的动作：重注入后继续，或温和终止。"""

    kind: str
    blocks: int
    threshold: int
    detail: str


def _signature(name: str, arguments: dict[str, Any]) -> str:
    """同名同参的规范形：键序无关（dict 的遍历顺序不参与语义）。"""
    canonical = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"{name}\x00{canonical}"


def _result_digest(content: str) -> str:
    """结果指纹：忽略行尾空白与 CRLF 差异——这些不算"实质变化"。"""
    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _repeat_message(name: str, count: int) -> str:
    return (
        f"错误：守护拦截——你已经连续 {count} 次调用 {name} 且参数完全相同。"
        "不要重复同一动作：换一种做法（读别的文件、换命令），或先总结现状再继续。"
    )


def _stagnation_message(name: str, count: int) -> str:
    return (
        f"错误：守护拦截——{name} 连续 {count} 次返回完全相同的结果，没有进展。"
        "请换一种做法，不要重复同一调用；如果无法推进，先总结现状并说明卡点。"
    )


def _goal_text(goal: str) -> str:
    text = goal.strip()
    if len(text) <= GOAL_MAX_CHARS:
        return text
    return text[:GOAL_MAX_CHARS] + "…"


def planning_reminder(goal: str, detail: str) -> str:
    """规划层重注入：任务目标 + 硬约束（作为 user 消息追加在工具结果之后）。"""
    return (
        f"[codelotte 规划层提醒] 工具层刚拦截了一次重复操作：{detail}。\n"
        f"任务目标（用户原话）：{_goal_text(goal)}\n"
        f"硬约束：{HARD_CONSTRAINTS}\n"
        "请停止重复，先用一两句话说明当前进展与卡点，再选择一种不同的做法继续；"
        "若无法继续，直接说明原因并交还用户。"
    )


def circuit_reminder(goal: str, failures: int) -> str:
    """推理层熔断：请模型在禁用工具的情况下总结现状。"""
    return (
        f"[codelotte 推理层熔断] 连续 {failures} 次工具调用失败，本回合已停止执行工具。\n"
        f"任务目标（用户原话）：{_goal_text(goal)}\n"
        "请不要再调用工具（本轮工具已禁用），基于已有信息用几句话总结："
        "已经完成了什么、卡在哪里、下一步建议是什么。"
    )


def planning_terminate_message(blocks: int, threshold: int, detail: str) -> str:
    """规划层温和终止时写进审计与界面的一句话。"""
    return (
        f"工具层已累计拦截 {blocks} 次（规划层阈值 {threshold}），模型仍在重复，"
        f"本回合温和终止并交还用户。最近一次拦截：{detail}"
    )


class GuardrailTracker:
    """一个回合内的三层防御状态。loop 在每次工具调用前后喂它，按结论记录事件。"""

    def __init__(self, limits: GuardrailLimits) -> None:
        self.limits = limits
        self.reset()

    def reset(self) -> None:
        """新回合：所有连续计数清零（上一回合的失败不牵连新任务）。"""
        self._last_signature: str | None = None
        self._repeat_streak = 0
        self._last_executed_signature: str | None = None
        self._last_result_digest: str | None = None
        self._stagnation_streak = 0
        self._failure_streak = 0
        self._blocks_this_batch = 0
        self._batch_block_details: list[str] = []
        self._planning_blocks = 0
        self._planning_injected = False

    def begin_batch(self) -> None:
        """一条 assistant 消息声明的工具调用批次开始（规划层按批次结算）。"""
        self._blocks_this_batch = 0
        self._batch_block_details = []

    @property
    def blocks_this_batch(self) -> int:
        return self._blocks_this_batch

    @property
    def failure_streak(self) -> int:
        return self._failure_streak

    def should_break(self) -> bool:
        """推理层熔断：当前连续失败数已达到阈值（批结束时检查）。"""
        return self._failure_streak >= self.limits.failure

    def check_call(self, name: str, arguments: dict[str, Any]) -> ToolBlock | None:
        """执行前的工具层判定；返回 None = 放行执行。"""
        signature = _signature(name, arguments)
        if signature == self._last_signature:
            self._repeat_streak += 1
        else:
            self._last_signature = signature
            self._repeat_streak = 1

        if (
            signature == self._last_executed_signature
            and self._stagnation_streak >= self.limits.stagnation
        ):
            block = ToolBlock(
                guard=GUARD_STAGNATION,
                count=self._stagnation_streak,
                threshold=self.limits.stagnation,
                detail=f"{name} 连续 {self._stagnation_streak} 次返回相同结果",
                message=_stagnation_message(name, self._stagnation_streak),
            )
            self._register_block(block.detail)
            return block

        if self._repeat_streak >= self.limits.repeat:
            block = ToolBlock(
                guard=GUARD_REPEAT,
                count=self._repeat_streak,
                threshold=self.limits.repeat,
                detail=f"连续 {self._repeat_streak} 次调用 {name} 且参数相同",
                message=_repeat_message(name, self._repeat_streak),
            )
            self._register_block(block.detail)
            return block
        return None

    def record_result(
        self, name: str, arguments: dict[str, Any], content: str, *, ok: bool
    ) -> None:
        """执行后的计数：失败累计/清零；成功结果参与无进展检测。"""
        if not ok:
            self._failure_streak += 1
            self._reset_stagnation()
            return
        self._failure_streak = 0
        signature = _signature(name, arguments)
        digest = _result_digest(content)
        if signature == self._last_executed_signature and digest == self._last_result_digest:
            self._stagnation_streak += 1
        else:
            self._last_executed_signature = signature
            self._last_result_digest = digest
            self._stagnation_streak = 1

    def record_malformed(self) -> None:
        """参数畸形（未执行）也计入连续失败：模型没改对参数就是没进展。"""
        self._failure_streak += 1
        self._reset_stagnation()

    def planning_after_batch(self) -> PlanningAction | None:
        """批结束后的规划层结算：首次拦截批次先重注入；之后累计到阈值则终止。

        每个批次最多产生一个动作；批内多次拦截合并计数（一条 assistant 消息算一步）。
        "首次批次先重注入"是给模型一次改法的机会——即使首批就拦了多次，也先提醒再谈终止。
        """
        blocks = self._blocks_this_batch
        detail = "；".join(self._batch_block_details)
        self._blocks_this_batch = 0
        self._batch_block_details = []
        if blocks == 0:
            return None
        self._planning_blocks += blocks
        if not self._planning_injected:
            self._planning_injected = True
            return PlanningAction(
                kind=GUARD_REINJECT,
                blocks=self._planning_blocks,
                threshold=self.limits.planning,
                detail=detail,
            )
        if self._planning_blocks >= self.limits.planning:
            return PlanningAction(
                kind=GUARD_TERMINATE,
                blocks=self._planning_blocks,
                threshold=self.limits.planning,
                detail=detail,
            )
        return None

    def _register_block(self, detail: str) -> None:
        self._blocks_this_batch += 1
        self._batch_block_details.append(detail)

    def _reset_stagnation(self) -> None:
        self._last_executed_signature = None
        self._last_result_digest = None
        self._stagnation_streak = 0
