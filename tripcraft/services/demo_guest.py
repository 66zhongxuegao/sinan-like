"""演示账号「一人一份」：多人同时用同一个演示账号登录时互不影响。

问题：demo-blank / demo-flow 原先是一个共享 user_id。B 登录会触发复位、清空 A 正在做的订单
和画像；A 退出又会清空 B 的数据；两人同时在线看到的是同一份订单与画像。

做法：演示账号只作为「模板」出现在登录页。用模板账号登录时：
  1. 新建一个临时访客账号 `<模板名>-g<8位hex>`（kind=demo，随机口令，从不下发）；
  2. 按模板的初始化函数把访客账号铺成模板的初始状态；
  3. 会话签给访客账号 —— 之后所有读写都落在访客自己的 user_id 上，按 user_id 天然隔离。
访客退出时整号删除；长时间不活跃（默认 12 小时）的访客在下次有人用模板登录时顺带清理。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Callable

from . import demo_blank_state, demo_stage_state
from .scenario_service import ScenarioService

GUEST_TTL_HOURS = 12
_GUEST_RE = re.compile(r"^(?P<template>.+)-g[0-9a-f]{8}$")


def _templates() -> dict[str, Callable]:
    """模板用户名 → 初始化函数(ctx, user_id)。标准案例账号（毛毛）为内部演示实例专用，不在此列。"""
    return {
        demo_blank_state.USERNAME: demo_blank_state.reset_blank,
        demo_stage_state.USERNAME: demo_stage_state.reset_initial,
    }


def is_template(username: str) -> bool:
    return (username or "") in _templates()


def template_of(username: str) -> str:
    """访客账号对应的模板名；不是访客返回空串。"""
    m = _GUEST_RE.match(username or "")
    return m.group("template") if m and m.group("template") in _templates() else ""


def is_guest(username: str) -> bool:
    return bool(template_of(username))


def is_blank_like(username: str) -> bool:
    """空白演示模板本身或它的访客（用于测评打分口径等特殊处理）。"""
    return username == demo_blank_state.USERNAME or template_of(username) == demo_blank_state.USERNAME


def start_guest(ctx, template: str) -> dict:
    """为一次模板登录创建并初始化访客账号，返回 auth.login 的会话 dict（含 token）。"""
    init = _templates()[template]
    auth = ctx.get_auth()
    try:
        purge_stale(ctx)
    except Exception:  # noqa: BLE001 - 清理失败不阻断登录
        pass
    tpl_row = ctx.store.user_by_name(template) or {}
    password = secrets.token_urlsafe(18)
    for _ in range(5):
        name = f"{template}-g{secrets.token_hex(4)}"
        if not ctx.store.user_by_name(name):
            break
    user = auth.register(name, password, display_name=tpl_row.get("display_name") or template, kind="demo")
    init(ctx, user["user_id"])
    return auth.login(name, password)


def delete_guest(ctx, user_id: str) -> None:
    """删除访客账号及其全部数据（只允许删访客，模板与真实账号不会被误删）。"""
    row = ctx.store.user_by_id(user_id) or {}
    if not is_guest(row.get("username") or ""):
        return
    ScenarioService(ctx).reset(user_id, all_orders=True, include_profile=True)
    ctx.store._exec("DELETE FROM sessions WHERE user_id=?", (user_id,))
    ctx.store._exec("DELETE FROM users WHERE user_id=?", (user_id,))


def purge_stale(ctx, hours: int = GUEST_TTL_HOURS) -> int:
    """清理超过 `hours` 小时没有活动的访客账号，返回删除个数。"""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = ctx.store._all(
        "SELECT u.user_id, u.username, u.created_at, "
        "MAX(COALESCE(NULLIF(s.last_seen_at,''), s.created_at)) AS last_active "
        "FROM users u LEFT JOIN sessions s ON s.user_id = u.user_id "
        "WHERE u.kind='demo' GROUP BY u.user_id")
    n = 0
    for r in rows:
        if not is_guest(r.get("username") or ""):
            continue
        last = r.get("last_active") or r.get("created_at") or ""
        if last and last < cutoff:
            delete_guest(ctx, r["user_id"])
            n += 1
    return n
