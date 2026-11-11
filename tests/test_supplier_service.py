"""资源方群矩阵 / 订单级事实 / 阶段门控 离线测试（不联网，走模板兜底）。

对应 PRD 28.22 与 D-050：资源方骨架写死、措辞交给模型，
且**事件与事实必须同源**——群里说了酒店超售，酒店群里再问也必须是超售口径。
"""

import json
import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.services.director_service import DirectorService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import (SupplierService, _party,
                                                    destination_city, persist_destination_city)
from tripcraft.storage import Store

O1 = "9000000000000001"          # 江苏 · 阶段 1
O2 = "9000000000000002"          # 云南 · 阶段 2
O4 = "9000000000000004"          # 浙江 · 阶段 4（行前/行中可用）
O6 = "9000000000000006"          # 贵州 · 阶段 0（还没接单）


def make():
    path = os.path.join(tempfile.gettempdir(), f"sup_{uuid4().hex}.sqlite")
    store = Store(path)
    practice = PracticeService(store)
    practice.seed("u-demo")
    svc = SupplierService(store=store, llm=None, practice=practice)
    director = DirectorService(store=store, practice=practice, llm=None)
    return store, practice, svc, director


def group(svc, order_id, code):
    return svc.group_for(order_id, code)


def unlock(svc, practice, order_id, *kinds):
    """把测试需要的资源联系人准备好；城市级资源先由地接确认资源池。"""
    resource_kinds = [k for k in kinds if k in ("酒店", "车队", "导游", "司机")]
    if resource_kinds and "地接社" not in svc.added_contacts(order_id):
        svc.add_contact(order_id, "地接社")
    if resource_kinds:
        director = DirectorService(store=svc._store, practice=practice)
        row = svc._store.order(order_id)
        director.materialize_resource_pool(order_id, "测试资源询价", resource_kinds,
                                            destination_city(row), "")
    for kind in kinds:
        svc.add_contact(order_id, kind)


def test_hub_is_one_per_user_and_dms_are_per_person():
    """D-059：资源大群全局唯一；酒店/车队这些不再自动建群，加了才有单聊。"""
    store, practice, svc, _ = make()
    hub = svc.ensure_hub("u-demo")
    assert hub["session_id"] == svc.hub_id("u-demo")
    assert svc.ensure_hub("u-demo")["session_id"] == hub["session_id"]     # 幂等、全局唯一
    # 接单后平台自动指派地接：本单资源群和地接单聊同时出现
    groups = {g["code"]: g for g in svc.ensure_groups(O1)}
    assert "dm-地接社" in groups and svc.names(O1)["地接社"] in groups["hub"]["members"]
    # 同一学员的两个订单：客户是两个人，各有各的单聊，不会串
    unlock(svc, practice, O1, "客户")
    unlock(svc, practice, O2, "客户")
    assert svc.contact_dm("u-demo", "客户", O1) != svc.contact_dm("u-demo", "客户", O2)


def test_contact_gate_requires_requirement_before_resource_contacts():
    """首呼后只给客户；需求确认单提交后才开放地接与后续资源。"""
    store, practice, svc, _ = make()
    with pytest.raises(ValueError):
        svc.add_contact(O6, "客户")
    practice.record_action(O6, "grab")
    practice.record_action(O6, "first_call")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["客户"]["available"] is True
    assert cat["地接社"]["available"] is False
    with pytest.raises(ValueError):
        svc.add_contact(O6, "地接社")
    practice.record_action(O6, "deliverable:需求确认单")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["地接社"]["available"] is True


def test_quote_is_order_specific_and_persisted():
    store, _, svc, _ = make()
    q1 = svc.facts(O1, "酒店")                        # 江苏 → 南京四星 520
    q2 = svc.facts(O2, "酒店")                        # 云南 → 昆明四星 460
    assert q1["city"] == "南京" and q2["city"] == "昆明"
    assert q1["summary"] != q2["summary"]
    assert store.quote(O1, "酒店")["summary"] == q1["summary"]   # 落库


def test_quote_follows_constraint_change():
    store, _, svc, director = make()
    first = svc.facts(O1, "酒店")["summary"]
    store.set_supplier_state("u-demo", "酒店", {"price_factor": 1.5}, order_id=O1)
    second = svc.facts(O1, "酒店")["summary"]
    assert first != second                            # 约束一变，落库报价作废重算
    assert svc.facts(O2, "酒店")["summary"] != second   # 只影响这一单


def test_apply_fact_does_not_leak_to_other_orders():
    store, _, svc, director = make()
    svc.apply_fact(O1, "车队", {"availability": "无档期", "note": "车全派出去了"})
    a = svc.facts(O1, "车队")
    b = svc.facts(O2, "车队")
    assert a["availability"] == "无档期" and "车全派出去了" in a["note"]
    assert b["availability"] == "有货" and b["note"] == ""


def test_party_parsing():
    assert _party({"party": "3大1小"})["total"] == 4
    assert _party({"party": ""})["known"] is False
    assert _party({"party": ""})["adults"] == 2


def test_supplier_reply_uses_hard_facts():
    store, practice, svc, _ = make()
    unlock(svc, practice, O2, "地接社")
    sid = svc.contact_dm("u-demo", "地接社", O2)      # 地接单聊（阶段 2 ≥ 下限 1）
    out = svc.respond(sid, "云南这单四星和用车什么价？")
    assert out["deferred"] is False and out["sender"] == svc.names(O2)["地接社"]
    assert "460" in out["content"]                    # 昆明四星基准价
    assert out["quote"]["kind"] == "地接社"


def test_hub_reply_falls_back_to_latest_order():
    """资源大群没有"这一单"的上下文：以最近在跟的一单的地接口径回答。"""
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社")
    hub = svc.ensure_hub("u-demo")
    out = svc.respond(hub["session_id"], "四星和用车什么价？")
    assert out and out["content"] and out["sender"].endswith("经理")


def test_guide_group_needs_pre_trip_then_reports_incident():
    store, practice, svc, director = make()
    unlock(svc, practice, O4, "地接社", "导游")
    g = svc.group_for(O4, "guide")
    assert g and g["kind"] == "导游"
    idle = svc.respond(g["session_id"], "今晚安排好了吗？")
    assert idle["deferred"] is False and "按计划走" in idle["content"]

    fired = director.emit(O4, "pre_trip")             # 车辆故障（司导群）
    assert fired["injected"] and fired["injected"]["code"] == "INC-VEHICLE-BREAKDOWN"
    assert fired["injected"]["session_id"] == g["session_id"]

    hot = svc.respond(g["session_id"], "客人那边你稳住，换车多久能好？")
    assert hot["deferred"] is False
    assert "换车" in hot["content"] or "车出问题" in hot["content"]
    # 事件与事实同源：车队这一单必须变成无档期，别的单不受影响
    assert svc.facts(O4, "车队")["availability"] == "无档期"
    assert svc.facts(O1, "车队")["availability"] == "有货"


def test_customer_group_replies_in_character():
    store, practice, svc, _ = make()
    unlock(svc, practice, O1, "客户")
    cus = svc.group_for(O1, "customer")
    out = svc.respond(cus["session_id"], "您好，我是您的定制师，方案今晚发您。")
    assert out["sender"] == svc.names(O1)["客户"] and out["content"] and not out.get("locked")
    assert "教练" not in out["content"]


def test_contacts_follow_the_real_sequence():
    """接单→首呼只给客户；需求确认→地接；地接→酒店/车队；行前才给司导。"""
    store, practice, svc, _ = make()
    practice.record_action(O6, "grab")
    assert svc.contact_catalog(O6)[1]["available"] is False
    practice.record_action(O6, "first_call")
    svc.add_contact(O6, "客户")
    assert "客户" in svc.added_contacts(O6)
    practice.record_action(O6, "deliverable:需求确认单")
    svc.add_contact(O6, "地接社")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["酒店"]["available"] is False and cat["车队"]["available"] is False
    svc.respond(svc.ensure_hub("u-demo", O6)["session_id"], "大连要酒店和车队")
    cat = {c["kind"]: c for c in svc.contact_catalog(O6)}
    assert cat["酒店"]["available"] is True and cat["车队"]["available"] is True


def test_group_rename_and_invite():
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社", "导游", "司机")
    hub = svc.ensure_hub("u-demo")
    out = svc.rename(hub["session_id"], "我的资源群")
    assert out["name"] == "我的资源群"
    msgs = store.im_messages(hub["session_id"])
    assert any(m["kind"] == "system" and "群名已由" in m["content"] for m in msgs)
    res = svc.add_members(hub["session_id"], ["导游·测试", "陌生人"])
    assert res["rejected"] == ["导游·测试", "陌生人"]   # 没加过联系方式的人拉不进来


def test_contact_remark_is_shown_everywhere():
    """备注名：通讯录、单聊会话名、资源大群成员名三处都要跟着变。"""
    store, practice, svc, _ = make()
    unlock(svc, practice, O4, "地接社")
    cid = svc.added_contacts(O4)["地接社"]["contact_id"]
    svc.rename_contact(cid, "黄哥·云南地接")
    assert svc.added_contacts(O4)["地接社"]["remark"] == "黄哥·云南地接"
    sid = svc.contact_dm("u-demo", "地接社", O4)
    assert store.session(sid)["name"] == "黄哥·云南地接"
    hub = svc.ensure_hub("u-demo")
    assert "黄哥·云南地接" in svc._members(store.session(hub["session_id"]))


# ---------------- 回复体验：不重复前缀、不重复同一句 ----------------

def test_hub_reply_has_no_name_prefix():
    """名字在界面里已经显示，正文里不该再带「（姓名）」前缀。"""
    import inspect
    from tripcraft.services import supplier_service as ss

    src = inspect.getsource(ss.SupplierService._hub_reply)
    assert "（{who}）" not in src
    assert 'out["content"] = f"（' not in src


def test_defer_variants_differ():
    from tripcraft.services.supplier_service import DEFER_VARIANTS

    texts = {t.format(reason="需求还没确认完") for t in DEFER_VARIANTS}
    assert len(texts) == len(DEFER_VARIANTS) >= 3

def test_locked_contact_reports_the_missing_step():
    """拿不到联系人时给出下一步，而不是让学员猜为什么不能加。"""
    store, practice, svc, _ = make()
    practice.record_action(O6, "grab")
    practice.record_action(O6, "first_call")
    with pytest.raises(ValueError) as err:
        svc.add_contact(O6, "地接社")
    assert "需求确认单提交后" in str(err.value)



def test_resource_hub_is_order_scoped_and_excludes_customer():
    """资源对接群按订单创建，只含本单资源方；客户始终留在客户单聊/客户群。"""
    store, practice, svc, _ = make()
    unlock(svc, practice, O1, "客户", "地接社", "酒店")
    unlock(svc, practice, O2, "地接社", "酒店")
    hub1 = svc.ensure_hub("u-demo", O1)
    hub2 = svc.ensure_hub("u-demo", O2)
    assert hub1["session_id"] != hub2["session_id"]
    assert hub1["order_id"] == O1 and hub2["order_id"] == O2
    members1 = svc._members(store.session(hub1["session_id"]))
    assert svc.names(O1)["客户"] not in members1
    assert svc.names(O1)["地接社"] in members1
    assert svc.names(O1)["酒店"] in members1
    assert svc.names(O2)["地接社"] not in members1
    assert svc.names(O2)["酒店"] not in members1


def test_resource_hub_rejects_customer_invite():
    store, practice, svc, _ = make()
    unlock(svc, practice, O1, "客户", "地接社")
    hub = svc.ensure_hub("u-demo", O1)
    customer = svc.names(O1)["客户"]
    out = svc.add_members(hub["session_id"], [customer])
    assert out["blocked_customer"] == [customer]
    assert customer not in svc._members(store.session(hub["session_id"]))


def test_ensure_groups_uses_order_hub_without_customer_context():
    store, practice, svc, _ = make()
    unlock(svc, practice, O1, "客户", "地接社")
    hub = next(g for g in svc.ensure_groups(O1) if g["code"] == "hub")
    assert hub["session_id"] == svc.hub_id("u-demo", O1)
    assert hub["customer"] == "" and hub["destination"] == ""


def test_hub_dispatch_uses_only_real_members_and_keeps_context():
    store, practice, svc, _ = make()
    store.add_action(O1, "grab", {"test": True})
    hub = svc.ensure_hub("u-demo", O1)
    sid = hub["session_id"]
    names = svc.names(O1)

    # 接单后只自动带入平台指派的地接，酒店和司导不能凭空出现。
    assert svc._members(store.session(sid)) == ["我", names["地接社"]]
    first = svc.respond(sid, "酒店有没有四星房，什么价？")
    assert first["sender"] == names["地接社"], "先由地接确认资源和城市"
    assert "可添加列表" in first["content"]
    assert names["酒店"] not in svc._members(store.session(sid))

    store.add_im_message(sid, "我", "me", "酒店有没有四星房，什么价？")
    store.add_im_message(sid, first["sender"], "other", first["content"])
    follow = svc.respond(sid, "是大床房还是标间？")
    assert follow["sender"] == names["酒店"], "地接确认后，酒店追问由本城酒店接续"

    store.add_im_message(sid, "我", "me", "是大床房还是标间？")
    store.add_im_message(sid, follow["sender"], "other", follow["content"])
    guide = svc.respond(sid, "呼和浩特夫妻二人包车两天，需要司导")
    assert guide["sender"] == names["地接社"], "司导档期由地接统筹，不凭空生成导游"
    assert "排班" in guide["content"]

    store.add_im_message(sid, "我", "me", "呼和浩特夫妻二人包车两天，需要司导")
    store.add_im_message(sid, guide["sender"], "other", guide["content"])
    customer = svc.respond(sid, "是客户N内蒙古")
    assert customer["sender"] == "系统"
    assert names["客户"] not in svc._members(store.session(sid))


def test_resource_event_uses_actual_dmc_name():
    store, practice, svc, director = make()
    store.add_action(O1, "grab", {"test": True})
    svc.ensure_hub("u-demo", O1)
    speaker = director._speaker_name(store.order(O1), "XX地接·张经理")
    assert speaker == svc.names(O1)["地接社"]


def test_city_selection_controls_city_level_resources():
    store, practice, svc, _ = make()
    assert destination_city(store.order(O1)) == "南京"
    persist_destination_city(store, O1, "苏州")
    names = svc.names(O1)
    assert "苏州" in names["酒店"]
    assert "苏州导游" == names["导游"].split("·")[0]
    assert svc.facts(O1, "酒店")["city"] == "苏州"


def test_vehicle_and_ticket_questions_get_concrete_answers():
    store, practice, svc, _ = make()
    store.add_action(O1, "grab", {"test": True})
    hub = svc.ensure_hub("u-demo", O1)
    sid = hub["session_id"]
    car = svc.respond(sid, "3大1小，5座车多少钱一天？")
    assert "5座" in car["content"] and "/天" in car["content"]
    assert "18:00" not in car["content"]
    store.add_im_message(sid, "我", "me", "3大1小，5座车多少钱一天？")
    store.add_im_message(sid, car["sender"], "other", car["content"])
    ticket = svc.respond(sid, "门票多少钱")
    assert "首道门票" in ticket["content"]
    assert "18:00" not in ticket["content"]


def test_dmc_reply_materializes_city_resource_pool():
    store, practice, svc, _ = make()
    hub = svc.ensure_hub("u-demo", O2)
    out = svc.respond(hub["session_id"],
                      "10月21日去大理，要四星酒店、7座车和司导，老人少走路")
    assert out["sender"] == svc.names(O2)["地接社"]
    assert "大理" in out["content"] and "联系人已放到可添加列表" in out["content"]
    order = store.order(O2)
    pool = json.loads(order["payload"]).get("resource_pool") or {}
    assert pool["city"] == "大理"
    assert {"酒店", "车队", "导游", "司机"}.issubset(set(pool["kinds"]))
    cat = {c["kind"]: c for c in svc.contact_catalog(O2)}
    assert cat["酒店"]["available"] and cat["车队"]["available"]
    assert cat["导游"]["available"] and cat["司机"]["available"]
    assert "大理" in cat["酒店"]["name"] and "大理" in cat["导游"]["name"]


def test_ticket_office_is_fixed_window_for_public_transport_only():
    store, practice, svc, _ = make()
    ticket = svc.ensure_ticket_window("u-demo", O1)
    sid = ticket["session_id"]
    assert ticket["code"] == "ticket"
    out = svc.respond(sid, "10月21日，从西安北站到兵马俑，坐高铁")
    assert out["sender"] == "票务·陈"
    assert "10月21日" in out["content"] and "西安北站" in out["content"]
    assert "小时" in out["content"] and "元/人" in out["content"]
    private = svc.respond(sid, "包车从西安北站到兵马俑")
    assert "只负责公共交通" in private["content"]


def test_hub_switches_to_any_named_city_before_contact_reply():
    store, practice, svc, _ = make()
    hub = svc.ensure_hub("u-demo", O1)
    sid = hub["session_id"]
    first = svc.respond(sid, "江苏酒店一晚多少钱")
    assert first["sender"] == svc.names(O1)["地接社"]
    import json
    first_pool = json.loads((store.order(O1) or {}).get("payload") or "{}").get("resource_pool") or {}
    assert first_pool["city"] == "南京", "省名不能被当成城市"
    for city in ("宿迁", "无锡", "常州"):
        store.add_im_message(sid, "我", "me", f"{city}的酒店一晚多少钱")
        store.add_im_message(sid, first["sender"], "other", first["content"])
        out = svc.respond(sid, f"{city}的酒店一晚多少钱")
        assert out["sender"] == svc.names(O1)["地接社"]
        assert city in out["content"]
        assert "查不到" not in out["content"]
        import json
        pool = json.loads((store.order(O1) or {}).get("payload") or "{}").get("resource_pool") or {}
        assert pool["city"] == city
        first = out
