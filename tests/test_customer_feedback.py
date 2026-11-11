"""客户文档反馈：复述方案内容不能被误判成修改已确认需求。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.services.customer_card import asked_fact_keys
from tripcraft.services.customer_context import RECEIPTS, customer_messages, guarded_reply
from tripcraft.storage import Store

ORDER = "9000000000000938"
REFERENCE = """# 行程方案

## 出发 / 返程
2026-12-11 至 2026-12-16，共 6 天；客户原意向：春节前后

## 出行人数
夫妻二人

## 住宿
三星或同档次

## 分项报价
合计 8100 元，人均 4050 元
"""


def make_store() -> Store:
    store = Store(os.path.join(tempfile.gettempdir(), f"customer-feedback-{uuid4().hex}.sqlite"))
    store.upsert_order(ORDER, "feedback-user", "客户 X", "西藏", "正常", 1, payload={
        "source_market": "新加坡", "language": "中文", "destination": "西藏",
        "party": "夫妻二人", "dates": "春节前后", "days": "6 天",
        "budget": "人均 4500 元，不含往返大交通", "hotel": "三星或同档次",
    })
    return store


class FeedbackLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat_json(self, messages, **kwargs):
        self.calls += 1
        return {"reply": self.reply, "sentiment": "犹豫", "asks": []}


def test_feedback_can_quote_proposal_dates_and_prices_without_receipt_fallback():
    store = make_store()
    llm = FeedbackLLM("我看到了，12月11日出发比春节前后早，人均4050元是按这个方案算的吗？")
    out = guarded_reply(store, llm, ORDER, "plan", f"定制师发来的「行程方案」内容：\n{REFERENCE}",
                        reference=REFERENCE, feedback=True)
    assert llm.calls == 1
    assert out["consistency"]["fallback"] is False
    assert "12月11日" in out["reply"] and "4050" in out["reply"]
    card = store.ensure_customer_card(ORDER)
    assert card["fields"]["dates"]["value"] == "春节前后"
    assert card["fields"]["budget"]["value"] == "人均 4500 元，不含往返大交通"


def test_feedback_cannot_change_confirmed_facts_without_a_real_confirmation():
    store = make_store()
    llm = FeedbackLLM("日期改成12月20日，我们四个人。")
    out = guarded_reply(store, llm, ORDER, "plan", f"定制师发来的「行程方案」内容：\n{REFERENCE}",
                        reference=REFERENCE, feedback=True)
    assert llm.calls == 2
    assert out["consistency"]["fallback"] is True
    card = store.ensure_customer_card(ORDER)
    assert card["fields"]["dates"]["value"] == "春节前后"
    assert card["fields"]["party"]["value"] == "夫妻二人"
def test_old_safety_receipt_is_not_replayed_as_customer_memory():
    store = make_store()
    receipt = RECEIPTS["中文"]
    store.add_customer_turn(ORDER, "plan", "customer", receipt, "old-fallback")
    messages = customer_messages(
        store, ORDER, "plan", f"定制师发来的「行程方案」内容：\n{REFERENCE}", feedback=True,
    )
    assert not any(receipt == str(m.get("content") or "").strip() for m in messages[1:])

def test_mentioning_child_does_not_mean_asking_party_size():
    message = "赠送您和孩子的门票，并安排一次亲子体验，司机修好车就送您过去。"
    assert asked_fact_keys(message) == []
    assert asked_fact_keys("这次出行人数是多少？") == ["party"]
