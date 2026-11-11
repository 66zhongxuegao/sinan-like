"""创建方案 → 发送方案 → 客户已读 → 客户确认 的离线测试（不联网）。"""

import os
import tempfile
from datetime import datetime, timedelta
from uuid import uuid4

from tripcraft.services.deliverable_service import DeliverableService
from tripcraft.services.plan_service import PlanService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

ORDER = "9000000000000004"      # 浙江单，阶段 4

DAYS = [
    {"day": "D1", "time": "14:00", "transport": "专车 40 分", "spot": "西湖", "meal": "晚 杭帮菜",
     "hotel": "西湖四星", "guide": "导游·王"},
    {"day": "D2", "time": "09:00", "transport": "专车 1 时", "spot": "灵隐寺", "meal": "午 素斋",
     "hotel": "西湖四星", "guide": "导游·王"},
]


def make():
    path = os.path.join(tempfile.gettempdir(), f"plan_{uuid4().hex}.sqlite")
    store = Store(path)
    practice = PracticeService(store)
    practice.seed("u-demo")
    svc = DeliverableService(store=store, practice=practice)
    plan = PlanService(store=store, practice=practice, deliverable=svc, tools=None)
    sup = SupplierService(store, practice=practice)
    return store, practice, svc, plan, sup


def _values(title="浙江 5 天亲子行程"):
    return {"title": title, "dates": "2026-11-01 至 11-05", "people": "2 大 1 小", "days": DAYS,
            "sections": [{"title": "交通与用车", "body": "7 座商务，含司机油费"}]}


def test_plan_flow_create_send_read_confirm():
    store, practice, svc, plan, sup = make()
    sup.add_contact(ORDER, "客户")                 # 首呼已回填动作，客户可加
    customer_room = sup.group_for(ORDER, "customer")["session_id"]

    # ① 创建：草稿，不动门槛
    p = plan.create(ORDER, _values())
    assert p["status"] == "草稿" and p["version"] == 1
    # 草稿不投递：客户群里还没有方案卡片
    assert not [m for m in store.im_messages(customer_room) if m["kind"] == "card"]

    # ② 发送：投卡片给客户，但客户还没读（不立刻回复）
    out = plan.send(ORDER, p["plan_id"], targets=[customer_room])
    assert out["ok"] and out["plan"]["status"] == "已发送"
    assert store.has_action(ORDER, "deliverable:行程方案")     # 交付物链路照走
    cards = [m for m in store.im_messages(customer_room) if m["kind"] == "card"]
    assert cards and "行程方案" in cards[-1]["content"]
    assert out["plan"]["read"] is False

    # ③ 到点后客户才读：状态变已读，反馈进客户群，并留一条「客户已读」证据
    store.update_plan(p["plan_id"], read_due_at=(datetime.now() - timedelta(seconds=5))
                      .strftime("%Y-%m-%d %H:%M:%S"))
    got = plan.list(ORDER)[0]
    assert got["status"] == "已读" and got["read_at"]
    assert got["feedback"]
    assert any(m["role"] == "other" for m in store.im_messages(customer_room))
    assert any(e["kind"] == "客户已读" for e in store.evidence(ORDER))

    # ④ 已读之后才允许登记客户确认
    conf = plan.confirm(ORDER, p["plan_id"])
    assert conf["ok"] and store.has_action(ORDER, "customer_confirmed_plan")


def test_confirm_before_read_is_rejected():
    store, practice, svc, plan, sup = make()
    sup.add_contact(ORDER, "客户")
    p = plan.create(ORDER, _values())
    plan.send(ORDER, p["plan_id"], targets=[sup.group_for(ORDER, "customer")["session_id"]])
    r = plan.confirm(ORDER, p["plan_id"])
    assert r["ok"] is False and "还没读" in r["error"]


def test_sent_plan_cannot_be_edited():
    store, practice, svc, plan, sup = make()
    sup.add_contact(ORDER, "客户")
    p = plan.create(ORDER, _values())
    plan.send(ORDER, p["plan_id"], targets=[sup.group_for(ORDER, "customer")["session_id"]])
    try:
        plan.update(ORDER, p["plan_id"], _values("改一版"))
    except ValueError as exc:
        assert "另建一版" in str(exc)
    else:
        raise AssertionError("已发送的方案不应允许改动")


def test_new_version_increments():
    store, practice, svc, plan, sup = make()
    plan.create(ORDER, _values("第一版"))
    v2 = plan.create(ORDER, _values("第二版"))
    assert v2["version"] == 2 and len(store.plans(ORDER)) == 2
