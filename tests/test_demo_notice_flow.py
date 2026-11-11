"""演示单出团通知：客户读到通知正文并回执，随后进入行中突发事件。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.deliverable_service import DeliverableService
from tripcraft.services.director_service import DirectorService
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.services.tools_service import ToolsService
from tripcraft.storage import Store

ORDER = "9920000000000002"
USER = "demo-flow"


def make_demo_order():
    store = Store(os.path.join(tempfile.gettempdir(), f"demo-notice-{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    for sp in ("C6.1", "C6.2", "C6.3", "C6.5", "C6.7"):
        store.set_ability(USER, sp, teach=70, real_v=62, source="learning")
    store.upsert_order(
        ORDER, USER, "周先生", "广西", "正常", 4,
        payload={
            "source_market": "新加坡", "language": "中文", "destination": "广西",
            "party": "3 大 1 小", "dates": "2026-11-22 至 2026-11-26", "days": "5 天",
            "budget": "人均 6500 元", "hotel": "四星或同档次，含早",
            "demo_data": True, "showcase_realistic": True,
        },
    )
    store.add_action(ORDER, "grab", {"demo_orders": True})
    store.add_action(ORDER, "first_call", {"demo_orders": True})
    store.add_action(ORDER, "deliverable:需求确认单", {"demo_orders": True})
    store.add_action(ORDER, "resources_locked", {"demo_orders": True})
    supplier = SupplierService(store, practice=practice)
    supplier.add_contact(ORDER, "客户")
    supplier.add_contact(ORDER, "地接社")
    director = DirectorService(store, practice=practice)
    practice.attach_director(director)
    director.materialize_resource_pool(ORDER, "需要导游和司机", ["导游", "司机"], "桂林", "")
    supplier.add_contact(ORDER, "导游")
    supplier.add_contact(ORDER, "司机")
    svc = DeliverableService(store=store, practice=practice, tools=ToolsService(store=store, llm=None))
    return store, svc


def test_demo_departure_notice_ack_and_on_trip_incident(monkeypatch):
    monkeypatch.setenv("TRIPCRAFT_COMPETITION_EASY", "1")
    store, svc = make_demo_order()
    out = svc.submit(ORDER, "departure_notice", {
        "gather": "11 月 22 日 09:00 南宁吴圩机场", "guide": "导游 小周 138****",
        "contact": "定制师 小李 137****",
    })
    assert "出团通知书" in out["routing"]["customer_reply"]
    assert out["routing"]["asks"] == []
    assert store.order(ORDER)["stage_index"] == 5
    assert out["triggered_incidents"], "出团推进时产生的事件必须回传给前端"
    assert out["triggered_incidents"][0]["code"] == "INC-VEHICLE-BREAKDOWN"
    assert out["triggered_incidents"][0]["session_id"]
    assert store.incidents(ORDER)[0]["code"] == "INC-VEHICLE-BREAKDOWN"
