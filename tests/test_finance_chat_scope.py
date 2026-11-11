"""财务追偿只发生在资源会话，并且发言人必须落到本单具体司机/资源联系人。"""

import os
import tempfile
from uuid import uuid4

from tripcraft.api.routers.calls import _finance_speaker_name, _is_resource_chat
from tripcraft.services.practice_service import PracticeService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.storage import Store

ORDER = "9000000000000004"


def make():
    store = Store(os.path.join(tempfile.gettempdir(), f"finance-chat-{uuid4().hex}.sqlite"))
    practice = PracticeService(store)
    practice.seed("u-demo")
    return store, SupplierService(store, practice=practice)


def test_customer_dm_never_triggers_resource_attribution():
    assert not _is_resource_chat("dm", "客户", "客户")
    assert _is_resource_chat("hub", "资源方", "地接社")
    assert _is_resource_chat("dm", "司机", "司机")


def test_vehicle_attribution_uses_this_orders_specific_driver():
    store, svc = make()
    speaker = _finance_speaker_name(svc, ORDER, "车队", {"kind": "客户", "name": "客户 D"})
    assert speaker != "车队"
    assert speaker == svc.names(ORDER)["司机"]
    assert "司机" in speaker
