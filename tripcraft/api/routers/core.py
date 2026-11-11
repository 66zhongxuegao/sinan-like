"""参考数据域：健康检查、文化桥、翻译、公开契约（steps / dimensions / skill-points / rubric / markets）。

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
from fastapi import APIRouter
from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()
    # ---------------- 健康检查 ----------------

    @router.get("/")
    def health():
        """单容器部署（SERVE_WEB=1）时根路径给前端页面；默认仍是健康状态 JSON。"""
        dist_index = Path(__file__).resolve().parents[3] / "frontend" / "dist" / "index.html"
        if os.environ.get("SERVE_WEB", "").strip() not in ("", "0") and dist_index.exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(dist_index))
        return {"status": "ok", "service": "TripCraft", "version": "0.1.0"}

    # ---------------- 文化桥（十大客源国共通点） ----------------

    @router.get("/learn/culture-bridges")
    def culture_bridges():
        return [cb.as_payload(b) for b in cb.all_bridges()]

    @router.get("/learn/culture-bridges/{code}")
    def culture_bridge(code: str):
        b = cb.get(code)
        if not b:
            raise HTTPException(404, f"未找到文化桥: {code}")
        return cb.as_payload(b)

    @router.post("/learn/translate")
    def learn_translate(body: S.TranslateBody):
        """把一段内容翻成目标语言，保持 Markdown 结构与专有名词不变。"""
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(400, "没有要翻译的内容")
        try:
            llm = ctx.get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        system = (
            f"你是翻译引擎，把用户给的内容翻译成{body.target}。\n"
            "硬性要求：\n"
            "1. 完整保留原有 Markdown 结构：标题层级、列表符号、加粗、表格、引用、代码块、链接一律不动；\n"
            "2. 只翻译自然语言；代码、URL、数字、单位、专有名词保持原样；\n"
            "3. 不要添加解释、不要输出「以下是翻译」之类的话；\n"
            "4. 直接输出译文本身。"
        )
        try:
            out = llm.chat([{"role": "system", "content": system},
                            {"role": "user", "content": text}],
                           temperature=0.2, max_tokens=2400)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        return {"target": body.target, "text": (out or "").strip()}

    # ---------------- 数据契约 ----------------

    @router.get("/contracts/steps")
    def steps():
        return [{"id": s.value, "name": STEP_NAMES[s]} for s in StepId]

    @router.get("/contracts/dimensions")
    def dimensions():
        return [
            {"id": d.value, "name": DIMENSION_NAMES[d], "weight": DIMENSION_WEIGHTS[d]}
            for d in Dimension
        ]

    @router.get("/contracts/skill-points")
    def skill_points(dimension: str | None = None):
        items = sp.SKILL_POINTS
        if dimension:
            try:
                dim = Dimension(dimension)
            except ValueError:
                raise HTTPException(400, f"未知维度: {dimension}")
            items = sp.by_dimension(dim)
        return [
            {
                "id": x.id, "name": x.name, "dimension": x.dimension.value,
                "checkpoint": x.checkpoint.value, "material": x.material,
                "steps": [s.value for s in x.steps], "target": x.target,
            }
            for x in items
        ]

    @router.get("/contracts/skill-points/{skill_point_id}")
    def skill_point(skill_point_id: str):
        x = sp.SKILL_POINTS_BY_ID.get(skill_point_id)
        if x is None:
            raise HTTPException(404, f"未知技能点: {skill_point_id}")
        return {
            "id": x.id, "name": x.name, "dimension": x.dimension.value,
            "checkpoint": x.checkpoint.value, "material": x.material,
            "steps": [s.value for s in x.steps], "target": x.target,
        }

    @router.get("/contracts/rubric/{skill_point_id}")
    def rubric(skill_point_id: str):
        r = RUBRICS.get(skill_point_id)
        if r is None:
            raise HTTPException(404, "该技能点的 Rubric 尚未产出（M0 只有 C2.2 示例）")
        return {
            "skill_point_id": r.skill_point_id,
            "steps": [s.value for s in r.steps],
            "target": r.target,
            "trigger": r.trigger,
            "anchors": [{"level": a.level.value, "behavior": a.behavior} for a in r.anchors],
            "positive": r.positive,
            "negative": r.negative,
            "evidence_required": r.evidence_required,
            "knowledge": r.knowledge,
        }

    @router.get("/contracts/markets")
    def contracts_markets():
        """客源市场清单（前端"客源语言"下拉用同一份口径，避免两边写死不一致）。"""
        from tripcraft.agents.scenario import LANGUAGES, SOURCE_MARKETS
        return {"languages": list(LANGUAGES),
                "markets": [{"market": k, "language": v[0], "documents": v[1], "complexity": v[2]}
                            for k, v in SOURCE_MARKETS.items()]}

    return router
