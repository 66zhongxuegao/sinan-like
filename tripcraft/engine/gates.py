"""门控规则 —— 每一步「能不能往前走」的硬判定。

口径来源：PRD 第 3.3 / 8 章、第 13 章硬规则。
设计原则（DECISIONS D-008 三层判断）：门控是**硬编码**的确定性判定，
不交给生成式模型。M0 阶段先做「结构校验 + 硬规则」两层，
业务细则（如路线可行性）在 M2/M3 接入外部数据后再补。

硬规则（不可绕过）：
- 保险必买（S6/S8）
- 未确认资源不得报死价（S4/S6）
- 合同/保险/付款齐全（S8）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..contracts.deliverables import Deliverable
from ..contracts.enums import DeliverableKind, StepId
from ..contracts.task import TaskInstance


@dataclass
class GateContext:
    """门控判定的输入。"""

    instance: TaskInstance
    deliverables: list[Deliverable] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)

    def has_deliverable(self, kind: DeliverableKind) -> bool:
        return any(d.kind == kind for d in self.deliverables)

    def flag(self, name: str) -> bool:
        return bool(self.flags.get(name, False))


@dataclass
class GateOutcome:
    step: StepId
    passed: bool
    reasons: list[str] = field(default_factory=list)   # 不通过原因
    hard: bool = False                                # 是否命中硬规则（不可绕过）

    def __bool__(self) -> bool:
        return self.passed


GateFn = Callable[[GateContext], GateOutcome]


def _ok(step: StepId) -> GateOutcome:
    return GateOutcome(step=step, passed=True)


def _fail(step: StepId, *reasons: str, hard: bool = False) -> GateOutcome:
    return GateOutcome(step=step, passed=False, reasons=list(reasons), hard=hard)


# ---------------------------------------------------------------- 各步门控

def gate_s0(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("hard_rules_recited"):
        return _fail(StepId.S0_INIT, "未复述硬规则（首呼时限/方案时限/保险必买/不飞单/未确认不报死价）")
    return _ok(StepId.S0_INIT)


def gate_s1(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("grabbed_in_time"):
        return _fail(StepId.S1_GRAB, "未在倒计时内抢单")
    if not ctx.flag("first_call_planned"):
        return _fail(StepId.S1_GRAB, "未识别派单缺失字段/未形成首呼计划")
    return _ok(StepId.S1_GRAB)


def gate_s2(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("core_info_collected"):
        return _fail(StepId.S2_FIRST_CALL, "核心信息缺失（人数/日期/目的地/预算口径/交通住宿意向）")
    if not ctx.flag("client_agreed_continue"):
        return _fail(StepId.S2_FIRST_CALL, "客户未同意继续沟通")
    if ctx.flag("mistook_value_as_budget"):
        return _fail(StepId.S2_FIRST_CALL, "把「性价比高」当成预算已明确")
    return _ok(StepId.S2_FIRST_CALL)


def gate_s3(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.REQUIREMENT_SHEET):
        return _fail(StepId.S3_REQUIREMENT, "未产出需求单")
    if not ctx.flag("hard_soft_separated"):
        return _fail(StepId.S3_REQUIREMENT, "未区分硬约束与软偏好")
    if not ctx.flag("requirement_confirmed"):
        return _fail(StepId.S3_REQUIREMENT, "需求未经客户确认")
    return _ok(StepId.S3_REQUIREMENT)


def gate_s4(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.RESOURCE_TABLE):
        return _fail(StepId.S4_RESOURCE, "未产出资源询价表")
    if not ctx.flag("resource_confirmed"):
        return _fail(StepId.S4_RESOURCE, "核心资源未确认可用性与价格")
    if ctx.flag("dead_quote"):
        return _fail(StepId.S4_RESOURCE, "把未确认资源写成确定报价（违反硬规则）", hard=True)
    return _ok(StepId.S4_RESOURCE)


def gate_s5(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.ITINERARY_PLAN):
        return _fail(StepId.S5_ITINERARY, "未产出行程方案")
    if not ctx.flag("hard_constraints_covered"):
        return _fail(StepId.S5_ITINERARY, "未覆盖全部硬约束/未排除「明确不要」")
    return _ok(StepId.S5_ITINERARY)


def gate_s6(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.QUOTATION):
        return _fail(StepId.S6_QUOTATION, "未产出分项报价单")
    if ctx.flag("quote_loss"):
        return _fail(StepId.S6_QUOTATION, "报价亏损（成本高于报价）", hard=True)
    if not ctx.flag("insurance_included"):
        return _fail(StepId.S6_QUOTATION, "报价未包含保险（定制游必须买保险）", hard=True)
    if ctx.flag("dead_quote"):
        return _fail(StepId.S6_QUOTATION, "存在未确认资源的确定报价", hard=True)
    return _ok(StepId.S6_QUOTATION)


def gate_s7(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("client_confirmed_final"):
        return _fail(StepId.S7_ITERATION, "客户未明确确认最终安排")
    if ctx.flag("version_conflict"):
        return _fail(StepId.S7_ITERATION, "方案/报价版本不可追溯")
    return _ok(StepId.S7_ITERATION)


def gate_s8(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("order_consistent"):
        return _fail(StepId.S8_ORDER, "录单字段与最终方案不一致")
    if not ctx.flag("contract_signed"):
        return _fail(StepId.S8_ORDER, "未签合同", hard=True)
    if not ctx.flag("insurance_bought"):
        return _fail(StepId.S8_ORDER, "未购买保险", hard=True)
    if not ctx.flag("payment_received"):
        return _fail(StepId.S8_ORDER, "未收取定金/首款")
    return _ok(StepId.S8_ORDER)


def gate_s9(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("resources_locked"):
        return _fail(StepId.S9_LOCK, "核心资源未锁定")
    if not ctx.flag("departure_notice_confirmed"):
        return _fail(StepId.S9_LOCK, "出团通知书未按时送达/客户未确认")
    return _ok(StepId.S9_LOCK)


def gate_s10(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.INCIDENT_LOG):
        return _fail(StepId.S10_ON_TRIP, "突发事件未形成处理记录")
    if not ctx.flag("incident_closed"):
        return _fail(StepId.S10_ON_TRIP, "事件未闭环")
    if ctx.flag("complaint_escalated"):
        return _fail(StepId.S10_ON_TRIP, "客户情绪升级为投诉")
    return _ok(StepId.S10_ON_TRIP)


def gate_s11(ctx: GateContext) -> GateOutcome:
    if not ctx.has_deliverable(DeliverableKind.SETTLEMENT):
        return _fail(StepId.S11_SETTLEMENT, "未产出结算核对表")
    if not ctx.flag("accounts_reconciled"):
        return _fail(StepId.S11_SETTLEMENT, "账目不一致且差异未说明")
    if not ctx.flag("final_paid"):
        return _fail(StepId.S11_SETTLEMENT, "尾款未结清")
    return _ok(StepId.S11_SETTLEMENT)


def gate_s12(ctx: GateContext) -> GateOutcome:
    if not ctx.flag("review_generated"):
        return _fail(StepId.S12_REVIEW, "未生成复盘报告/画像未更新")
    return _ok(StepId.S12_REVIEW)


GATES: dict[StepId, GateFn] = {
    StepId.S0_INIT: gate_s0,
    StepId.S1_GRAB: gate_s1,
    StepId.S2_FIRST_CALL: gate_s2,
    StepId.S3_REQUIREMENT: gate_s3,
    StepId.S4_RESOURCE: gate_s4,
    StepId.S5_ITINERARY: gate_s5,
    StepId.S6_QUOTATION: gate_s6,
    StepId.S7_ITERATION: gate_s7,
    StepId.S8_ORDER: gate_s8,
    StepId.S9_LOCK: gate_s9,
    StepId.S10_ON_TRIP: gate_s10,
    StepId.S11_SETTLEMENT: gate_s11,
    StepId.S12_REVIEW: gate_s12,
}