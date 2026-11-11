"""学习路线管家：画像驱动排序、需求加权与调整保留。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services import learning_route
from tripcraft.storage import Store

USER = "route-user"


def make():
    store = Store(os.path.join(tempfile.gettempdir(), f"route-{uuid4().hex}.sqlite"))
    store.upsert_order("9000000000000999", USER, "客户", "云南", "正常", 0, payload={})
    store.set_ability(USER, "C1.1", teach=82, source="initial")
    store.set_ability(USER, "C1.2", teach=58, source="initial")
    store.set_ability(USER, "C2.1", teach=55, source="initial")
    store.set_ability(USER, "C5.1", teach=48, source="initial")
    store.set_ability(USER, "C5.2", teach=62, source="initial")
    store.set_ability(USER, "C8.1", teach=70, source="initial")
    return store


def test_generate_route_is_linear_and_persisted():
    store = make()
    route = learning_route.generate_route(store, USER, "想提升报价和预算沟通")
    assert len(route["items"]) == learning_route.ROUTE_SIZE
    assert [x["order"] for x in route["items"]] == list(range(1, 17))
    assert sum(t["count"] for t in route["tiers"]) == len(route["items"])
    assert any(x["id"].startswith("C5.") for x in route["items"][:6])
    saved = learning_route.latest_route(store, USER)
    assert saved["route_id"] == route["route_id"]
    assert saved["demand"] == "想提升报价和预算沟通"


def test_revise_route_keeps_conversation_and_repioritizes_need():
    store = make()
    learning_route.generate_route(store, USER, "先补沟通")
    revised = learning_route.revise_route(store, USER, "最近要接入境客人，把跨文化放到最前")
    assert any(x["role"] == "user" and "入境" in x["text"] for x in revised["messages"])
    assert any(x["id"].startswith("C8.") for x in revised["items"][:8])
    assert learning_route.latest_route(store, USER)["revision"].startswith("最近要接入境客人")

def test_revise_route_can_demote_a_previously_prioritized_dimension():
    store = make()
    learning_route.generate_route(store, USER, "先补入境和跨文化")
    revised = learning_route.revise_route(store, USER, "跨文化先放后面，报价更着急")
    positions = [i for i, x in enumerate(revised["items"]) if x["dimension"] == "C8"]
    assert positions and min(positions) >= 7
    assert any(x["dimension"] == "C5" for x in revised["items"][:4])
    assert "往后排" in revised["summary"]
