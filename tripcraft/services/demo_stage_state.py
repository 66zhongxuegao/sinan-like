"""演示账号初始状态：三个阶段订单 + 可评分的完整订单。

只在专用演示账号退出登录时调用；普通账号没有入口。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..contracts.rubric import RUBRICS
from ..contracts.skill_points import SKILL_POINTS, SKILL_POINTS_BY_ID
from .profile_radar import build_radar
from .scenario_service import ScenarioService
from .supplier_service import SupplierService

USERNAME = "demo-flow"
DISPLAY_NAME = "途悠国际旅行社定制师毛毛"
PASSWORD = "Demo2026!"
ITINERARY_ORDER = "9920000000000001"
NOTICE_ORDER = "9920000000000002"
SCORE_ORDER = "9920000000000003"
INITIAL = {"C1": 62, "C2": 60, "C3": 58, "C4": 55, "C5": 57, "C6": 59, "C7": 63, "C8": 52}


def _report(summary: str, kind: str = "refresh") -> dict:
    return {"kind": kind, "summary": summary,
            "strengths": ["能主动确认关键需求", "资源取舍清晰", "突发事件处理有闭环意识"],
            "suggestions": [
                {"dim_name": "需求洞察", "title": "先确认预算口径",
                 "why": "亲子团容易在预算和节奏上出现偏差。",
                 "how": "首呼一次问清人数、日期、预算和硬约束。", "skill_point_id": "C2.1"},
                {"dim_name": "方案能力", "title": "把亲子节奏写进逐日安排",
                 "why": "可执行的节奏比景点数量更重要。",
                 "how": "每天保留机动时间，避免连续赶路。", "skill_point_id": "C3.5"},
            ]}


def payload(customer: str, destination: str, dates: str, *, intent: str,
            budget: str | None = None) -> dict:
    now = datetime.now()
    return {
        "customer": customer, "source_market": "新加坡", "language": "中文",
        "destination": destination, "party": "3 大 1 小", "dates": dates, "days": "5 天",
        "budget": budget or "人均 6500 元", "hotel": "四星或同档次，含早",
        "transport": "含接送机，7 座商务车", "special": "亲子出行，节奏不要太赶",
        "documents": "有效护照；签证按实际行程核验", "generated": True, "demo_data": True, "showcase_realistic": True,
        "published": True, "dispatch_at": now.isoformat(timespec="seconds"),
        "first_call_limit_min": 120, "intent": intent,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _actions(store, oid: str, names: tuple[str, ...]) -> None:
    for name in names:
        if not store.has_action(oid, name):
            store.add_action(oid, name, {"demo_orders": True})


def _add_customer(store, oid: str) -> None:
    supplier = SupplierService(store=store)
    if "客户" not in supplier.added_contacts(oid):
        supplier.add_contact(oid, "客户")


def _seed_profile(ctx, uid: str) -> None:
    store = ctx.store
    for dim, value in INITIAL.items():
        store.save_baseline(uid, dim, value, source="intake")
    for point in SKILL_POINTS:
        base = INITIAL[point.dimension.value]
        store.set_ability(uid, point.id, teach=min(90, base + 10), source="learning")
        store.set_ability(uid, point.id, real_v=58, source="practice")
    initial_radar = build_radar(uid, {}, store.baseline(uid),
                                _report("初始画像完成，已识别当前能力起点。", "initial"))
    saved = store.save_profile_snapshot(uid, "initial", initial_radar,
                                        _report("初始画像完成，已识别当前能力起点。", "initial"))
    ids = [saved["snapshot"]["id"]]
    for level, text in ((1, "完成需求与方案练习，学习掌握度上升。"),
                        (2, "完成亲子团实战，方案与沟通能力提升。")):
        historical = {}
        for point in SKILL_POINTS:
            base = INITIAL[point.dimension.value]
            historical[point.id] = {"teach": min(94, base + 8 + level * 3),
                                    "real_v": min(90, base + level * 3),
                                    "teach_source": "learning", "real_source": "practice"}
        radar = build_radar(uid, historical, store.baseline(uid), practice_completed_at="")
        saved = store.save_profile_snapshot(uid, "refresh", radar, _report(text))
        ids.append(saved["snapshot"]["id"])
    for index, sid in enumerate(ids):
        at = (datetime.now() - timedelta(days=8 - index * 4)).isoformat(timespec="seconds")
        store._exec("UPDATE profile_snapshot SET created_at=? WHERE snapshot_id=?", (at, sid))


def reset_initial(ctx, user_id: str) -> dict:
    """只重置一个演示账号；调用方必须先确认是 demo-flow。"""
    store = ctx.store
    store.update_user_profile(user_id, {"display_name": DISPLAY_NAME})
    ScenarioService(ctx).reset(user_id, all_orders=True, include_profile=True)
    _seed_profile(ctx, user_id)
    store = ctx.store

    store.upsert_order(
        ITINERARY_ORDER, user_id, "陈女士", "云南", "正常", 1,
        payload=payload("陈女士", "云南", "2026-11-15 至 2026-11-19",
                        intent="亲子游，想去云南，预算人均 6500 元，希望节奏轻松。"),
    )
    _actions(store, ITINERARY_ORDER, ("grab", "first_call", "deliverable:需求确认单"))
    _add_customer(store, ITINERARY_ORDER)

    # 周先生单停在「行前 · 出团通知」：资源已锁定，等待学员固定发送出团通知书。
    # 发送后由阶段推进自动登记 depart，并触发司导群的车辆故障事件。
    store.upsert_order(
        NOTICE_ORDER, user_id, "周先生", "广西", "正常", 4,
        payload=payload("周先生", "广西", "2026-11-22 至 2026-11-26",
                        intent="带父母和孩子去广西，住宿要安静，老人不能走太久。"),
    )
    _actions(store, NOTICE_ORDER, (
        "grab", "first_call", "deliverable:需求确认单", "deliverable:行程方案",
        "deliverable:分项报价", "guard_pass:分项报价", "customer_confirmed_plan",
        "contract_signed", "insurance_bought", "customer_signed_contract", "deposit_paid",
        "resources_locked",
    ))
    _add_customer(store, NOTICE_ORDER)
    supplier = SupplierService(store=store)
    # 司导群需要先有导游/司机，否则 S10 的车辆故障规则没有落点。
    director = ctx.get_director()
    try:
        director.materialize_resource_pool(
            NOTICE_ORDER, "需要导游和司机", ["导游", "司机"], "桂林", "")
    except Exception:
        pass
    for kind in ("地接社", "导游", "司机"):
        try:
            supplier.add_contact(NOTICE_ORDER, kind)
        except ValueError:
            pass

    store.upsert_order(
        SCORE_ORDER, user_id, "林女士", "四川", "正常", 7,
        payload=payload("林女士", "四川", "2026-10-20 至 2026-10-24",
                        intent="一家三口去四川，希望行程轻松，资源确认清楚。"),
    )
    _actions(store, SCORE_ORDER, (
        "grab", "first_call", "deliverable:需求确认单", "deliverable:行程方案",
        "deliverable:分项报价", "guard_pass:分项报价", "customer_confirmed_plan",
        "contract_signed", "insurance_bought", "customer_signed_contract", "deposit_paid",
        "resources_locked", "pre_trip_notice", "settlement_verified", "balance_paid",
        "review_done",
    ))
    _add_customer(store, SCORE_ORDER)
    score_payload = json.loads(store.order(SCORE_ORDER)["payload"] or "{}")
    score_payload["auto_accept_scores"] = True
    store.upsert_order(SCORE_ORDER, user_id, "林女士", "四川", "正常", 7, payload=score_payload)

    target_ids = ("C1.1", "C1.4", "C2.1", "C2.3", "C3.1", "C3.5", "C4.1", "C4.4",
                  "C5.1", "C5.3", "C6.1", "C6.3", "C7.1", "C7.4", "C8.1", "C8.5")
    fallback = {
        "C1": "首呼中确认身份与目的，复述客户原话并取得确认。",
        "C2": "识别亲子、长辈和预算口径，完成四分类整理。",
        "C3": "逐日行程六要素齐全，路线无折返。",
        "C4": "酒店、车辆、门票均询价并记录库存和保留时限。",
        "C5": "分项报价合计一致，保险计入，毛利保留空间。",
        "C6": "突发事件先安抚、再核实、给替代方案并记录成本。",
        "C7": "首呼、方案、合同和出团通知按时完成。",
        "C8": "补充证件、支付和通讯说明，规避文化禁忌。",
    }
    for sp_id in target_ids:
        point = SKILL_POINTS_BY_ID[sp_id]
        rubric = RUBRICS.get(sp_id)
        step = point.steps[0].value if point.steps else "S10"
        quote = rubric.positive if rubric else fallback[point.dimension.value]
        text = (f"【{sp_id} {point.name}】客户原话与处理记录：{quote}。"
                f"对应动作：{point.target}。时间、资源、金额与客户确认均有留痕，可复核。")
        ctx.practice.record_evidence(SCORE_ORDER, "完整交付物与沟通记录", text, step=step)
        store.upsert_target(SCORE_ORDER, sp_id, point.checkpoint.value, step,
                            trigger_state="reacted", covered=True, reason="完整订单训练证据已归档")
    return {"ok": True, "username": USERNAME,
            "orders": [ITINERARY_ORDER, NOTICE_ORDER, SCORE_ORDER]}
