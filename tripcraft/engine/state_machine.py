"""13 步状态机骨架（PRD 第 3 章）。

设计（DECISIONS D-010）：不引入 LangGraph/CrewAI，用确定性代码实现。
- 线性主干 S0->S1->...->S12
- 协同工作区 S2-S7 支持循环回退（S7 可回退到 S2/S3/S4/S5/S6）
- 门控不通过则不放行；硬规则命中则拦截
- 时限超时由 deadlines 驱动（M0 先留接口）

M0 只做「结构 + 门控」骨架，业务细则在 M1/M3 接入。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.deliverables import Deliverable
from ..contracts.enums import OrderStatus, StepId, StepStatus
from ..contracts.task import TaskInstance
from .gates import GATES, GateContext, GateOutcome

WORK_ZONE: tuple[StepId, ...] = (
    StepId.S2_FIRST_CALL, StepId.S3_REQUIREMENT, StepId.S4_RESOURCE,
    StepId.S5_ITINERARY, StepId.S6_QUOTATION, StepId.S7_ITERATION,
)

STEP_TO_ORDER: dict[StepId, OrderStatus] = {
    StepId.S0_INIT: OrderStatus.PENDING_GRAB,
    StepId.S1_GRAB: OrderStatus.GRABBED,
    StepId.S2_FIRST_CALL: OrderStatus.FIRST_CALL,
    StepId.S3_REQUIREMENT: OrderStatus.REQUIREMENT,
    StepId.S4_RESOURCE: OrderStatus.RESOURCE,
    StepId.S5_ITINERARY: OrderStatus.ITINERARY,
    StepId.S6_QUOTATION: OrderStatus.QUOTATION,
    StepId.S7_ITERATION: OrderStatus.ITERATION,
    StepId.S8_ORDER: OrderStatus.DEAL,
    StepId.S9_LOCK: OrderStatus.LOCKING,
    StepId.S10_ON_TRIP: OrderStatus.ON_TRIP,
    StepId.S11_SETTLEMENT: OrderStatus.SETTLEMENT,
    StepId.S12_REVIEW: OrderStatus.REVIEWED,
}


@dataclass
class TransitionResult:
    ok: bool
    from_step: StepId
    to_step: StepId
    reason: str = ""
    hard_blocked: bool = False


@dataclass
class StepRecord:
    step: StepId
    status: StepStatus = StepStatus.NOT_STARTED
    rollback_from: StepId | None = None


@dataclass
class Run:
    """一次演练的运行时状态（对应 PRD task_step_state）。"""

    instance: TaskInstance
    steps: dict[StepId, StepRecord] = field(default_factory=dict)
    deliverables: list[Deliverable] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for step in StepId:
            self.steps.setdefault(step, StepRecord(step))
        self.steps[self.instance.current_step].status = StepStatus.IN_PROGRESS

    # ---- helpers ----

    def ctx(self) -> GateContext:
        return GateContext(instance=self.instance, deliverables=self.deliverables, flags=self.flags)

    def add_deliverable(self, d: Deliverable) -> None:
        self.deliverables.append(d)

    def set_flag(self, name: str, value: bool = True) -> None:
        self.flags[name] = value

    def gate(self) -> GateOutcome:
        return GATES[self.instance.current_step](self.ctx())

    # ---- transitions ----

    def advance(self) -> TransitionResult:
        cur = self.instance.current_step
        outcome = self.gate()
        if not outcome.passed:
            self.log.append(f"[{cur}] 门控不通过: {'; '.join(outcome.reasons)}")
            return TransitionResult(False, cur, cur, "; ".join(outcome.reasons), outcome.hard)
        if cur is StepId.S12_REVIEW:
            self.steps[cur].status = StepStatus.PASSED
            return TransitionResult(True, cur, cur, "已是最后一步")
        self.steps[cur].status = StepStatus.PASSED
        nxt = StepId(next(s for s in StepId if s.value == f"S{int(cur.value[1:]) + 1}"))
        self.instance.current_step = nxt
        self.instance.status = STEP_TO_ORDER[nxt]
        self.steps[nxt].status = StepStatus.IN_PROGRESS
        self.log.append(f"[{cur}] 通过 -> {nxt}")
        return TransitionResult(True, cur, nxt, "门控通过")

    def rollback(self, to_step: StepId, reason: str) -> TransitionResult:
        cur = self.instance.current_step
        if to_step not in WORK_ZONE or to_step.value >= cur.value:
            return TransitionResult(False, cur, cur, f"不允许回退到 {to_step}")
        self.steps[cur].status = StepStatus.ROLLED_BACK
        self.instance.current_step = to_step
        self.instance.status = STEP_TO_ORDER[to_step]
        rec = self.steps[to_step]
        rec.status = StepStatus.IN_PROGRESS
        rec.rollback_from = cur
        self.log.append(f"[{cur}] 回退 -> {to_step}（{reason}）")
        return TransitionResult(True, cur, to_step, reason)

    def fail(self, reason: str) -> None:
        cur = self.instance.current_step
        self.steps[cur].status = StepStatus.FAILED
        self.instance.status = OrderStatus.LOST
        self.log.append(f"[{cur}] 失败: {reason}")