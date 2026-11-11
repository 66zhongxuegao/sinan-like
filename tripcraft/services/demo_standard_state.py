"""标准案例「毛毛」演示账号：退出时重建固定案例订单。"""

from __future__ import annotations

import json

from .scenario_service import ScenarioService, default_case_id

USERNAME = "demo-20261018"
DISPLAY_NAME = "途悠国际旅行社定制师毛毛"


def reset_standard(ctx, user_id: str) -> dict:
    """清掉该账号的固定案例订单并重新导入，保留画像数据。

    只在标准案例「毛毛」演示账号退出时调用；不要用于 verified 成品账号。
    """
    store = ctx.store
    case_id = ""
    for order in store.orders(user_id):
        try:
            payload = json.loads(order.get("payload") or "{}")
        except (TypeError, ValueError):
            continue
        case_id = str(payload.get("scenario_id") or "")
        if case_id:
            break
    case_id = case_id or default_case_id()

    svc = ScenarioService(ctx)
    svc.reset(user_id, case_id=case_id, include_profile=False)
    imported = svc.import_case(user_id, case_id)
    store.update_user_profile(user_id, {"display_name": DISPLAY_NAME})
    return {"ok": True, "username": USERNAME, "case_id": case_id,
            "order_id": imported.get("order_id", ""), "rebuilt": True}
