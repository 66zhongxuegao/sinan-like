"""Conversation router: explicit order + explicit role, no silent guessing."""

import os
import tempfile
from uuid import uuid4

import pytest

from tripcraft.services.conversation_service import (
    ConversationError,
    ConversationService,
    ROLE_AGENCY,
    ROLE_HOTEL,
)
from tripcraft.storage import Store


def make_store() -> Store:
    store = Store(os.path.join(tempfile.gettempdir(), f"conv-route-{uuid4().hex}.sqlite"))
    store.upsert_order("9000000000001001", "route-user", "客户甲", "江苏", "正常", 1)
    store.upsert_order("9000000000001002", "route-user", "客户乙", "云南", "正常", 2)
    return store


def test_hub_requires_explicit_order_when_multiple_orders_are_active():
    store = make_store()
    store.upsert_session("hub", "route-user", "资源对接群", "资源方", ["我"],
                         order_id="", code="hub")
    svc = ConversationService(store)
    with pytest.raises(ConversationError) as exc:
        svc.resolve("hub", "route-user", text="酒店什么价？")
    assert exc.value.status == 409
    route = svc.resolve("hub", "route-user", order_id="9000000000001001",
                       text="酒店什么价？")
    assert route.order_id == "9000000000001001"
    assert route.target_role == ROLE_HOTEL
    assert route.agent_id == "practice.hub"


def test_dm_uses_its_own_order_and_role():
    store = make_store()
    store.upsert_session("hotel-dm", "route-user", "酒店销售", "酒店", ["我", "酒店·李"],
                         order_id="9000000000001002", code="dm-酒店")
    svc = ConversationService(store)
    route = svc.resolve("hotel-dm", "route-user", text="有房吗？")
    assert route.order_id == "9000000000001002"
    assert route.target_role == ROLE_HOTEL
    assert route.agent_id == "practice.supplier"


def test_explicit_target_role_wins_over_message_mention():
    store = make_store()
    store.upsert_session("hub", "route-user", "资源对接群", "资源方", ["我"],
                         order_id="", code="hub")
    svc = ConversationService(store)
    route = svc.resolve("hub", "route-user", order_id="9000000000001001",
                       text="酒店和车队都看一下", target_role="车队")
    assert route.target_role == "vehicle"
    assert route.reason == "explicit"


def test_cross_order_message_is_rejected():
    store = make_store()
    store.upsert_session("hotel-dm", "route-user", "酒店销售", "酒店", ["我", "酒店·李"],
                         order_id="9000000000001002", code="dm-酒店")
    svc = ConversationService(store)
    with pytest.raises(ConversationError) as exc:
        svc.resolve("hotel-dm", "route-user", order_id="9000000000001001",
                    text="这单换酒店")
    assert exc.value.status == 403
