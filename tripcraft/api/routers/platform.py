"""平台域：工具台、拦截网、校准集、MCP 调试面。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt）。
对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。
"""

from __future__ import annotations


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
from fastapi import APIRouter, Depends
from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext
from tripcraft.api.security import current_user, own_order, require_debug

PLATFORM_DEBUG_ENV = "TRIPCRAFT_DEBUG_PLATFORM"


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()

    def _platform_debug() -> None:
        """校准集与全局拦截网是运营/调试面，不是学员入口：默认 404。"""
        require_debug(PLATFORM_DEBUG_ENV, "平台调试面")

    # ---------------- 人工校准集（PRD 第 25 章） ----------------

    @router.get("/calibration")
    def calibration_status():
        _platform_debug()
        run = ctx.store.latest_calibration()
        rows = load_samples()
        return {
            "gate": ctx.practice.calibration_gate(),
            "thresholds": ctx.practice.thresholds(),
            "samples": len(rows),
            "dataset": audit_dataset(rows),
            "latest": (None if not run else {
                "run_id": run["run_id"], "samples": run["samples"], "predictions": run["predictions"],
                "agreement": run["agreement"], "evidence_accuracy": run["evidence_accuracy"],
                "stability": run["stability"], "passed": bool(run["passed"]),
                "threshold_confidence": run["threshold_conf"],
                "threshold_delta": run["threshold_delta"],
                "created_at": run["created_at"],
            }),
            "history": [{"run_id": r["run_id"], "agreement": r["agreement"],
                         "evidence_accuracy": r["evidence_accuracy"], "passed": bool(r["passed"]),
                         "created_at": r["created_at"]} for r in ctx.store.calibration_runs(5)],
        }

    @router.get("/calibration/samples")
    def calibration_samples():
        _platform_debug()
        rows = load_samples()
        return {"count": len(rows),
                "items": [{"id": s["id"], "skill_point_ids": s["skill_point_ids"],
                           "source_market": s.get("source_market", ""), "language": s.get("language", ""),
                           "difficulty": s.get("difficulty", ""),
                           "labels": [{"skill_point_id": l["skill_point_id"], "level": l["level"]}
                                      for l in s.get("labels", [])]} for s in rows]}

    @router.post("/calibration/run")
    def calibration_run(body: S.CalibrationBody):
        _platform_debug()
        try:
            llm = ctx.get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        samples = load_samples()
        if body.limit:
            samples = samples[:body.limit]
        if not samples:
            raise HTTPException(400, "没有校准样本")
        try:
            report = run_calibration(llm, samples, repeats=max(1, body.repeats))
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        ctx.store.add_calibration_run(
            report["run_id"], report["samples"], report["predictions"],
            report["agreement"], report["evidence_accuracy"], report["stability"],
            report["threshold"]["confidence"], report["threshold"]["boundary_delta"],
            report["passed"], report)
        return report

    # ---------------- Multi-Agent Orchestra 目录（调试面） ----------------

    @router.get("/orchestration/agents")
    def orchestration_agents():
        _platform_debug()
        agents = ctx.conductor.registry.catalog()
        return {
            "architecture": "Multi-Agent Orchestra",
            "conductor": "deterministic",
            "agents": agents,
            "bound": sum(1 for a in agents if a["bound"]),
            "total": len(agents),
        }

    # ---------------- MCP 封装（PRD 23 / D-011） ----------------
    # 外部数据与资源能力统一按 MCP 工具契约暴露：复赛换真实接口只替换下面的 handler。

    _knowledge_dir = Path(__file__).resolve().parents[3] / "data" / "knowledge"

    def _mcp_knowledge(args: dict):
        sp = str(args.get("skill_point_id", ""))
        f = _knowledge_dir / f"{sp}.json"
        if not f.exists():
            return {"error": f"未找到技能点知识底座: {sp}"}
        return json.loads(f.read_text(encoding="utf-8"))

    def _mcp_deliverable(args: dict):
        kind = str(args.get("kind", ""))
        content = str(args.get("content", ""))
        order_id = str(args.get("order_id", ""))
        if not order_id:
            return {"error": "请先选择订单，再投递给本单客户"}
        report = ctx.get_guard().check(kind, content, order_id or None)
        if report["blocked"]:
            return {"blocked": True, "guard": report,
                    "message": "交付物未通过校验，未投递给客户"}
        out = ctx.get_tools().deliverable_feedback(kind, content, str(args.get("customer") or "客户"), order_id=order_id)
        out["guard"] = report
        if order_id:
            out["evidence_id"] = ctx.practice.record_evidence(
                order_id, kind, f"【交付物·{kind}】\n{content.strip()}",
                ref=f"mcp-{int(time.time() * 1000)}")
        return out

    mcp_handlers = {
        "weather": lambda a: ctx.get_tools().weather(str(a["city"])),
        "route": lambda a: ctx.get_tools().route(str(a["origin"]), str(a["destination"])),
        "itinerary": lambda a: ctx.get_tools().check_itinerary(list(a["stops"])),
        "fx": lambda a: ctx.get_tools().fx(str(a.get("base") or "CNY"), a.get("quotes") or None),
        "supplier": lambda a: ctx.get_tools().supplier(str(a["kind"]), str(a["request"]),
                                                       str(a.get("user_id") or "")),
        "deliverable": _mcp_deliverable,
        "guard": lambda a: ctx.get_guard().check(str(a["kind"]), str(a["content"]),
                                             str(a.get("order_id") or "") or None,
                                             geo=bool(a.get("geo"))),
        "director": lambda a: ctx.get_director().emit(str(a["order_id"]), str(a["type"])),
        "order": lambda a: ctx.practice.order_detail(str(a["order_id"])) or {"error": "未找到订单"},
        "coverage": lambda a: ctx.practice.coverage(str(a["order_id"])),
        "knowledge": _mcp_knowledge,
    }
    mcp = MCPServer(mcp_handlers)

    MCP_DEBUG_ENV = "TRIPCRAFT_DEBUG_MCP"

    def _mcp_enabled() -> None:
        """R16：MCP 只是调试/系统能力，对学员默认隐藏（404）；且从不接入真实预订。"""
        require_debug(MCP_DEBUG_ENV, "MCP 调试面")

    @router.get("/mcp/tools", include_in_schema=False)
    def mcp_tools():
        _mcp_enabled()
        catalog = MCPServer.catalog()
        if isinstance(catalog, dict):
            return {"debug_only": True, "booking_enabled": False, "not_connected": True, **catalog}
        return {"debug_only": True, "booking_enabled": False, "not_connected": True,
                "tools": catalog}

    @router.post("/mcp", include_in_schema=False)
    def mcp_rpc(body: dict):
        """MCP 核心 JSON-RPC 入口（initialize / tools/list / tools/call / ping）。

        对学员默认 404（R16）；这些工具只做本地数据与文案能力，**未接入**任何
        机酒预订/支付通道，不得对外宣称可真实预订。
        """
        _mcp_enabled()
        resp = mcp.handle(body if isinstance(body, dict) else {})
        if resp is None:
            return {"jsonrpc": "2.0", "id": None, "result": {}}
        return resp

    # ---------------- 双层拦截网（PRD 24.3） ----------------

    @router.post("/guard/check")
    def guard_check(body: S.GuardBody):
        # 全局拦截网自检：运营/调试面，不是学员入口（订单级检查见下面那个接口）
        _platform_debug()
        return ctx.get_guard().check(body.kind, body.content, body.order_id or None, geo=body.geo)

    @router.post("/practice/orders/{order_id}/guard")
    def guard_order(order_id: str, body: S.GuardBody, user: str = Depends(current_user)):
        # 交付物工作台在用：保留对学员开放，但必须是自己那一单
        own_order(ctx, user, order_id)
        return ctx.get_guard().check(body.kind, body.content, order_id, geo=body.geo)

    # ---------------- 工具台 ----------------

    @router.get("/tools/weather")
    def tools_weather(city: str, date: str | None = None):
        try:
            return ctx.get_tools().weather(city, date)
        except Exception as exc:
            raise HTTPException(503, f"天气查询失败: {exc}")

    def _waypoints(raw: str) -> list[str]:
        import re as _re
        return [w.strip() for w in _re.split(r"[,，、]", raw or "") if w.strip()]

    @router.get("/tools/route")
    def tools_route(origin: str, destination: str, mode: str = "driving", waypoints: str = ""):
        """真实路线：驾车（可带途经点）/ 步行 / 骑行 / 公交。"""
        try:
            return ctx.get_tools().route(origin, destination, mode, _waypoints(waypoints))
        except Exception as exc:
            raise HTTPException(503, f"路线查询失败: {exc}")

    @router.get("/tools/poi/tips")
    def tools_poi_tips(q: str, city: str = ""):
        """输入联想（高德输入提示）：前端输入框的下拉候选。"""
        try:
            return {"tips": ctx.get_tools().poi_tips(q, city)}
        except Exception as exc:
            raise HTTPException(503, f"联想查询失败: {exc}")

    @router.get("/tools/map")
    def tools_map(origin: str, destination: str, mode: str = "driving", waypoints: str = "",
                  size: str = "900*520"):
        """静态地图 PNG（高德底图 + 起终点与途经点标记 + 驾车路线）。"""
        from fastapi.responses import Response
        try:
            png = ctx.get_tools().map_image(origin, destination, mode, _waypoints(waypoints), size)
        except Exception as exc:
            raise HTTPException(503, f"地图生成失败: {exc}")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "no-cache"})

    @router.post("/tools/itinerary/check")
    def tools_itinerary(body: S.ItineraryBody):
        try:
            return ctx.get_tools().check_itinerary(body.stops)
        except Exception as exc:
            raise HTTPException(503, f"行程核验失败: {exc}")

    @router.get("/tools/fx")
    def tools_fx(base: str = "CNY", quotes: str = ""):
        try:
            want = [q.strip() for q in quotes.split(",") if q.strip()] or None
            return ctx.get_tools().fx(base, want)
        except Exception as exc:
            raise HTTPException(503, f"汇率查询失败: {exc}")

    @router.get("/tools/supplier/state")
    def tools_supplier_state(user: str = Depends(current_user)):
        return {"states": ctx.get_tools().supplier_states(user)}

    @router.post("/tools/supplier/state")
    def tools_supplier_state_set(body: S.SupplierStateBody, user: str = Depends(current_user)):
        # 模拟器控制面：状态只写当前登录用户，忽略请求体里的 user_id（防冒用）
        try:
            state = ctx.get_tools().set_supplier_state(body.kind, {
                "availability": body.availability,
                "price_factor": body.price_factor,
                "note": body.note,
            }, user_id=user)
            return {"kind": body.kind, "state": state, "states": ctx.get_tools().supplier_states(user)}
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/tools/supplier")
    def tools_supplier(body: S.SupplierBody, user: str = Depends(current_user)):
        # 带订单：走该单的资源方事实（与群里同一个口径），并登记为询价证据
        if body.order_id:
            own_order(ctx, user, body.order_id)
            out = ctx.get_supplier().ask(body.order_id, body.kind, body.request)
            if out is not None:
                q = out.get("quote") or {}
                reply = {"kind": body.kind, "request": body.request, "reply": out["content"],
                         "price": q.get("summary", ""), "availability": q.get("availability", ""),
                         "note": q.get("note", ""), "deferred": bool(out.get("deferred"))}
                ctx.practice.record_evidence(
                    body.order_id, "供应商询价",
                    f"【询价·{body.kind}】\n我问：{body.request.strip()}\n"
                    f"{out['sender']}：{out['content']}",
                    ref=f"supplier-{int(time.time() * 1000)}")
                return reply
        try:
            return ctx.get_tools().supplier(body.kind, body.request, user)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(503, str(exc))
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/tools/deliverable")
    def tools_deliverable(body: S.DeliverableBody2, user: str = Depends(current_user)):
        if not body.order_id:
            raise HTTPException(400, "请先选择订单，再投递给本单客户")
        # 第一层先跑拦截网：被拦下的交付物不投递给客户、不登记证据
        if body.order_id:
            own_order(ctx, user, body.order_id)
        report = ctx.get_guard().check(body.kind, body.content, body.order_id or None)
        if report["blocked"]:
            return {"blocked": True, "guard": report, "reply": "",
                    "sentiment": "", "asks": [],
                    "message": "交付物未通过校验，未投递给客户；请按下方问题修改后重新提交。"}
        try:
            out = ctx.get_tools().deliverable_feedback(body.kind, body.content, body.customer, order_id=body.order_id or "")
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        out["guard"] = report
        if body.order_id:
            ev_id = ctx.practice.record_evidence(
                body.order_id, body.kind,
                f"【交付物·{body.kind}】\n{body.content.strip()}",
                ref=f"deliverable-{int(time.time() * 1000)}")
            out["evidence_id"] = ev_id
            # 只登记门槛里真正存在的动作（并非每种交付物都有关卡动作）
            for act in (f"deliverable:{body.kind}", f"guard_pass:{body.kind}"):
                if act in ACTION_LABELS:
                    ctx.practice.record_action(body.order_id, act)
            out["gates"] = ctx.practice.gate_report(body.order_id)
        return out

    return router
