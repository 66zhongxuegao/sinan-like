"""13 步状态机骨架的回归测试。"""

from tripcraft.contracts.deliverables import Deliverable
from tripcraft.contracts.enums import DeliverableKind, OrderStatus, StepId, StepStatus
from tripcraft.contracts.task import TaskInstance
from tripcraft.engine.state_machine import Run

# 走通全流程所需的标记与交付物
HAPPY_FLAGS = [
    "hard_rules_recited",
    "grabbed_in_time", "first_call_planned",
    "core_info_collected", "client_agreed_continue",
    "hard_soft_separated", "requirement_confirmed",
    "resource_confirmed",
    "hard_constraints_covered",
    "insurance_included",
    "client_confirmed_final",
    "order_consistent", "contract_signed", "insurance_bought", "payment_received",
    "resources_locked", "departure_notice_confirmed",
    "incident_closed",
    "accounts_reconciled", "final_paid",
    "review_generated",
]


def make_run() -> Run:
    inst = TaskInstance(id="t1", template_id="tpl1", user_id="u1")
    return Run(instance=inst)


def set_happy(run: Run) -> None:
    for f in HAPPY_FLAGS:
        run.set_flag(f)
    for kind in DeliverableKind:
        run.add_deliverable(Deliverable(id=f"d-{kind.value}", instance_id="t1", kind=kind,
                                        step=StepId.S3_REQUIREMENT))


def test_starts_at_s0():
    run = make_run()
    assert run.instance.current_step is StepId.S0_INIT
    assert run.steps[StepId.S0_INIT].status is StepStatus.IN_PROGRESS


def test_gate_blocks_without_flags():
    run = make_run()
    result = run.advance()
    assert not result.ok
    assert run.instance.current_step is StepId.S0_INIT


def test_full_happy_path():
    run = make_run()
    set_happy(run)
    steps = list(StepId)
    for i, step in enumerate(steps):
        assert run.instance.current_step is step, f"应在 {step}"
        result = run.advance()
        if step is StepId.S12_REVIEW:
            assert result.ok
            assert run.steps[step].status is StepStatus.PASSED
            break
        assert result.ok, f"{step} 应通过，实际: {result.reason}"
    assert run.instance.status is OrderStatus.REVIEWED


def test_hard_rule_insurance_blocks():
    run = make_run()
    set_happy(run)
    # 推进到 S6
    for _ in range(6):
        assert run.advance().ok
    assert run.instance.current_step is StepId.S6_QUOTATION
    run.set_flag("insurance_included", False)
    result = run.advance()
    assert not result.ok
    assert result.hard_blocked
    assert "保险" in result.reason


def test_rollback_within_work_zone():
    run = make_run()
    set_happy(run)
    for _ in range(8):  # 走到 S8
        assert run.advance().ok
    assert run.instance.current_step is StepId.S8_ORDER
    result = run.rollback(StepId.S4_RESOURCE, "客户改了酒店要求")
    assert result.ok
    assert run.instance.current_step is StepId.S4_RESOURCE
    assert run.steps[StepId.S4_RESOURCE].rollback_from is StepId.S8_ORDER


def test_rollback_outside_work_zone_rejected():
    run = make_run()
    set_happy(run)
    for _ in range(8):
        assert run.advance().ok
    result = run.rollback(StepId.S1_GRAB, "非法回退")
    assert not result.ok
    assert run.instance.current_step is StepId.S8_ORDER