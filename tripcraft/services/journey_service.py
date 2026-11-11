"""六阶段旅程投影（journey 域）——把底层「8 态平台状态 + 13 步考核」收敛成用户确认的 6 阶段。

阶段口径的**唯一来源**是 `tripcraft/contracts/stages.py`（Lead 冻结 v1）：本模块只做投影，
不重新定义阶段、不复制阶段表。

对外（供 `tripcraft/api/routers/practice.py` 与 `deliverables.py` 使用，均为无状态纯函数，
不持有可变单例，避免同一 app 内出现第二套状态）：

- `stages_payload()`                      → 原样透传契约（前端 `/practice/stages`）
- `journey(store, order_id)`              → 六阶段进度 + 子步骤状态 + 唯一下一步动作
- `deliverable_list(store, items, ...)`   → 给交付物列表补齐 stage/stage_name/in_current_stage/is_next
- `annotate_submission(store, order_id, out)` → 给提交回执补 delivered / receipt / next_action

子步骤完成判定说明：能直接对应「学员动作账本」或「交付物文档」的一律按真实记录判定；
行中服务（S10）的三个子步骤只能按「已出团 + 是否有导演事件 / 证据」近似，属于**近似判定**，
已在 `SUBSTEP_APPROX` 标注，前端不得据此对外宣称"系统自动播放了行中"。
"""

from __future__ import annotations

from datetime import datetime

from ..contracts.deliverables_spec import BY_ID, PRACTICE_FINAL_CODES, resolve
from ..contracts.stages import STAGE_ORDER, STAGES, STAGES_BY_ID, deliverable_stage

# 平台 8 态（practice_service.ORDER_STEPS）→ 六阶段 id。
# 定位依据是「当前平台态下**还剩什么没做**」：
#   0 定制师接单      → 行前1（抢单 / 首呼 / 需求确认单）
#   1 定制师提供方案  → 行前2（询价 / 逐日行程；报价单在此窗口产出，但归属行前3）
#   2 客户确认方案    → 行前3（报价与成交确认）
#   3 定制师提供合同  → 行前3（等客户回签 / 定金，剩下的是合同类子项）
#   4 客户确认合同    → 行前4（只剩资源锁定 + 出团通知书）
#   5 客户出团        → 行中服务
#   6 定制师提交结算  → 行后复盘
#   7 订单完成        → 行后复盘（全部完成）
PLATFORM_STAGE_TO_JOURNEY: tuple[str, ...] = (
    "pre1_requirement", "pre2_plan", "pre3_quote", "pre3_quote",
    "pre4_notice", "on_trip", "post_trip", "post_trip",
)

PLATFORM_STAGE_MAX = 7

# 行中服务的近似判定（见模块 docstring）
SUBSTEP_APPROX: frozenset[str] = frozenset({"on.execute", "on.incident", "on.comm"})

# 子步骤 → 下一步动作的落点
_SUBSTEP_DELIVERABLE: dict[str, str] = {
    "pre1.clarify": "requirement_sheet", "pre1.confirm": "requirement_sheet",
    "pre2.quote": "resource_quote", "pre2.tradeoff": "resource_quote",
    "pre2.day": "itinerary", "pre2.submit": "itinerary",
    "pre3.price": "quotation", "pre3.margin": "quotation",
    "pre3.contract": "contract",
    "pre4.prepare": "contract", "pre4.notice": "departure_notice",
    "post.settle": "settlement", "post.review": "review",
}

_DELIVERABLE_CN = {d.code: d.id for d in BY_ID.values()}


def _platform_stage_name(idx: int) -> str:
    try:
        from .practice_service import ORDER_STEPS      # 惰性导入，避免与路由装配顺序耦合
        return ORDER_STEPS[min(max(idx, 0), len(ORDER_STEPS) - 1)]
    except Exception:
        return ""


def stages_payload() -> dict:
    """前端 `/practice/stages`：原样透传六阶段契约（不改字段、不加工）。"""
    from ..contracts.stages import as_payload
    return as_payload()


# ---------------------------------------------------------------- 事实采集

def _facts(store, order_id: str) -> dict:
    docs = {r["deliverable_id"]: r for r in store.deliverables(order_id)}
    plans = store.plans(order_id)
    actions = store.action_keys(order_id)
    events = store.events(order_id)
    event_types = {(r.get("type") or r.get("type_") or "") for r in events}
    versions = [int(p.get("version") or 0) for p in plans]
    return {
        "actions": actions,
        "docs": docs,
        "plan_count": len(plans),
        "plan_max_version": max(versions) if versions else 0,
        "plan_sent": any((p.get("status") or "") in ("已发送", "已读", "客户已确认")
                         or p.get("sent_at") for p in plans),
        "plan_read": any(p.get("read_at") or (p.get("status") or "") in ("已读", "客户已确认")
                         for p in plans),
        "plan_feedback": any((p.get("feedback") or "").strip() for p in plans),
        "event_types": {t for t in event_types if t},
        "incidents": len(store.incidents(order_id)),
        "evidence_kinds": {(r.get("kind") or "") for r in store.evidence(order_id)},
        "has_scores": bool(store.order_scores(order_id)),
    }


_SUBSTEP_RULES: dict[str, str] = {
    "pre1.brief": "always",
    "pre1.grab": "action:grab",
    "pre1.call": "action:first_call",
    "pre1.clarify": "doc:需求确认单|action:first_call",
    "pre1.confirm": "doc:需求确认单",
    "pre2.quote": "doc:资源询价记录|evidence:供应商询价",
    "pre2.tradeoff": "doc:资源询价记录|evidence:供应商询价",
    "pre2.day": "doc:行程方案",
    "pre2.feedback": "plan_sent",
    "pre2.submit": "doc:行程方案",
    "pre3.price": "doc:分项报价",
    "pre3.margin": "doc:分项报价",
    "pre3.iterate": "plan_versions>=2|plan_read|plan_feedback",
    "pre3.deal": "action:customer_confirmed_plan",
    "pre3.contract": "doc:合同与保险",
    "pre4.lock": "action:resources_locked",
    "pre4.prepare": "action:insurance_bought",
    "pre4.notice": "doc:出团通知书",
    "on.execute": "action:depart",
    "on.incident": "incidents|event:incident_injected",
    "on.comm": "action:depart&evidence:*",
    "post.settle": "doc:地接结算核对单",
    "post.score": "has_scores|action:review_done",
    "post.review": "doc:回访与复盘记录",
}


def _rule_hit(rule: str, f: dict) -> bool:
    for part in rule.split("|"):
        part = part.strip()
        if not part:
            continue
        if part == "always":
            return True
        if part.startswith("action:"):
            if part[7:] in f["actions"]:
                return True
        elif part.startswith("doc:"):
            if part[4:] in f["docs"]:
                return True
        elif part.startswith("evidence:"):
            kind = part[9:]
            if kind == "*":
                if f["evidence_kinds"] - {""}:
                    return True
            elif kind in f["evidence_kinds"]:
                return True
        elif part.startswith("event:"):
            if part[6:] in f["event_types"]:
                return True
        elif part == "plan_sent":
            if f["plan_sent"]:
                return True
        elif part == "plan_read":
            if f["plan_read"]:
                return True
        elif part == "plan_feedback":
            if f["plan_feedback"]:
                return True
        elif part.startswith("plan_versions>="):
            try:
                if f["plan_max_version"] >= int(part.split(">=", 1)[1]):
                    return True
            except ValueError:
                pass
        elif part == "incidents":
            if f["incidents"] > 0:
                return True
        elif part == "has_scores":
            if f["has_scores"]:
                return True
    return False


def _substep_done(substep_id: str, f: dict) -> bool:
    rule = _SUBSTEP_RULES.get(substep_id, "")
    if not rule:
        return False
    if "&" in rule:
        return all(_rule_hit(seg, f) for seg in rule.split("&") if seg.strip())
    return _rule_hit(rule, f)


# ---------------------------------------------------------------- 定位

def current_stage_index(order: dict) -> int:
    """订单当前落在六阶段的第几段（0-based）。平台态 7 = 订单完成 → 最后一段且已完成。"""
    idx = int(order.get("stage_index") or 0)
    if idx >= PLATFORM_STAGE_MAX:
        return len(STAGES) - 1
    stage_id = PLATFORM_STAGE_TO_JOURNEY[min(max(idx, 0), len(PLATFORM_STAGE_TO_JOURNEY) - 1)]
    try:
        return STAGE_ORDER.index(stage_id)
    except ValueError:
        return 0


def _route_for(order_id: str, substep_id: str, deliverable: str) -> tuple[str, str, str]:
    """返回 (kind, route, deliverable_code)。"""
    if substep_id == "pre1.grab":
        return "action", "/practice/messages", ""
    if substep_id == "pre1.call":
        return "call", f"/practice/orders/{order_id}/call", ""
    if substep_id in ("pre2.feedback", "pre3.iterate") or deliverable == "itinerary":
        return "plan", f"/practice/orders/{order_id}/plan/new", deliverable or "itinerary"
    # S4 资源询价：谈价发生在资源对接群（聊天界面），不是填台账
    if substep_id == "pre2.quote":
        return "im", "/practice/im", ""
    # S8 成交确认：客户确认按钮在《行程方案》页（登记客户已确认方案）
    if substep_id in ("pre3.deal",):
        return "plan", f"/practice/orders/{order_id}/plan/new", ""
    if substep_id in ("pre4.lock", "on.execute", "on.incident", "on.comm"):
        return "im", "/practice/im", ""
    if substep_id == "post.score":
        return "score", f"/practice/orders/{order_id}/score", ""
    if deliverable:
        return ("deliverable",
                f"/practice/orders/{order_id}/deliverables?code={deliverable}",
                deliverable)
    return "action", f"/practice/orders/{order_id}", ""


def _next_action(order_id: str, stages: list[dict]) -> dict | None:
    """当前阶段内第一个未完成子步骤 → 唯一下一步动作；本阶段做完就看后面阶段。"""
    for st in stages:
        for sub in st["substeps"]:
            if sub["done"]:
                continue
            deliverable = sub.get("deliverable") or _SUBSTEP_DELIVERABLE.get(sub["id"], "")
            kind, route, code = _route_for(order_id, sub["id"], deliverable)
            return {
                "kind": kind, "stage": st["id"], "substep": sub["id"],
                "deliverable": code, "label": sub["name"], "detail": sub["hint"],
                "route": route,
            }
    return None


# ---------------------------------------------------------------- 主投影

def journey(store, order_id: str) -> dict | None:
    """订单 → 六阶段旅程投影。订单不存在返回 None。"""
    order = store.order(order_id)
    if not order:
        return None
    platform_stage = int(order.get("stage_index") or 0)
    all_done = platform_stage >= PLATFORM_STAGE_MAX
    cur = current_stage_index(order)
    f = _facts(store, order_id)

    stages: list[dict] = []
    for i, st in enumerate(STAGES):
        if all_done or i < cur:
            state = "done"
        elif i == cur:
            state = "current"
        else:
            state = "todo"

        subs: list[dict] = []
        for sub in st.substeps:
            done = _substep_done(sub.id, f)
            sub_state = "done" if done else ("current" if state == "current" and not done else "todo")
            sub_deliverable = sub.deliverable or _SUBSTEP_DELIVERABLE.get(sub.id, "")
            sub_kind, sub_route, _sub_code = _route_for(order_id, sub.id, sub_deliverable)
            item = {"id": sub.id, "name": sub.name, "hint": sub.hint, "step": sub.step,
                    "deliverable": sub_deliverable, "route": sub_route, "kind": sub_kind,
                    "state": sub_state, "done": done}
            if sub.id in SUBSTEP_APPROX:
                item["approx"] = True
            subs.append(item)

        docs = []
        for code in st.deliverables:
            spec = resolve(code)
            row = f["docs"].get(spec.id) if spec else None
            docs.append({"code": code, "title": spec.title if spec else code,
                         "submitted": bool(row),
                         "version": int((row or {}).get("version") or 0)})

        done_count = sum(1 for s in subs if s["done"])
        stages.append({
            "id": st.id, "name": st.name, "short": st.short, "order": st.order,
            "focus": st.focus, "primary_deliverable": st.primary_deliverable,
            "state": state, "done_count": done_count, "total_count": len(subs),
            "substeps": subs, "deliverables": docs, "next_action": None,
        })

    # 每阶段的下一步动作也填上（点某一段时能看到那一段要做什么），
    # 顶层 next_action 才是「唯一主动作」。
    for i, st_payload in enumerate(stages):
        if st_payload["state"] == "todo":
            st_payload["next_action"] = _next_action(order_id, [stages[i]])
        elif st_payload["state"] == "current":
            st_payload["next_action"] = _next_action(order_id, [stages[i]])

    next_action = None if all_done else _next_action(order_id, stages[cur:])
    if next_action is None and not all_done:
        next_action = _next_action(order_id, stages)

    return {
        "order_id": order_id, "version": 1,
        "platform_stage": platform_stage,
        "platform_stage_name": _platform_stage_name(platform_stage),
        "current_stage": stages[cur]["id"], "current_stage_index": cur,
        "stages": stages,
        "next_action": next_action,
        "documents": documents(store, order_id),
    }


def documents(store, order_id: str) -> list[dict]:
    """按阶段顺序排好的文档清单（R01：四份文档后移到对应阶段）。"""
    rows = {r["deliverable_id"]: r for r in store.deliverables(order_id)}
    out = []
    for spec in BY_ID.values():
        stage_id = deliverable_stage(spec.code)
        st = STAGES_BY_ID.get(stage_id)
        row = rows.get(spec.id)
        out.append({
            "code": spec.code, "title": spec.title, "step": spec.step,
            "stage": stage_id, "stage_name": st.name if st else "",
            "stage_order": st.order if st else 99,
            "submitted": bool(row), "version": int((row or {}).get("version") or 0),
            "surface": spec.surface,
        })
    out.sort(key=lambda d: (d["stage_order"], _code_order(d["code"])))
    return out


_CODE_INDEX = {code: i for i, code in enumerate(d.code for d in BY_ID.values())}


def _code_order(code: str) -> int:
    return _CODE_INDEX.get(code, 99)


def deliverable_list(store, items: list[dict], order_id: str = "") -> dict:
    """给 `DeliverableService.list_for_order` 的每条补阶段元数据，并按阶段排序。"""
    order_id = order_id or ""
    cur_stage = ""
    if order_id:
        order = store.order(order_id)
        if order:
            cur_stage = STAGE_ORDER[current_stage_index(order)]
    nxt = None
    if order_id:
        j = journey(store, order_id)
        nxt = (j or {}).get("next_action")

    enriched = []
    for it in items:
        code = it.get("code") or ""
        stage_id = deliverable_stage(code)
        st = STAGES_BY_ID.get(stage_id)
        spec = resolve(code)
        item = dict(it)
        item.update({
            # 中文 id 别名：聊天界面等旧调用方按 deliverable_id 找文档
            "deliverable_id": spec.id if spec else it.get("id") or it.get("deliverable_id") or "",
            "stage": stage_id,
            "stage_name": st.name if st else "",
            "stage_order": st.order if st else 99,
            "stage_state": ("current" if stage_id and stage_id == cur_stage
                            else "done" if (st and cur_stage and st.order < _order_of(cur_stage))
                            else "todo"),
            "in_current_stage": bool(stage_id) and stage_id == cur_stage,
            "is_next": bool(nxt) and nxt.get("deliverable") == code,
        })
        enriched.append(item)
    enriched.sort(key=lambda d: (d.get("stage_order", 99), _code_order(d.get("code", ""))))

    cur_def = STAGES_BY_ID.get(cur_stage)
    stage_summaries = []
    for st in STAGES:
        stage_summaries.append({
            "id": st.id, "name": st.name, "short": st.short, "order": st.order,
            "state": ("current" if st.id == cur_stage else "todo"),
            "deliverable_codes": [c for c in st.deliverables],
        })
    if cur_def:
        for s in stage_summaries:
            if s["order"] < cur_def.order:
                s["state"] = "done"

    return {
        "order_id": order_id,
        "deliverables": enriched,
        "items": enriched,
        "current_stage": cur_stage,
        "current_stage_index": STAGE_ORDER.index(cur_stage) if cur_stage in STAGE_ORDER else -1,
        "stages": stage_summaries,
        "next_action": nxt,
        "training_completion": training_completion(store, order_id),
    }


def _order_of(stage_id: str) -> int:
    st = STAGES_BY_ID.get(stage_id)
    return st.order if st else 99


def annotate_submission(store, order_id: str, out: dict) -> dict:
    """给提交回执补 `delivered` / `receipt` / `next_action`（R03 / R04 的判据来源）。"""
    blocked = bool(out.get("blocked"))
    did = out.get("deliverable_id") or ""
    spec = resolve(did) if did else None
    code = spec.code if spec else (out.get("code") or "")
    stage_id = deliverable_stage(code) if code else ""
    st = STAGES_BY_ID.get(stage_id)

    out["delivered"] = not blocked
    out["stage"] = stage_id
    out["stage_name"] = st.name if st else ""
    if blocked:
        out["receipt"] = None
    else:
        targets = [t.get("name") or t.get("session_id") or ""
                   for t in ((out.get("routing") or {}).get("targets") or [])]
        sent_to = (out.get("routing") or {}).get("sent_to") or []
        out["receipt"] = {
            "deliverable_id": spec.id if spec else did,
            "code": code,
            "version": int(out.get("version") or 0),
            "at": out.get("at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stage": stage_id,
            "targets": [t for t in targets if t] or sent_to,
            "message": (f"《{spec.title}》已投递（V{out.get('version')}）" if spec
                        else f"{did} 已投递（V{out.get('version')}）"),
        }
    j = journey(store, order_id)
    out["next_action"] = (j or {}).get("next_action")
    out["training_completion"] = training_completion(store, order_id)
    return out


def training_completion(store, order_id: str) -> dict:
    """行后两份文件的提交回执即为完成依据，不要求覆盖率或其他阶段门槛。"""
    required = [resolve(code) for code in PRACTICE_FINAL_CODES]
    rows = {row["deliverable_id"]: row for row in store.deliverables(order_id)}
    completed = all(spec.id in rows for spec in required)
    return {"completed": completed,
            "completed_at": max(str(rows[spec.id].get("at") or "") for spec in required) if completed else "",
            "required": [{"code": spec.code, "title": spec.title, "submitted": spec.id in rows} for spec in required],
            "score_route": f"/practice/orders/{order_id}/score"}


def order_is_complete(store, order_id: str) -> bool:
    order = store.order(order_id)
    if not order:
        return False
    return int(order.get("stage_index") or 0) >= PLATFORM_STAGE_MAX
