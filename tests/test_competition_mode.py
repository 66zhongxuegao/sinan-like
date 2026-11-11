"""比赛演示放行回归：开关打开时业务校验全通过，客户一次作答即满意。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.competition_mode import enabled
from tripcraft.services.customer_context import guarded_reply
from tripcraft.services.deliverable_service import DeliverableService, check_arithmetic
from tripcraft.services.guard_service import GuardService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

ORDER = "9000000000000006"


def make():
    store = Store(os.path.join(tempfile.gettempdir(), f"competition-{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    practice.seed("u-demo")
    return store, practice


class MustNotCallLLM:
    def chat(self, *_args, **_kwargs):
        raise AssertionError("比赛放行不应调用客户模型")

    def chat_json(self, *_args, **_kwargs):
        raise AssertionError("比赛放行不应调用客户模型")


def test_competition_switch_passes_business_checks(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    assert enabled()
    assert DeliverableService.validate("itinerary", {}) == []
    assert check_arithmetic("quotation", {"total": 999, "items": []}) == []
    report = GuardService().check("分项报价", "这不是一份合格的报价")
    assert report["blocked"] is False and report["verdict"] == "pass"
    assert report["competition_bypass"] is True


def test_customer_feedback_is_satisfied_in_one_turn(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, _ = make()
    out = guarded_reply(store, MustNotCallLLM(), ORDER, "plan", "客户 X 的行程方案", feedback=True)
    assert out["sentiment"] == "满意" and out["asks"] == []
    assert "满意" in out["reply"]
    assert out["consistency"]["competition_bypass"] is True


def test_forms_and_supplier_open_but_gate_requires_real_actions(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, practice = make()
    # 表单/资源放行，但流程门槛不能凭空通过。
    assert practice.gate_report(ORDER)["passed"] is False
    supplier = SupplierService(store=store, llm=None, practice=practice)
    practice.record_action(ORDER, "grab")
    practice.record_action(ORDER, "first_call")
    supplier.add_contact(ORDER, "客户")
    practice.record_action(ORDER, "deliverable:需求确认单")
    supplier.add_contact(ORDER, "地接社")
    hub = supplier.ensure_hub("u-demo", ORDER)
    supplier.respond(hub["session_id"], "需要酒店和车队", target_role="地接社")
    added = supplier.add_contact(ORDER, "酒店")
    sid = added["session_id"]
    out = supplier.respond(sid, "请报四星房价格")
    assert out and out.get("deferred") is False


def test_stage_advances_only_after_current_stage_actions(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, practice = make()
    practice.record_action(ORDER, "grab")
    assert int(store.order(ORDER)["stage_index"]) == 0
    practice.record_action(ORDER, "first_call")
    assert int(store.order(ORDER)["stage_index"]) == 0
    practice.record_action(ORDER, "deliverable:需求确认单")
    assert int(store.order(ORDER)["stage_index"]) == 1

def test_resource_lock_chat_auto_records_locked_action(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, practice = make()
    store.set_stage(ORDER, 4)
    supplier = SupplierService(store=store, llm=None, practice=practice)
    hub = supplier.ensure_hub("u-demo")
    out = supplier.respond(hub["session_id"], "好的，锁定吧", order_id=ORDER)
    assert out and out.get("deferred") is False
    assert store.has_action(ORDER, "resources_locked")
    # 资源锁定动作已登记，但出团通知书还没完成，不能跳到下一阶。
    assert int(store.order(ORDER)["stage_index"]) == 4

def test_full_flow_never_skips_stages(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, practice = make()
    stages = [
        ("grab", 0), ("first_call", 0), ("deliverable:需求确认单", 1),
        ("deliverable:行程方案", 1), ("deliverable:分项报价", 1),
        ("guard_pass:分项报价", 1), ("customer_confirmed_plan", 2),
        ("contract_signed", 2), ("insurance_bought", 3),
        ("customer_signed_contract", 3), ("deposit_paid", 4),
        ("resources_locked", 4), ("pre_trip_notice", 5),
        ("settlement_verified", 6), ("balance_paid", 6), ("review_done", 7),
    ]
    for action, expected in stages:
        practice.record_action(ORDER, action)
        assert int(store.order(ORDER)["stage_index"]) == expected, action
