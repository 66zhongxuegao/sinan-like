"""空白演示账户：每次登录/退出都清空订单、学习、画像数据。"""

from __future__ import annotations

from .scenario_service import ScenarioService

USERNAME = "demo-blank"
DISPLAY_NAME = "新学员 · 空白画像"
PASSWORD = "Demo2026!"
DEMO_ASSESSMENT_SCORES = {
    "C1": 68.0, "C2": 55.0, "C3": 62.0, "C4": 58.0,
    "C5": 51.0, "C6": 46.0, "C7": 64.0, "C8": 57.0,
}


def normalize_assessment_scores(scores: dict) -> dict:
    """空白演示账号全选同一档时，换成分散、可信的演示画像。

    只处理 demo-blank；真实账号或已经做出差异化选择的答卷保持原分。
    """
    values = [float(v) for v in scores.values() if v is not None]
    if values and max(values) - min(values) < 0.1:
        return dict(DEMO_ASSESSMENT_SCORES)
    return scores


def reset_blank(ctx, user_id: str) -> dict:
    """把账号恢复到「刚注册、还没做画像测评」的空白状态。

    只删除该账号自己的数据，不碰其他账号；users 行和登录口令保留。
    """
    ScenarioService(ctx).reset(user_id, all_orders=True, include_profile=True)
    ctx.store.update_user_profile(user_id, {"display_name": DISPLAY_NAME})
    return {"ok": True, "username": USERNAME, "blank": True, "user_id": user_id}


def ensure_account(ctx, *, reset: bool = True) -> dict:
    """确保空白演示账号存在；可重复调用。"""
    auth = ctx.get_auth()
    store = auth.store
    user = store.user_by_name(USERNAME)
    if not user:
        user = auth.register(USERNAME, PASSWORD, display_name=DISPLAY_NAME, kind="demo")
    else:
        store.update_user_profile(user["user_id"], {"display_name": DISPLAY_NAME})
        store._exec("UPDATE users SET kind='demo' WHERE user_id=?", (user["user_id"],))
    if reset:
        reset_blank(ctx, user["user_id"])
    return store.user_by_name(USERNAME) or user
