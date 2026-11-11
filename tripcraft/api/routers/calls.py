"""通话与沟通域：订单绑定通话、语音中继 WebSocket、IM 群聊与联系人。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt）。
对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。
"""

from __future__ import annotations


import asyncio
import base64
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
from tripcraft.services.supplier_service import ROLE_TO_KIND, SupplierService
from tripcraft.services.conversation_service import ConversationError
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
from fastapi import APIRouter, Depends
from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext
from tripcraft.api.public_dto import public_call_snapshot
from tripcraft.api.security import current_user, own_order, websocket_user
from tripcraft.services.customer_order_facts import (
    facts_for_order_id,
    persona_for_order,
)


def _own_session(store, sid: str, user: str) -> dict:
    """im_session 归属校验：会话不存在 404，不属于当前用户 403。"""
    sess = store.session(sid)
    if not sess:
        raise HTTPException(404, "未找到会话")
    if (sess.get("user_id") or "") != user:
        raise HTTPException(403, "无权访问该会话")
    return sess


RESOURCE_CHAT_KINDS = {"地接社", "酒店", "车队", "票务", "行中", "导游", "司机"}


def _is_resource_chat(conversation_type: str, session_kind: str, target_kind: str = "") -> bool:
    """只有资源群/资源单聊里的追偿话术才触发资源方定责回复。"""
    return conversation_type == "hub" or session_kind in RESOURCE_CHAT_KINDS or target_kind in RESOURCE_CHAT_KINDS


def _finance_speaker_name(svc, order_id: str, kind: str, session: dict | None = None) -> str:
    """把台账资源类型换成这一单的具体联系人；车辆责任优先落到本单司机。"""
    contacts = svc.added_contacts(order_id)
    contact = None
    if kind == "车队":
        contact = contacts.get("司机") or contacts.get("车队")
    else:
        contact = contacts.get(kind)
    if contact:
        return svc.display(contact)
    session = session or {}
    session_kind = str(session.get("kind") or "")
    if session_kind == kind or (kind == "车队" and session_kind == "司机"):
        name = str(session.get("name") or "").strip()
        if name and name not in (kind, "客户", "资源方"):
            return name
    names = svc.names(order_id)
    if kind == "车队":
        return names.get("司机") or names.get("车队") or "本单司机"
    return names.get(kind) or kind


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()
    # ---------------- 通话（订单绑定的实时客户 Agent） ----------------

    @router.post("/practice/orders/{order_id}/call")
    def start_call(order_id: str, user: str = Depends(current_user)):
        """发起文本首呼。

        修复点（R02/R08）：
        - 订单归属校验：不是自己的单一律 403（own_order 严格归属，无池放行）；
        - 客户事实统一经 `customer_order_facts` 取，不再由路由逐个 `detail.get(...)`；
        - 落库用户是真实登录用户，不再写死 u-demo。
        """
        row = own_order(ctx, user, order_id)
        if row.get("status") == "禁用":
            raise HTTPException(409, "该订单已取消，无法发起通话")
        try:
            sess = ctx.get_call().start_for_order(ctx.store, order_id, user)
        except (RuntimeError, LLMError) as exc:
            raise HTTPException(503, str(exc))
        return public_call_snapshot(sess.snapshot())

    @router.get("/practice/call/{sid}")
    def call_snapshot(sid: str, user: str = Depends(current_user)):
        sess = ctx.get_call().get(sid, user)
        if sess is None:
            raise HTTPException(404, "未找到通话会话")
        return public_call_snapshot(sess.snapshot())

    @router.post("/practice/call/{sid}/messages")
    def call_say(sid: str, body: S.CallSay, user: str = Depends(current_user)):
        if ctx.get_call().get(sid, user) is None:
            raise HTTPException(404, "未找到通话会话")
        try:
            line = ctx.get_call().say(sid, body.text, user)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        if line is None:
            raise HTTPException(404, "未找到通话会话")
        sess = ctx.get_call().get(sid, user)
        snap = public_call_snapshot(sess.snapshot()) if sess else {}
        return {"reply": line, **snap}

    @router.post("/practice/call/{sid}/end")
    def call_end(sid: str, user: str = Depends(current_user)):
        snap = ctx.get_call().end(sid, user)
        if snap is None:
            raise HTTPException(404, "未找到通话会话")
        if snap.get("turns"):
            ctx.practice.record_action(snap["order_id"], "first_call", {"session_id": sid})
        return public_call_snapshot(snap)

    @router.post("/practice/im/sessions/{sid}/messages")
    def im_send(sid: str, body: S.ImMsg, user: str = Depends(current_user)):
        """发消息：先由 ConversationService 固定会话、订单和目标角色，再交给 Orchestra。

        资源大群不是"靠最近一单猜"的路由器：多单并行且没有明确 order_id 时返回 409。
        """
        sess0 = _own_session(ctx.store, sid, user)
        try:
            route = ctx.get_conversation().resolve(
                sid, user, order_id=body.order_id, text=body.content,
                target_role=body.target_role, allow_latest=(body.role != "me"),
            )
        except ConversationError as exc:
            raise HTTPException(exc.status, str(exc))
        oid_now = route.order_id
        if oid_now:
            own_order(ctx, user, oid_now)
        state = ctx.get_supplier().room_state(oid_now, sid)
        if body.role == "me" and state["locked"]:
            raise HTTPException(409, state["hint"])

        msg_id = ctx.store.add_im_message(
            sid, body.sender, body.role, body.content, kind=body.kind,
            payload={**(body.payload or {}), "_route": route.as_dict()})
        # 学员在群里回话 = 对注入事件的「可观测反应」→ B 型考点算覆盖
        reacted = ctx.get_director().react(sid) if body.role == "me" else []
        reply, error, fin = None, "", None
        target_kind = ROLE_TO_KIND.get(route.target_role, "")
        if body.role == "me":
            sess_now = ctx.store.session(sid) or {}
            try:
                reply = ctx.get_supplier().respond(
                    sid, body.content, oid_now, target_role=body.target_role, strict=True)
            except Exception as exc:      # 不静默吞掉：把原因带回去，便于定位
                error = f"{type(exc).__name__}: {exc}"
            if reply:
                ctx.store.add_im_message(sid, reply["sender"], "other", reply["content"])
            # 学员在资源方群里谈追偿/赔付 → 先定位具体资源方，再按写死比例定责。
            # 客户单聊里只是向客户说明处理方案，不能触发资源方定责回复。
            session_kind = str(sess_now.get("kind") or "")
            if _is_resource_chat(route.conversation_type, session_kind, target_kind):
                try:
                    fin = ctx.get_finance().maybe_attribute_from_chat(
                        oid_now, target_kind or session_kind, body.content)
                except Exception:
                    fin = None
                if fin and fin.get("message"):
                    kind = fin.get("supplier_kind") or target_kind or session_kind
                    speaker = _finance_speaker_name(ctx.get_supplier(), oid_now, kind, sess_now)
                    ctx.store.add_im_message(sid, speaker, "other", fin["message"])
            # 群聊也是证据：每一次发言都绑定 conversation_id + order_id。
            used = reply["content"] if reply else "（对方未应答）"
            ref = f"im:{sid}:{msg_id}" if msg_id else sid
            ctx.practice.record_evidence(
                oid_now, "im",
                f"【{route.conversation_type}·{sess_now.get('name') or route.conversation.name}】"
                f"订单 {oid_now or '—'}\n我：{body.content.strip()}\n"
                f"{reply['sender'] if reply else '系统'}：{used}",
                step=GROUP_STEP.get(route.conversation.code or "") or None, ref=ref)
            # 资源方给出具体价格/库存/档期，就是一次可验证的 S4 资源询价。
            # 这样「资源询价」不再要求学员离开聊天去补一份形式化记录。
            if (reply and reply.get("quote") and not reply.get("deferred")
                    and reply.get("supplier_kind") in ("地接社", "酒店", "车队", "票务")):
                ctx.practice.record_evidence(
                    oid_now, "供应商询价",
                    f"【资源询价·{reply['supplier_kind']}】\n我：{body.content.strip()}\n"
                    f"{reply['sender']}：{used}",
                    step="S4", ref=ref + ":supplier-quote")

        out = {"ok": True, "reacted": reacted, "reply": reply, "route": route.as_dict()}
        if fin and fin.get("entry"):
            out["finance"] = {"entry_id": fin["entry"]["entry_id"], "bearer": fin["entry"]["bearer"],
                              "ours": fin["entry"]["ours"], "amount": fin["entry"]["amount"],
                              "supplier_kind": fin.get("supplier_kind") or target_kind}
        if fin and fin.get("need_supplier"):
            out["finance"] = {"need_supplier": fin["need_supplier"], "message": fin["message"]}
        if reply and reply.get("supplier_kind"):
            out["supplier"] = {"kind": reply.get("supplier_kind"),
                               "name": reply.get("supplier_name") or reply.get("sender", "")}
        if error:
            out["error"] = error
        return out
    @router.websocket("/voice/realtime")
    async def voice_realtime(ws: WebSocket):
        """语音入口的认证边界（R08）：WebSocket 不受 HTTP 中间件覆盖，必须自行取 token。

        拒绝策略（fail-closed）：
        - 无 token / token 失效 → 4401 关闭，不建立通话会话、不调用 DashScope、不落库；
        - token 有效但订单不属于本人 → 4403 关闭，同上。
        """
        await ws.accept()
        ctx_uid = websocket_user(ctx, ws)
        if not ctx_uid:
            await ws.send_json({"type": "error", "message": "未登录或会话已失效，请重新登录"})
            await ws.close(code=4401)
            return
        order_id = str(ws.query_params.get("order_id", "") or "")
        row = ctx.store.order(order_id) if order_id else None
        if not row:
            await ws.send_json({"type": "error", "message": f"未找到订单: {order_id}"})
            await ws.close(code=4404)
            return
        owner = row.get("user_id") or ""
        if owner and owner != ctx_uid:
            await ws.send_json({"type": "error", "message": "无权访问该订单"})
            await ws.close(code=4403)
            return
        detail = ctx.practice.order_detail(order_id)
        if not detail:
            await ws.send_json({"type": "error", "message": f"未找到订单: {order_id}"})
            await ws.close(code=4404)
            return
        if detail["status"] == "禁用":
            await ws.send_json({"type": "error", "message": "该订单已取消，无法发起通话"})
            await ws.close(code=4409)
            return
        # detail 是给界面的公开平铺视图，不含 payload 中的完整客户事实。
        # 语音内部必须传原始订单行；只补当前阶段，私有人设不下发前端。
        voice_order = {**row, "stage_name": detail.get("stage_name", "")}
        try:
            bridge = VoiceBridge(ws, voice_order, detail["customer"], detail["destination"],
                                 ctx.get_call(), ctx.practice, user_id=ctx_uid)
            await bridge.run()
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # 保底：把失败原因送回前端而不是静默断开
            try:
                await ws.send_json({"type": "error", "message": f"语音通道异常: {exc}"})
            except Exception:
                pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    @router.websocket("/voice/dictation")
    async def voice_dictation(ws: WebSocket):
        """聊天输入框的实时语音转写：只回文字，不生成客户回复。"""
        await ws.accept()
        user = websocket_user(ctx, ws)
        if not user:
            await ws.send_json({"type": "error", "message": "未登录或会话已失效，请重新登录"})
            await ws.close(code=4401)
            return
        lang = str(ws.query_params.get("lang") or "zh")
        from tripcraft.voice.realtime_qwen import QwenRealtimeClient, resolve_env
        try:
            api_key, ws_url, model = resolve_env()
        except RuntimeError as exc:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.close()
            return
        instructions = (
            "You are a speech-to-text dictation service for a Chinese travel consultant. "
            f"Transcribe the user's speech verbatim in language {lang}. "
            "Do not answer the user, do not summarize, do not add explanations. "
            "Only reproduce exactly what was spoken."
        )
        loop = asyncio.get_running_loop()
        events: asyncio.Queue = asyncio.Queue()
        transcript_seen = asyncio.Event()

        def on_event(ev: dict) -> None:
            loop.call_soon_threadsafe(events.put_nowait, ev)

        client = QwenRealtimeClient(api_key, ws_url, model, instructions, voice=None,
                                    on_event=on_event)
        client.connect()
        if not await asyncio.to_thread(client.wait_ready, 20):
            await ws.send_json({"type": "error", "message": "语音转写服务连接超时"})
            client.close()
            await ws.close()
            return
        await ws.send_json({"type": "ready", "lang": lang})

        async def pump() -> None:
            while True:
                ev = await events.get()
                t = ev.get("type", "")
                if t in ("conversation.item.input_audio_transcription.completed",
                         "conversation.item.input_audio_transcription.done"):
                    text = str(ev.get("transcript") or "").strip()
                    if text:
                        transcript_seen.set()
                        await ws.send_json({"type": "transcript", "text": text, "final": True})
                elif t in ("error", "ws_error"):
                    await ws.send_json({"type": "error", "message": str(ev.get("error") or ev)[:300]})

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                kind = msg.get("type")
                if kind == "audio":
                    audio = msg.get("audio") or ""
                    if audio:
                        client.append_audio(base64.b64decode(audio))
                elif kind == "commit":
                    client.commit()
                elif kind == "stop":
                    client.commit()
                    try:
                        await asyncio.wait_for(transcript_seen.wait(), timeout=6)
                    except asyncio.TimeoutError:
                        pass
                    break
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            client.close()
            try:
                await ws.close()
            except Exception:
                pass

    # ---------------- 聊天界面（第 26.10 节） ----------------

    @router.get("/practice/im/sessions")
    def im_sessions(order_id: str = "", session: str = "", user: str = Depends(current_user)):
        """聊天会话：本单资源对接群 + 单聊 + 自己拉的群（跨订单混排，像真实聊天软件）。

        资源对接群按订单创建，只包含该单的地接、酒店、车队、票务与司导；
        客户只在客户群或客户单聊里，不进入资源对接群。
        指定 session 时以该会话所属订单为准，避免打开别的订单时套错资源群。
        """
        if session:
            wanted = _own_session(ctx.store, session, user)
            order_id = wanted.get("order_id") or order_id
        if order_id:
            own_order(ctx, user, order_id)
        svc = ctx.get_supplier()
        orders = {o["order_id"]: o for o in ctx.practice.list_orders(user)}
        requirement_done = lambda oid: ctx.store.has_action(oid, "deliverable:需求确认单")
        hub_order_ids = [order_id] if order_id and requirement_done(order_id) else [
            oid for oid, row in orders.items()
            if int(row.get("stage_index") or 0) < 7
            and ctx.store.has_action(oid, "grab") and requirement_done(oid)
        ]
        rows = []
        for oid in hub_order_ids:
            if not oid or not requirement_done(oid):
                continue
            view = svc._session_view(svc.ensure_hub(user, oid)["session_id"]) or {}
            if view:
                rows.append(view)
            ticket = svc._session_view(svc.ensure_ticket_window(user, oid)["session_id"]) or {}
            if ticket:
                rows.append(ticket)
        keep = ("group", "custom")
        for sess in ctx.store.sessions(user):
            code = sess.get("code") or ""
            if code in ("hub", "ticket"):
                continue                  # 固定窗口已在上方按订单加入
            if not (code.startswith("dm-") or code in keep):
                continue                  # 老的按订单自动建的房间：不再显示
            rows.append(svc._session_view(sess["session_id"]) or {})
        out = []
        for v in rows:
            o = orders.get(v.get("order_id") or "", {})
            oid = v.get("order_id") or ""
            facts = facts_for_order_id(ctx.store, oid) if oid else None
            is_fixed = (v.get("code") or "") in ("hub", "ticket")
            out.append({**v,
                        "customer": "" if is_fixed else o.get("customer", ""),
                        "destination": "" if is_fixed else o.get("destination", ""),
                        "language": facts.language if facts else "中文",
                        "min_stage": 0, "intro": "",
                        "messages": ctx.store.im_messages(v["session_id"])})
        out.sort(key=lambda r: (0 if r.get("code") == "hub" else 1 if r.get("code") == "ticket" else 2,
                                r.get("order_id") or "", r.get("name") or ""))
        # 方案「客户已读」是惰性结算的：聊天页面也要顺手结算一次，
        # 否则学员点完「发送方案」跳到聊天里会一直等不到客户回复（回复只在查方案时生成）。
        for oid in {r.get("order_id") for r in out if r.get("order_id")}:
            try:
                ctx.get_plans().list(oid)
            except Exception:
                pass
        for r in out:
            r["messages"] = ctx.store.im_messages(r["session_id"])
        return out

    @router.get("/practice/im/contacts")
    def im_contacts(order_id: str = "", user: str = Depends(current_user)):
        """这一单能拿到哪些联系人（来源 / 能不能加 / 加没加）+ 我的通讯录。"""
        svc = ctx.get_supplier()
        catalog = []
        if order_id:
            own_order(ctx, user, order_id)
            catalog = svc.contact_catalog(order_id)
        return {"order_id": order_id, "contacts": catalog, "mine": svc.contacts_of_user(user)}

    @router.patch("/practice/im/contacts/{contact_id}")
    def im_contact_remark(contact_id: str, body: S.RemarkBody, user: str = Depends(current_user)):
        """给联系人起备注名（真实聊天软件的核心功能）。只能改自己的联系人。"""
        row = ctx.store.contact(contact_id)
        if not row:
            raise HTTPException(404, f"未找到联系人: {contact_id}")
        if (row.get("user_id") or "") != user:
            raise HTTPException(403, "无权修改该联系人")
        try:
            c = ctx.get_supplier().rename_contact(contact_id, body.remark)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "contact": c, "display": ctx.get_supplier().display(c)}

    @router.post("/practice/im/contacts")
    def im_add_contact(body: S.ContactBody, user: str = Depends(current_user)):
        """加联系人：建 1:1 会话。没到条件（没首呼 / 没接单 / 地接还没给）加不了。"""
        own_order(ctx, user, body.order_id)
        try:
            out = ctx.get_supplier().add_contact(body.order_id, body.kind)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True, **out}

    @router.post("/practice/im/sessions/{sid}/rename")
    def im_rename(sid: str, body: S.RenameBody, user: str = Depends(current_user)):
        _own_session(ctx.store, sid, user)
        try:
            return {"ok": True, **ctx.get_supplier().rename(sid, body.name)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/practice/im/sessions/{sid}/members")
    def im_members(sid: str, body: S.MembersBody, user: str = Depends(current_user)):
        _own_session(ctx.store, sid, user)
        try:
            out = ctx.get_supplier().add_members(sid, body.names)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if out.get("blocked_customer"):
            out["message"] = "资源对接群只对接地接、酒店、车队、票务和司导，客户请留在客户群或客户单聊。"
        elif out["rejected"]:
            out["message"] = f"这些还没有联系方式，先加好友：{'、'.join(out['rejected'])}"
        return {"ok": True, **out}

    # ---------------- 成本 · 损失 · 结算（PRD 6.2 / C5 · C6.7） ----------------

    @router.get("/practice/orders/{order_id}/finance")
    def finance_view(order_id: str, user: str = Depends(current_user)):
        """本单成本与结算：资源口径成本、损失台账、实际毛利与自报口径的偏差。"""
        own_order(ctx, user, order_id)
        return ctx.get_finance().summary(order_id)

    @router.post("/practice/orders/{order_id}/finance/entries/{entry_id}/decide")
    def finance_decide(order_id: str, entry_id: str, body: S.FinanceDecideBody,
                       user: str = Depends(current_user)):
        """给一笔损失定责：我方承担 / 向资源方追偿 / 转嫁客户。"""
        own_order(ctx, user, order_id)
        try:
            out = ctx.get_finance().decide(order_id, entry_id, body.bearer, body.note)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return {"ok": True, "message": out["message"], "entry": out["entry"],
                "summary": ctx.get_finance().summary(order_id)}

    @router.post("/practice/orders/{order_id}/finance/settle")
    def finance_settle(order_id: str, user: str = Depends(current_user)):
        """结账：汇总成本与损失、落库，并写一条 S11 结算证据。"""
        own_order(ctx, user, order_id)
        return ctx.get_finance().settle(order_id)

    @router.post("/practice/im/sessions")
    def im_create(body: S.ImSessionBody, user: str = Depends(current_user)):
        """拉群：只能邀请已加过联系方式的人；群名可改（默认「旅行小群」）。

        归属：群主一律是当前登录用户（请求体里的 `user_id` 不参与身份判定）。
        """
        svc = ctx.get_supplier()
        if body.order_id:
            own_order(ctx, user, body.order_id)
        members = [m for m in (body.members or []) if m and m.strip()]
        mine = svc.contacts_of_user(user)
        known = {c["name"] for c in mine} | {svc.display(c) for c in mine}
        rejected = [m for m in members if m not in known]
        if rejected:
            raise HTTPException(409, f"还没有这些人的联系方式，先加好友：{'、'.join(rejected)}")
        name = (body.name or "").strip() or "旅行小群"
        # 稳定哈希：Python 的 hash() 每个进程都不一样，重启会生成新会话
        h = 0
        for ch in f"{body.order_id}|{name}|{'|'.join(members)}":
            h = (h * 31 + ord(ch)) % 100000
        sid = f"im-{body.order_id}-group-{h}" if body.order_id else f"s{h}"
        full = ["我"] + [m for m in members if m != "我"]
        ctx.store.upsert_session(sid, user, name, body.kind, full,
                             order_id=body.order_id, code="group")
        ctx.store.add_im_message(sid, "系统", "system",
                             f"你创建了群聊「{name}」，成员：{'、'.join(full[1:]) or '（待邀请）'}",
                             kind="system")
        return {"session_id": sid, "name": name, "kind": body.kind,
                "order_id": body.order_id, "members": full}

    return router
