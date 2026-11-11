"""完整模板的离线回归：只使用内存库，不调用模型或真实账号。"""
import json

import pytest

from tripcraft.contracts.deliverables_spec import BY_ID, resolve
from tripcraft.services.deliverable_service import DeliverableError, DeliverableService
from tripcraft.services.guard_service import GuardService
from tripcraft.storage import Store


class CountingGuard(GuardService):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.reject = False

    def check(self, *args, **kwargs):
        self.calls += 1
        result = super().check(*args, **kwargs)
        if self.reject:
            result.update(blocked=True, reasons=["测试合规冲突"])
        return result


@pytest.fixture
def sample():
    store = Store(":memory:")
    guard = CountingGuard()
    store.upsert_order("complete-template", "test-user", "客户甲", "福建", "进行中", 0, {})
    try:
        yield store, DeliverableService(store, guard=guard), guard
    finally:
        store.close()


def draft(store, code):
    return json.loads(store.deliverable_draft("complete-template", resolve(code).id)["values_json"])


@pytest.mark.parametrize("payload", [
    {},
    {"party": "3 大 1 小", "dates": "2026-11-12 至 2026-11-16", "days": "5 天", "budget": "人均 5000 元", "source_market": "台湾"},
    {"party": "两个人", "days": "1 天", "source_market": "内地"},
    {"party": "4 人", "days": "3 天", "budget": "总计 2 万", "source_market": "沙特", "special": "清真餐食，无猪肉及酒精"},
])
def test_complete_import_then_submit_all_documents(sample, payload):
    store, service, guard = sample
    # 重建该单事实卡，让每种场景独立进入首次填写状态。
    store._exec("DELETE FROM order_customer WHERE order_id=?", ("complete-template",))
    store.upsert_order("complete-template", "test-user", "客户甲", "福建", "进行中", 0, payload)
    result = service.import_templates("complete-template")
    assert result["count"] == 8 and result["ready_to_submit"]
    assert not store.deliverables("complete-template")
    assert not store.sessions("test-user")
    for spec in BY_ID.values():
        values = draft(store, spec.code)
        assert all(values.get(f.key) not in (None, "", []) for f in spec.fields)
        assert all(values[f.key] in f.options for f in spec.fields if f.type == "select")
        if payload.get("source_market") == "沙特" and spec.code == "itinerary":
            assert all("清真" in row["meal"] for row in values["days"])
        # 模拟浏览器 JSON 往返，将整值浮点数转为整数。
        values = json.loads(json.dumps(values), parse_float=lambda raw: int(float(raw)) if float(raw).is_integer() else float(raw))
        out = service.submit("complete-template", spec.id, values, submit_once=True)
        assert not out["blocked"], (spec.code, out)
        assert service.submit("complete-template", spec.code, values, submit_once=True)["already_submitted"]
    assert len(store.deliverables("complete-template")) == 8
    assert guard.calls == 4, "未修改的模板应复用导入预检结果"
    assert service.import_templates("complete-template")["count"] == 0


def test_import_is_stable_and_documents_share_amounts(sample):
    store, service, _ = sample
    service.import_templates("complete-template")
    first = {code: draft(store, code) for code in ("quotation", "contract", "settlement", "review")}
    service.import_templates("complete-template", {"quotation": {"total": "", "cost": "待确认"}})
    assert first == {code: draft(store, code) for code in first}
    quote, contract, settlement, review = (first[code] for code in first)
    assert round(sum(row["amount"] for row in quote["items"]), 2) == quote["total"]
    assert settlement["total_ours"] == quote["total"]
    assert settlement["actual_cost"] == quote["cost"]
    assert review["profit"] == settlement["actual_margin"]
    assert contract["deposit"] == round(quote["total"] * .3, 2)
    assert all(field["state"] != "unknown" for field in store.ensure_customer_card("complete-template")["fields"].values())
    assert any(event["kind"] == "simulated" for event in store.customer_fact_events("complete-template"))


def test_edited_template_and_changed_facts_run_guard_again(sample):
    store, service, guard = sample
    service.import_templates("complete-template")
    guard.reject = True
    values = draft(store, "requirement_sheet")
    values["freeform"] += " 客户新增内容"
    assert service.submit("complete-template", "requirement_sheet", values)["blocked"]
    assert not store.deliverables("complete-template")
    values = draft(store, "itinerary")
    store.complete_template_identity("complete-template", {"destination": "不会覆盖已有目的地"})
    # 新事实会使预检证书失效。
    card = store.ensure_customer_card("complete-template")
    card["fields"]["special"]["value"] = "客户新增饮食禁忌"
    store._exec("UPDATE order_customer SET card_json=? WHERE order_id=?", (json.dumps(card), "complete-template"))
    assert service.submit("complete-template", "itinerary", values)["blocked"]
    assert guard.calls == 6


def test_blocked_precheck_does_not_persist_bad_documents(sample):
    store, service, guard = sample
    guard.reject = True
    with pytest.raises(DeliverableError, match="预检未通过"):
        service.import_templates("complete-template")
    assert not store._all("SELECT * FROM deliverable_draft")
    assert not store.deliverables("complete-template")
    assert not store.sessions("test-user")


def test_preserve_usable_draft_quote_and_supplement_customer_hints(sample):
    store, service, _ = sample
    service.import_templates("complete-template", {
        "requirement_sheet": {"people": "2 人", "dates": "2026-11-20 至 2026-11-22", "budget": "总预算 25000 元"},
        "quotation": {"total": 20001.51, "cost": 15000,
                      "items": [{"name": "组合服务含保险", "amount": 20001.51}]},
    })
    quote = draft(store, "quotation")
    assert quote["total"] == 20001.51 and quote["cost"] == 15000
    assert quote["people"] == "2 人"
    assert len(draft(store, "itinerary")["days"]) == 3
    settlement = draft(store, "settlement")
    service.import_templates("complete-template")
    assert quote == draft(store, "quotation")
    assert settlement == draft(store, "settlement")
