"""实战服务测试。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.contracts.enums import Dimension
from tripcraft.contracts.enums import StepId
from tripcraft.contracts.rubric import RUBRICS
from tripcraft.contracts.skill_points import SKILL_POINTS, by_step
from tripcraft.services.practice_service import PracticeService, ORDER_STEPS
from tripcraft.storage import Store


def make():
    p = os.path.join(tempfile.gettempdir(), f"tp_{uuid4().hex}.sqlite")
    store = Store(p)
    svc = PracticeService(store)
    svc.seed("u1")
    return svc, store


def test_seed_and_list_orders():
    svc, _ = make()
    orders = svc.list_orders("u1")
    assert len(orders) == 5, "订单管理只列我的订单；未抢的阶段 0 派单归消息中心"
    assert all(o["stage_name"] in ORDER_STEPS for o in orders)


def test_gate_report_shape():
    svc, _ = make()
    g = svc.gate_report("9000000000000001")
    assert g["total"] > 0
    assert len(g["checks"]) == g["total"]
    assert all(isinstance(c["ok"], bool) for c in g["checks"])
    assert all({"action", "label", "hint", "ok", "reason"} <= set(c) for c in g["checks"])
    assert g["stage_hint"]


def test_flow_progress_maps_to_13_steps():
    svc, _ = make()
    f = svc.flow_progress("9000000000000002")
    assert len(f["steps"]) == 13
    assert f["steps"][f["current"]]["state"] == "current"


def test_order_scores_cover_8_dimensions_and_61_points():
    svc, _ = make()
    r = svc.order_scores("9000000000000001")
    assert len(r["dimensions"]) == 8
    assert sum(len(d["points"]) for d in r["dimensions"]) == 61
    assert {d["id"] for d in r["dimensions"]} == {d.value for d in Dimension}


def test_order_scores_are_empty_until_scored():
    """没有证据就没有分数：不再返回伪随机演示值（D-021）。"""
    svc, _ = make()
    r = svc.order_scores("9000000000000001")
    assert r["average"] is None
    assert r["evaluated"] == 0
    assert all(d["score"] is None for d in r["dimensions"])
    assert all(not p["evaluated"] for d in r["dimensions"] for p in d["points"])


def test_record_evidence_and_map_to_skill_points():
    svc, _ = make()
    oid = "9000000000000001"
    assert svc.evidence(oid) == []
    svc.record_evidence(oid, "call", "定制师: 您好，请问怎么称呼您？\n客户: 我姓王。", ref="c1")
    svc.record_evidence(oid, "\u884c\u7a0b\u65b9\u6848", "\u65b9\u6848\u6b63\u6587", ref="d1")
    assert len(svc.evidence(oid)) == 2
    ids = svc.target_skill_points(oid)
    assert ids, "S2/S5 应映射出技能点"
    assert all(i in RUBRICS for i in ids)
    # 通话映射出的是首呼相关技能点
    s2 = [sp.id for sp in by_step(StepId.S2_FIRST_CALL)]
    assert set(ids) & set(s2)


def test_every_order_is_inbound_and_scores_cross_culture():
    """本平台只做入境接待：中文单同样是入境单，C8 一律参评（D-021）。"""
    svc, _ = make()
    c8 = {sp.id for sp in SKILL_POINTS if sp.dimension is Dimension.C8_CROSS_CULTURE}
    assert c8, "应存在 C8 技能点"

    # 中文单（香港客源）
    svc.record_evidence("9000000000000001", "call", "定制师: 您好", ref="c1")
    zh_order = set(svc.target_skill_points("9000000000000001"))
    assert zh_order
    assert zh_order & c8, "中文单也必须评 C8——客源是香港"

    # 英文单（美国客源）
    svc.record_evidence("9000000000000005", "call", "Agent: Hello, this is Kenji.", ref="c2")
    en_order = set(svc.target_skill_points("9000000000000005"))
    assert en_order & c8


def test_orders_carry_source_market_and_documents():
    svc, _ = make()
    orders = {o["order_id"]: o for o in svc.list_orders("u1")}
    assert len(orders) == 5
    assert orders["9000000000000001"]["source_market"] == "\u9999\u6e2f"
    assert orders["9000000000000001"]["language"] == "\u4e2d\u6587"
    assert "\u56de\u4e61\u8bc1" in orders["9000000000000001"]["documents"]
    assert orders["9000000000000005"]["source_market"] == "\u7f8e\u56fd"
    assert orders["9000000000000005"]["language"] == "English"
    for o in orders.values():
        assert o["source_market"], "每单都必须有客源地（全部为入境接待）"


def test_record_evidence_ignores_unknown_order():
    svc, _ = make()
    assert svc.record_evidence("no-such-order", "call", "x") is None


def test_score_order_without_evidence_reports_reason():
    svc, _ = make()
    r = svc.score_order("9000000000000001", llm=None)
    assert r["ok"] is False and r["scored"] == 0
    assert "\u8bc1\u636e" in r["error"]


def test_order_scores_reflect_persisted_scores():
    svc, store = make()
    store.upsert_order_score("9000000000000001", "C1.1", 82, "M4", False,
                             [{"kind": "message", "quote": "您好，我是XX定制游的定制师"}],
                             "自报家门完整", "实战")
    r = svc.order_scores("9000000000000001")
    assert r["average"] == 82 and r["evaluated"] == 1
    point = next(p for d in r["dimensions"] for p in d["points"] if p["id"] == "C1.1")
    assert point["evaluated"] and point["level"] == "M4"
    assert point["evidence"][0]["quote"].startswith("\u60a8\u597d" or "")

def test_order_detail_has_platform_steps_and_contacts():
    svc, _ = make()
    d = svc.order_detail("9000000000000001")
    assert d is not None
    assert len(d["steps"]) == 8
    assert d["steps"][0]["state"] == "done"
    assert d["steps"][1]["state"] == "current"
    assert d["created_at"]
    assert len(d["contacts"]) >= 1
    assert {"time", "kind", "status", "has_record", "detail"} <= set(d["contacts"][0])


def test_order_detail_missing_order_returns_none():
    svc, _ = make()
    assert svc.order_detail("no-such-order") is None


def test_messages_grouped_with_counts():
    svc, _ = make()
    m = svc.messages("u1")
    assert m["messages"], "should seed at least one notice"
    assert all(msg["order_id"] for msg in m["messages"])
    # 分组计数：无子分类的取自身，有子分类的取子项之和
    total = 0
    for g in m["groups"]:
        total += sum(c["count"] for c in g["children"]) if g["children"] else g["count"]
    assert total == len(m["messages"])


def test_order_steps_mark_disabled_order_without_current():
    svc, _ = make()
    steps = svc.order_steps("9000000000000003")
    assert len(steps) == 8
    assert not any(s["urgent"] for s in steps)


# ---------------- 流程通关驱动 ----------------

def test_stage_zero_order_requires_real_actions():
    svc, _ = make()
    oid = "9000000000000006"
    g = svc.gate_report(oid)
    assert g["stage_index"] == 0 and g["passed"] is False
    assert {c["action"] for c in g["checks"]} == {"grab", "first_call", "deliverable:\u9700\u6c42\u786e\u8ba4\u5355"}

    out = svc.record_action(oid, "grab")
    assert out["recorded"] is True
    assert out["advance"]["advanced"] == [], "只抢单还不够，不应推进"
    assert svc.gate_report(oid)["done"] == 1


def test_record_action_is_idempotent_and_validates():
    svc, _ = make()
    oid = "9000000000000006"
    assert svc.record_action(oid, "grab")["recorded"] is True
    assert svc.record_action(oid, "grab")["recorded"] is False
    for args in ((oid, "no_such_action"), ("no-such-order", "grab")):
        try:
            svc.record_action(*args)
            raise AssertionError("\u5e94\u62a5\u9519")
        except ValueError:
            pass


def test_full_workflow_advances_to_done():
    """把阶段 0 的订单按门槛一路推到「订单完成」。"""
    svc, _ = make()
    oid = "9000000000000006"
    manual = ["customer_confirmed_plan", "contract_signed", "insurance_bought",
              "customer_signed_contract", "deposit_paid", "resources_locked",
              "pre_trip_notice", "settlement_verified", "balance_paid", "review_done"]
    svc.record_action(oid, "grab")
    svc.record_action(oid, "first_call")
    for kind in ("\u9700\u6c42\u786e\u8ba4\u5355", "\u884c\u7a0b\u65b9\u6848", "\u5206\u9879\u62a5\u4ef7"):
        svc.record_action(oid, f"deliverable:{kind}")
    svc.record_action(oid, "guard_pass:\u5206\u9879\u62a5\u4ef7")
    for a in manual:
        svc.record_action(oid, a)
    assert svc.get_order(oid)["stage_index"] == 7
    assert svc.gate_report(oid)["total"] == 0, "订单完成后没有剩余门槛"


def test_late_first_call_keeps_timeout_but_allows_resource_inquiry():
    from tripcraft.services.supplier_service import SupplierService

    svc, store = make()
    oid = "9000000000000006"
    svc._set_payload(oid, grabbed_at="2026-10-08T09:00:00")
    for action, at in (("grab", "2026-10-08T09:00:00"), ("first_call", "2026-10-08T11:30:00")):
        store.add_action(oid, action)
        store._exec("UPDATE order_action SET at=? WHERE order_id=? AND action=?", (at, oid, action))
    g = svc.gate_report(oid)
    check = next(c for c in g["checks"] if c["action"] == "first_call")
    assert check["ok"] is True and "超过" in check["reason"]
    assert store.has_action(oid, "deadline_miss:first_call")
    # 未产出需求确认单时仍然拦截；补齐后进入资源询价。
    assert svc.try_advance(oid)["advanced"] == []
    out = svc.record_action(oid, "deliverable:需求确认单")
    assert out["advance"]["advanced"] == [1]
    from tripcraft.services.journey_service import journey
    assert journey(store, oid)["current_stage"] == "pre2_plan"
    suppliers = SupplierService(store=store, llm=None, practice=svc)
    hub = suppliers.ensure_hub("u1")
    reply = suppliers.respond(hub["session_id"], "请核一下住宿和用车报价", order_id=oid)
    assert reply["deferred"] is False and reply["quote"]["kind"] == "地接社"
    assert store.quote(oid, "地接社")
    assert svc.dispatch_info(oid)["first_call"]["missed"] is True
    svc.try_advance(oid)
    assert len([e for e in store.events(oid) if e["type"] == "deadline_miss"]) == 1


def test_first_call_uses_order_limit_for_timeout_warning():
    svc, store = make()
    oid = "9000000000000006"
    svc._set_payload(oid, grabbed_at="2026-10-08T09:00:00", first_call_limit_min=120)
    for action, at in (("grab", "2026-10-08T09:00:00"), ("first_call", "2026-10-08T10:30:00")):
        store.add_action(oid, action)
        store._exec("UPDATE order_action SET at=? WHERE order_id=? AND action=?", (at, oid, action))
    check = next(c for c in svc.gate_report(oid)["checks"] if c["action"] == "first_call")
    assert check["ok"] is True and check["reason"] == ""
    assert not store.has_action(oid, "deadline_miss:first_call")


def test_seeded_orders_have_backfilled_actions():
    """种子里已在阶段 N 的订单，前序门槛动作应补齐，账本与阶段自洽。"""
    from tripcraft.services.workflow import gates_for
    svc, _ = make()
    for o in svc.list_orders("u1"):
        if o["status"] == "\u7981\u7528":
            continue
        for st in range(o["stage_index"]):
            for gate in gates_for(st):
                assert svc._store.has_action(o["order_id"], gate.action), \
                    f"{o['order_id']} 阶段 {o['stage_index']} 缺动作 {gate.action}"
