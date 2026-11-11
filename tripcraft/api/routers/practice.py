"""实战旅程域：订单、派单、通关动作、完成条件、导演总线、覆盖与复核、六阶段旅程投影。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt）。
对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。

安全（security.py v2，2026-10-16 收紧后）：
- 身份一律取服务端会话（`Depends(current_user)`），不用查询串/请求体里的 user_id 当身份；
  请求体里若出现 user_id，用 `require_self()` 校验，不得冒用他人。
- 所有 `/practice/orders/{order_id}/...` 子路径先 `own_order()`：不存在 404、不属于当前用户 403。

阶段口径（R09/R10）：`GET /practice/stages` 原样透传 `tripcraft/contracts/stages.py`；
`GET /practice/orders/{order_id}/journey` 是订单在六阶段里的投影，含唯一下一步动作。
`GET /practice/steps` 保留原有的 8 态平台状态（底层考核状态），并附上六阶段契约，供旧调用方过渡。
"""

from __future__ import annotations


import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from tripcraft.contracts import culture_bridges as cb
from tripcraft.contracts import skill_points as sp
from tripcraft.contracts import skill_points as sp_module
from tripcraft.contracts.deliverables import Deliverable
from tripcraft.contracts.enums import (
    DIMENSION_NAMES,
    DIMENSION_WEIGHTS,
    MASTERY_NAMES,
    STEP_NAMES,
    DeliverableKind,
    Dimension,
    StepId,
    mastery_of,
)
from tripcraft.contracts.profile import LearnerProfile, dimension_value
from tripcraft.contracts.rubric import RUBRICS
from tripcraft.contracts.task import TaskInstance
from tripcraft.engine.state_machine import Run
from tripcraft.agents.llm import DeepSeekClient, LLMError
from tripcraft.agents import profiler as profile_agent
from tripcraft.services.call_service import CallService
from tripcraft.services.director_service import EVENTS as DIRECTOR_EVENTS
from tripcraft.services.director_service import INCIDENT_RULES, DirectorService
from tripcraft.services.deliverable_service import DeliverableError, DeliverableService
from tripcraft.services.guard_service import GuardService
from tripcraft.services.finance_service import FinanceService
from tripcraft.services.plan_service import PlanService
from tripcraft.services.supplier_service import SupplierService
from tripcraft.services.workflow import ACTION_LABELS, MANUAL_ACTIONS
from tripcraft.mcp.server import MCPServer
from tripcraft.calibration import audit_dataset, load_samples, run_calibration
from tripcraft.services.s2_session import S2Session
from tripcraft.services.practice_service import GROUP_STEP, PracticeService
from tripcraft.services.thread_service import ThreadService
from tripcraft.services.tools_service import ToolsService
from tripcraft.voice.bridge import VoiceBridge
from tripcraft.services.visit_monitor import VISIT_MONITOR, VisitMonitorMiddleware
from tripcraft.storage import Store
from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext
from tripcraft.api.security import current_user, own_order, require_self
from tripcraft.api.public_dto import public_customer_from_facts, scan_forbidden_keys
from tripcraft.services import journey_service as journey
from tripcraft.services.customer_order_facts import facts_for_order_id


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()
    # ---------------- 六阶段契约（唯一阶段口径来源） ----------------

    @router.get("/practice/stages")
    def practice_stages():
        """原样透传 contracts/stages.py 的 as_payload()：前端六阶段导航的唯一来源。"""
        return journey.stages_payload()

    # ---------------- 实战：订单 / 完成条件 / 评分 ----------------

    @router.get("/practice/steps")
    def practice_steps():
        """底层 8 态平台状态（保留兼容）+ 六阶段契约（新调用方用 /practice/stages）。"""
        from tripcraft.services.practice_service import ORDER_STEPS, STAGE_HINTS
        return {"steps": ORDER_STEPS, "hints": STAGE_HINTS,
                "journey": journey.stages_payload()}

    @router.get("/practice/orders")
    def practice_orders(user: str = Depends(current_user)):
        return ctx.practice.list_orders(user)

    @router.get("/practice/orders/{order_id}/customer-card")
    def customer_card(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        card = ctx.store.ensure_customer_card(order_id)
        events = ctx.store.customer_fact_events(order_id)
        return {"card": card, "events": events,
                "conflicts": [event for event in events if event["kind"] == "conflict"]}

    @router.get("/practice/dispatch/brief")
    def dispatch_brief(user_id: str = "", user: str = Depends(current_user)):
        """本单简报：画像 → 目标技能点 + 各难度旋钮档位（给前端解释用）。

        schema v2：user_id 不是身份，只做自报校验；身份一律取登录会话。
        R08：`user_id` 是内部身份，不作为前端可见字段下发（实测此前是空串残留）。
        """
        brief = ctx.practice.brief_for(require_self(user_id, user))
        brief.pop("user_id", None)
        return brief

    @router.post("/practice/dispatch/generate")
    def dispatch_generate(body: S.DispatchGenerateBody, user: str = Depends(current_user)):
        """按画像生成新派单（随机游客由画像反推，不是随机出题）。

        新用户的初始订单走这里：spawn_order 生成全局唯一 order_id，不需要模型。

        若本实例是**内部演示实例**（启动期显式开启 TRIPCRAFT_DEMO_TOURIST），
        这里改派固定标准案例（含资源约束）；已存在本案例订单则复用，不重复建单。
        """
        owner = require_self(body.user_id, user)
        try:
            from tripcraft.services.scenario_service import demo_replacement
            replaced = demo_replacement(ctx, owner, count=body.count)
        except Exception:                     # noqa: BLE001 - 替换失败不得影响正常派单
            replaced = None
        if replaced is not None:
            return replaced
        try:
            llm = ctx.get_llm()
        except LLMError:
            llm = None
        return ctx.practice.generate_dispatch(owner, llm=llm, count=body.count,
                                              language=body.language)


    @router.get("/practice/orders/available")
    def practice_available(user: str = Depends(current_user)):
        """可抢订单（消息中心「待接单」持续刷新用）。"""
        return ctx.practice.available_orders(user)

    @router.get("/practice/orders/{order_id}/journey")
    def practice_journey(order_id: str, user: str = Depends(current_user)):
        """订单的六阶段旅程投影：阶段状态 + 子步骤状态 + 唯一下一步动作（R09/R10）。"""
        own_order(ctx, user, order_id)
        out = journey.journey(ctx.store, order_id)
        if out is None:
            raise HTTPException(404, f"未找到订单: {order_id}")
        return out

    @router.get("/practice/orders/{order_id}")
    def practice_order(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        detail = ctx.practice.order_detail(order_id)
        if not detail:
            raise HTTPException(404, f"未找到订单: {order_id}")
        # R08 边界：客户人设一律走公开投影（白名单构造），再做一次越界字段自检（fail-closed）
        detail["persona"] = public_customer_from_facts(facts_for_order_id(ctx.store, order_id))
        leaked = scan_forbidden_keys(detail)
        if leaked:
            raise HTTPException(500, f"订单详情包含未公开字段，已拦截：{'、'.join(leaked[:5])}")
        return detail

    @router.get("/practice/orders/{order_id}/steps")
    def practice_order_steps(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return {"order_id": order_id, "steps": ctx.practice.order_steps(order_id)}

    @router.get("/practice/orders/{order_id}/contacts")
    def practice_order_contacts(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        rows = ctx.store.contacts(order_id)
        return [{"time": c["at"], "kind": c["kind"], "status": c["status"],
                 "has_record": bool(c["has_record"]), "detail": c["detail"]} for c in rows]

    @router.get("/practice/messages")
    def practice_messages(user: str = Depends(current_user)):
        return ctx.practice.messages(user)

    @router.get("/practice/orders/{order_id}/gates")
    def practice_gates(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.gate_report(order_id)

    # ---------------- 流程通关驱动（D-033） ----------------

    @router.post("/practice/orders/{order_id}/grab")
    def practice_grab(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        detail = ctx.practice.order_detail(order_id)
        if not detail:
            raise HTTPException(404, f"未找到订单: {order_id}")
        if detail["status"] in ("禁用", "已派他人"):
            raise HTTPException(409, "该订单已取消或已被接走，无法抢单")
        try:
            out = ctx.practice.record_action(order_id, "grab", {"by": user})
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        out["dispatch"] = ctx.practice.dispatch_info(order_id)
        return out

    @router.post("/practice/orders/{order_id}/actions")
    def practice_action(order_id: str, body: S.ActionBody, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            return ctx.practice.record_action(order_id, body.action, {"by": user})
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.get("/practice/orders/{order_id}/actions")
    def practice_actions(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        rows = ctx.store.actions(order_id)
        return {"order_id": order_id,
                "actions": [{"action": r["action"], "at": r["at"],
                             "label": ACTION_LABELS.get(r["action"], r["action"])} for r in rows],
                "manual_options": list(MANUAL_ACTIONS),
                "labels": ACTION_LABELS}

    @router.get("/practice/orders/{order_id}/flow")
    def practice_flow(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.flow_progress(order_id)

    @router.get("/practice/orders/{order_id}/scores")
    def practice_scores(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.order_scores(order_id)

    # ---------------- 导演总线（事件 → 规则化注入突发事件） ----------------

    @router.get("/practice/director/catalog")
    def director_catalog():
        return {"events": list(DIRECTOR_EVENTS), "rules": ctx.director.catalog()}

    @router.post("/practice/orders/{order_id}/events")
    def director_emit(order_id: str, body: S.DirectorEventBody, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            return ctx.get_director().emit(order_id, body.type, body.payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.get("/practice/orders/{order_id}/dispatch")
    def order_dispatch(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.dispatch_info(order_id)

    @router.get("/practice/orders/{order_id}/timeline")
    def director_timeline(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.get_director().timeline(order_id)

    @router.get("/practice/orders/{order_id}/coverage")
    def practice_coverage(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.coverage(order_id)

    @router.get("/practice/orders/{order_id}/reviews")
    def practice_reviews(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        return ctx.practice.pending_reviews(order_id)

    @router.post("/practice/orders/{order_id}/reviews/{sp}")
    def practice_review(order_id: str, sp: str, body: S.ReviewBody,
                        user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            return ctx.practice.review_score(order_id, sp, body.decision, body.score)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    return router
