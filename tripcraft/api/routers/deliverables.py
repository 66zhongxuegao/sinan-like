"""交付物域：契约渲染、校验、PDF、按对象投递、方案版本与模板、附件。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt）。
对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。

安全（security.py v2）：
- 身份一律取服务端会话（`Depends(current_user)`）；请求体里的 user_id 只用于 `require_self` 校验。
- 所有 `/practice/orders/{order_id}/...` 先 `own_order()`；方案再核对 plan_id 属于该订单。
- 文件上传/下载按订单归属校验：`GET /deliverables/files/{file_id}` 不能凭 file_id 任意下载。

阶段口径（R01）：交付物列表按 `contracts/stages.py` 的阶段顺序返回，
每条带 stage/stage_name/stage_state/in_current_stage/is_next；提交回执带 delivered/receipt/next_action。
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
from tripcraft.services import journey_service as journey
from urllib.parse import quote

_UPLOAD_MAX_BYTES = 8 * 1024 * 1024


def _safe_filename(name: str, fallback: str = "download") -> str:
    """文件名净化：去掉 CR/LF/引号/反斜杠/路径分隔符与 NUL，避免 header 注入与目录穿越。"""
    raw = (name or "").replace("\r", "").replace("\n", "").replace("\x00", "")
    raw = raw.replace("\\", "_").replace("/", "_").replace('"', "_")
    raw = raw.strip().strip(".")
    # 只取最后一段（防 ../ 残留）
    raw = raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return raw or fallback


def _content_disposition(name: str, fallback: str = "download") -> str:
    """RFC 5987 / RFC 6266 的 Content-Disposition：ASCII fallback + filename*（UTF-8 百分号编码）。

    Starlette 对 header 值做 latin-1 编码，中文直接塞进 filename= 会抛错 → 500；
    这里把非 ASCII 全部收敛成 ASCII fallback，真实文件名走 filename*=UTF-8''。
    """
    safe = _safe_filename(name, fallback)
    ascii_fallback = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in safe) or fallback
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()

    def _render_ctx(order: dict) -> dict:
        payload = json.loads(order.get("payload") or "{}")
        return {"order_id": order["order_id"], "customer": order["customer"],
                "destination": order["destination"],
                "source_market": payload.get("source_market", ""),
                "language": payload.get("language", "中文")}

    def _own_plan(order_id: str, plan_id: str) -> dict:
        """plan_id 必须属于该订单，否则 404（防止 A 单 plan_id 配 B 单 order_id）。"""
        row = ctx.store.plan(plan_id)
        if not row or row.get("order_id") != order_id:
            raise HTTPException(404, f"未找到方案: {plan_id}")
        return row

    # ---------------- 交付物工作台（契约 → 渲染 → 校验 → 按对象投递） ----------------

    @router.get("/deliverables/specs")
    def deliverable_specs():
        return {"deliverables": DeliverableService.specs()}

    @router.get("/practice/orders/{order_id}/deliverables")
    def order_deliverables(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        base = ctx.get_deliverables().list_for_order(order_id)
        return journey.deliverable_list(ctx.store, base["deliverables"], order_id)

    @router.post("/practice/orders/{order_id}/deliverables/import-template")
    def import_deliverable_templates(order_id: str, body: S.DeliverableTemplateImport,
                                    user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            llm = ctx.get_llm()
        except LLMError:
            llm = None
        try:
            return ctx.get_deliverables().import_templates(order_id, body.drafts, llm)
        except DeliverableError as exc:
            raise HTTPException(400, str(exc))

    @router.get("/practice/orders/{order_id}/deliverables/{did}")
    def order_deliverable(order_id: str, did: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            return ctx.get_deliverables().detail(order_id, did)
        except DeliverableError as exc:
            raise HTTPException(404, str(exc))

    @router.post("/practice/orders/{order_id}/deliverables/{did}/preview")
    def order_deliverable_preview(order_id: str, did: str, body: S.DeliverablePreview,
                                  user: str = Depends(current_user)):
        """按契约渲染当前填写内容（不提交、不校验），用于右侧实时预览。

        - **会发给客户的文档**（需求确认单 / 行程方案 / 分项报价 / 合同与保险 / 出团通知书）：
          预览＝客户看到的版本（无内部字段与核算汇总，内部口径句子剔除）；
        - **内部/地接专用文档**（资源询价记录 / 地接结算核对单 / 回访与复盘记录）：
          预览＝文档自身内容，核算说明原样保留（它们本来就不发客户）。
        两种情况都回传内部档案文本与被剔除的词供学员自查。
        """
        from tripcraft.contracts.deliverables_spec import (is_customer_facing, render,
                                                           render_for_customer, resolve)
        order = own_order(ctx, user, order_id)
        spec = resolve(did)
        if spec is None:
            raise HTTPException(404, "交付物不存在")
        render_ctx = _render_ctx(order)
        internal_text = render(spec, body.values, render_ctx)
        customer_facing = is_customer_facing(spec)
        if customer_facing:
            customer_text, withheld = render_for_customer(spec, body.values, render_ctx)
        else:
            customer_text, withheld = internal_text, []
        return {"rendered": customer_text,
                "internal_rendered": internal_text,
                "customer_facing": customer_facing,
                "customer_withheld": withheld,
                "missing": DeliverableService.validate(spec.id, body.values)}

    @router.post("/practice/orders/{order_id}/deliverables/{did}/export.pdf")
    def order_deliverable_pdf(order_id: str, did: str, body: S.DeliverablePreview,
                              user: str = Depends(current_user)):
        """导出 PDF：会发给客户的文档出客户版，内部/地接专用文档出自身内容。"""
        from fastapi.responses import Response

        from tripcraft.contracts.deliverables_spec import (is_customer_facing, render,
                                                           render_for_customer, resolve)
        from tripcraft.services.pdf_service import markdown_to_pdf

        order = own_order(ctx, user, order_id)
        spec = resolve(did)
        if spec is None:
            raise HTTPException(404, "交付物不存在")
        render_ctx = _render_ctx(order)
        if is_customer_facing(spec):
            text = render_for_customer(spec, body.values, render_ctx)[0]
        else:
            text = render(spec, body.values, render_ctx)
        pdf = markdown_to_pdf(text, title=spec.title,
                              order_id=order_id, customer=order["customer"])
        name = f"{spec.title}-{order_id}.pdf"
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": _content_disposition(name, "deliverable.pdf")})

    @router.post("/practice/orders/{order_id}/deliverables/{did}")
    def order_deliverable_submit(order_id: str, did: str, body: S.DeliverableSubmit,
                                 user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            out = ctx.get_deliverables().submit(order_id, did, body.values, body.file_ids,
                                                targets=body.targets, submit_once=body.submit_once)
        except DeliverableError as exc:
            raise HTTPException(400, str(exc))
        # R03/R04：回执带 delivered / receipt / next_action
        return journey.annotate_submission(ctx.store, order_id, out)

    # ---------------- 方案版本：创建方案 → 发送方案 → 客户已读（PRD 28.31） ----------------

    @router.get("/practice/orders/{order_id}/plans")
    def order_plans(order_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        plans = ctx.get_plans().list(order_id)
        return {"order_id": order_id, "plans": plans,
                "unread": sum(1 for p in plans if p["status"] == "已发送" and not p["read"])}

    @router.post("/practice/orders/{order_id}/plans")
    def order_plan_create(order_id: str, body: S.PlanBody, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        try:
            return {"ok": True, "plan": ctx.get_plans().create(order_id, body.values, body.note)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.put("/practice/orders/{order_id}/plans/{plan_id}")
    def order_plan_update(order_id: str, plan_id: str, body: S.PlanBody,
                          user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        _own_plan(order_id, plan_id)
        try:
            return {"ok": True, "plan": ctx.get_plans().update(order_id, plan_id, body.values,
                                                               body.note)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/practice/orders/{order_id}/plans/{plan_id}/send")
    def order_plan_send(order_id: str, plan_id: str, body: S.PlanSendBody,
                        user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        _own_plan(order_id, plan_id)
        try:
            return ctx.get_plans().send(order_id, plan_id, body.targets)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/practice/orders/{order_id}/plans/{plan_id}/confirm")
    def order_plan_confirm(order_id: str, plan_id: str, user: str = Depends(current_user)):
        own_order(ctx, user, order_id)
        _own_plan(order_id, plan_id)
        try:
            return ctx.get_plans().confirm(order_id, plan_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    # 方案小节模板：学员自己写的标题存下来，下次创建方案直接用
    @router.get("/practice/doc-templates")
    def doc_templates(kind: str = "plan", user: str = Depends(current_user)):
        rows = ctx.store.doc_templates(user, kind)
        return {"templates": [{"template_id": r["template_id"], "name": r["name"],
                               "sections": json.loads(r["sections"] or "[]"),
                               "updated_at": r["updated_at"]} for r in rows]}

    @router.post("/practice/doc-templates")
    def doc_template_save(body: S.TemplateBody, user: str = Depends(current_user)):
        if not body.name.strip():
            raise HTTPException(400, "模板名不能为空")
        # schema v2：body.user_id 不是身份，只做自报校验（空 = 未自报）
        owner = require_self(body.user_id, user)
        tid = f"tpl-{owner}-{body.kind}-{abs(hash(body.name)) % 100000}"
        ctx.store.save_doc_template(tid, owner, body.name.strip(), body.sections, body.kind)
        return {"ok": True, "template_id": tid}

    @router.delete("/practice/doc-templates/{template_id}")
    def doc_template_delete(template_id: str, user: str = Depends(current_user)):
        row = ctx.store.doc_template(template_id)
        if not row:
            raise HTTPException(404, "模板不存在")
        if (row.get("user_id") or "") != user:
            raise HTTPException(403, "无权删除该模板")
        ctx.store._exec("DELETE FROM doc_template WHERE template_id=?", (template_id,))
        return {"ok": True}

    @router.post("/deliverables/files")
    def deliverable_upload(body: S.FileUpload, user: str = Depends(current_user)):
        import base64 as _b64
        if not (body.order_id or "").strip():
            # 归属校验必须能落到具体订单，否则文件成了任何人凭 file_id 可取的孤儿数据
            raise HTTPException(400, "上传附件必须带上 order_id")
        own_order(ctx, user, body.order_id)
        try:
            data = _b64.b64decode(body.data_b64, validate=False)
        except Exception:
            raise HTTPException(400, "文件内容不是合法 base64")
        if len(data) > _UPLOAD_MAX_BYTES:
            raise HTTPException(413, "文件过大（上限 8MB）")
        fid = f"f-{int(time.time() * 1000) % 100000000}-{abs(hash(body.filename)) % 10000}"
        ctx.store.save_file(fid, body.order_id, body.deliverable_id,
                            _safe_filename(body.filename, "attachment"), body.mime, len(data), data)
        return {"file_id": fid, "filename": _safe_filename(body.filename, "attachment"),
                "size": len(data)}

    @router.get("/deliverables/files/{file_id}")
    def deliverable_file(file_id: str, user: str = Depends(current_user)):
        """文件下载：按文件所属订单校验归属，不能凭 file_id 任意下载。"""
        from fastapi.responses import Response
        row = ctx.store.file(file_id)
        if not row:
            raise HTTPException(404, "文件不存在")
        order_id = (row.get("order_id") or "").strip()
        if not order_id:
            # 历史孤儿文件（上传时未关联订单）：fail-closed，不对外下载
            raise HTTPException(403, "该文件未关联订单，无法确认归属")
        own_order(ctx, user, order_id)
        return Response(content=row["data"], media_type=row["mime"] or "application/octet-stream",
                        headers={"Content-Disposition": _content_disposition(
                            row.get("filename") or "download")})

    return router
