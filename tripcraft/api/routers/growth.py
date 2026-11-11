"""身份与成长域：学习地图、技能点线程、实战评分与画像、初始测评与刷新。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt），
identity 域在拆分基础上做了三件事（R08/R11/R12/R14）：

1. **归属收敛**：本模块所有接口一律以 `security.current_user` 为可信身份；
   路径/查询里显式指定别人的 user_id → 403；订单相关一律过 `security.own_order`。
   请求体里自带的 user_id 默认被忽略（只用当前会话身份），只有当调用方**显式**
   传了别人的 user_id 时才 403（`_claimed_user`）。
2. **数字口径**：`/profiles/{id}/trend` 不再用固定起点 + 加减分模拟，改为
   按 `quiz_attempt`（题目口径）与 `order_score`（订单口径）真实记录计算，
   并返回样本数、均分与数据来源（示例/真实）。
3. **初始/当前同量纲**：`/profiles/{id}/radar` 用 `profile_baseline`（初始测评快照，
   不被后续评分覆盖）与当前 ability 对比，同为 0–100 维度值；缺数据显示「未评估」，
   绝不假增分。

对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。
"""

from __future__ import annotations


import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext
from tripcraft.api.public_dto import public_quiz_card
from tripcraft.api.security import current_user, own_order, require_debug, require_self
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
from tripcraft.services.profile_radar import build_radar, initial_only, radar_abilities
from tripcraft.services import learning_route
from tripcraft.services.tools_service import ToolsService
from tripcraft.voice.bridge import VoiceBridge
from tripcraft.services.visit_monitor import VISIT_MONITOR, VisitMonitorMiddleware
from tripcraft.storage import Store

REPORT_TYPE = "profile_report"

# 手工写能力分是内部调试面：学员的正规写入口是初始测评 / 答题 / 实战评分。
PROFILE_DEBUG_ENV = "TRIPCRAFT_DEBUG_PROFILE"

# 认证上线前就存在的历史种子演示账号（不在 users 表里）。
# 只用于 R14 的示例/真实口径判定，是精确 id 白名单，不是用户名前缀匹配。
LEGACY_DEMO_IDS = frozenset({"u-demo", "u-show"})


def _fields_set(body: object) -> set:
    """调用方**显式**传了哪些字段（兼容 pydantic v2 / v1）。"""
    found = getattr(body, "model_fields_set", None)
    if found is None:
        found = getattr(body, "__fields_set__", None)
    return set(found or ())


def _explicit_user_id(body: object) -> str:
    """请求体里**显式**传的 user_id。

    老 DTO（schemas.py，Lead 所有）里 user_id 的默认值是 "u-demo" 这类占位符；
    它不是「调用方声明我是 u-demo」，只是历史默认值，不能当作冒用处理。
    因此只有显式出现在请求体里的 user_id 才参与 require_self 校验。
    """
    if "user_id" not in _fields_set(body):
        return ""
    return str(getattr(body, "user_id", "") or "").strip()


def _self_of_body(body: object, uid: str, what: str) -> str:
    """体里显式冒用他人 → 403；没显式声明 → 一律用当前会话身份。"""
    return require_self(_explicit_user_id(body), uid, what)


# ---------------- R08：题卡答案剥离（题干可以下发，正确答案不行） ----------------

def _sanitize_quiz_payload(result):
    """把线程响应里的题卡答案投影掉。

    `thread_service` 的题卡带 `answer` / `reference` / `rubric_points` / `explain`，
    这些只允许进判分逻辑，**不能下发前端**（否则学员直接看答案）。
    覆盖三条真实泄漏路径：
      1. `snapshot()["quiz"]`                      —— 当前题卡
      2. `snapshot()["messages"][*]["payload"]`     —— 历史题卡（JSON 字符串，kind=quiz）
      3. `chat()/pick_question()` 的 `quiz` 字段    —— 新出的题

    注意：`kind=quiz_result` 的历史消息**不剥离** —— 那是学员已经交卷后的判分反馈，
    给出结论（对错/得分/解释）是正常教学行为，不属于「题干泄漏答案」。
    """
    if not isinstance(result, dict):
        return result
    out = dict(result)

    if isinstance(out.get("quiz"), dict):
        out["quiz"] = public_quiz_card(out["quiz"])

    messages = out.get("messages")
    if isinstance(messages, list):
        cleaned = []
        for m in messages:
            if not isinstance(m, dict):
                cleaned.append(m)
                continue
            item = dict(m)
            if str(item.get("kind") or "") == "quiz":
                raw = item.get("payload")
                if isinstance(raw, dict):
                    item["payload"] = public_quiz_card(raw)
                elif isinstance(raw, str) and raw.strip():
                    try:
                        card = json.loads(raw)
                    except (TypeError, ValueError):
                        card = None
                    if isinstance(card, dict):
                        item["payload"] = json.dumps(public_quiz_card(card), ensure_ascii=False)
            cleaned.append(item)
        out["messages"] = cleaned

    # `pick_question()` / `submit_answer()` 的题卡是**扁平**返回（顶层直接就是题卡字段，
    # 不是 {"quiz": card}），所以顶层也要过一遍投影。public_quiz_card 只 pop 那 4 个键，
    # 对快照/chat 的顶层（skill_point_id/name/messages/quiz/kind/content/...）是幂等无害的。
    out = public_quiz_card(out)
    return out


def _data_scope(user_row: dict | None, user_id: str) -> dict:
    """示例数据 / 真实数据口径（R14）。

    唯一权威是 `users.kind`：注册时按 demo-/u-show 前缀把 kind 写成 demo（写入一次），
    之后读取只认 kind，**不做用户名前缀匹配** —— 前缀匹配会误伤真实用户名
    （比如真有人叫 u-demo123 就会被错标成示例数据），也违反「不硬编码用户」的原则。
    只有 users 表里查不到的**认证上线前的历史种子账号**，才按已知 id 精确判定为示例。
    """
    if user_row is not None:
        kind = str(user_row.get("kind") or "").strip() or "real"
        if kind == "demo":
            return {"scope": "example", "label": "标准案例 / 演示数据", "kind": "demo"}
        return {"scope": "real", "label": "真实训练数据", "kind": kind}
    if (user_id or "").strip() in LEGACY_DEMO_IDS:
        return {"scope": "example", "label": "标准案例 / 演示数据", "kind": "legacy-demo"}
    return {"scope": "real", "label": "真实训练数据", "kind": "unknown"}


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()

    # ---------------- 实战评分（真实评分 Agent → 画像写回） ----------------

    @router.post("/practice/orders/{order_id}/score")
    def practice_score_order(order_id: str, uid: str = Depends(current_user)):
        # security v2：严格归属，无公共池放行。只能给自己的单评分。
        own_order(ctx, uid, order_id)
        try:
            llm = ctx.get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        # 评分前快照：用于复盘弹窗展示「本单对画像的影响」。
        before_abilities = ctx.store.abilities(uid)
        try:
            report = ctx.practice.score_order(order_id, llm)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        if not report.get("ok"):
            raise HTTPException(409, report.get("error", "评分失败"))
        # 订单复盘评分是画像的自动更新时间点：只要本次有分数正式写回，
        # 就立刻重算并保存一份画像快照，学员不需要再手动点「更新画像」。
        report["profile_auto_updated"] = False
        if report.get("written"):
            try:
                snapshot = profile_refresh(uid, uid)
                report["profile_auto_updated"] = True
                report["profile_snapshot_id"] = ((snapshot or {}).get("snapshot") or {}).get("id", "")
            except HTTPException as exc:
                # 没有初始画像时只提示，不阻断评分结果。
                report["profile_refresh_error"] = str(exc.detail)
            except Exception as exc:  # noqa: BLE001
                report["profile_refresh_error"] = str(exc)

        # 本单数据、画像变化、下一单难度预览：一次返回给评分复盘弹窗。
        after_abilities = ctx.store.abilities(uid)
        impact_items = []
        for entry in report.get("skill_points") or []:
            sid = str(entry.get("skill_point_id") or "")
            if not sid:
                continue
            before = before_abilities.get(sid) or {}
            after = after_abilities.get(sid) or {}
            before_real = float(before.get("real_v") or 0)
            after_real = float(after.get("real_v") or 0)
            before_has = bool(before.get("real_source") == "practice" or before_real > 0)
            after_has = bool(after.get("real_source") == "practice" or after_real > 0)
            before_value = round(before_real, 1) if before_has else None
            after_value = round(after_real, 1) if after_has else None
            status = str(entry.get("status") or "")
            point = sp_module.SKILL_POINTS_BY_ID.get(sid)
            impact_items.append({
                "skill_point_id": sid,
                "name": getattr(point, "name", sid),
                "dimension": getattr(getattr(point, "dimension", None), "value", ""),
                "before": before_value,
                "after": after_value,
                "delta": round(after_value - before_value, 1)
                if before_value is not None and after_value is not None else None,
                "before_level": mastery_of(before_real).value if before_has else "未评估",
                "after_level": mastery_of(after_real).value if after_has else "未评估",
                "score": entry.get("score"),
                "level": entry.get("level"),
                "status": status,
                "written": status.startswith("已入库"),
            })
        written_items = [i for i in impact_items if i["written"]]

        def _avg(values):
            vals = [v for v in values if v is not None]
            return round(sum(vals) / len(vals), 1) if vals else None

        report["profile_impact"] = {
            "items": impact_items,
            "written": len(written_items),
            "pending": len([i for i in impact_items if not i["written"]]),
            "average_before": _avg([i["before"] for i in written_items]),
            "average_after": _avg([i["after"] for i in written_items]),
        }
        current = ctx.practice.get_order(order_id) or {}
        report["current_order"] = {
            "order_id": order_id,
            "difficulty": current.get("difficulty", ""),
            "target_skill_points": current.get("target_skill_points", []),
        }
        try:
            next_brief = ctx.practice.brief_for(uid)
            next_brief.pop("user_id", None)
            report["next_order"] = next_brief
        except Exception as exc:  # noqa: BLE001 - 预览失败不影响本单评分
            report["next_order_error"] = str(exc)
        return report

    @router.get("/practice/orders/{order_id}/evidence")
    def practice_evidence(order_id: str, uid: str = Depends(current_user)):
        own_order(ctx, uid, order_id)
        rows = ctx.practice.evidence(order_id)
        return [{"kind": r["kind"], "step": r["step"], "ref": r["ref"],
                 "at": r["created_at"], "chars": len(r["text"] or "")} for r in rows]

    # ---------------- 学习地图（真实掌握度） ----------------

    @router.get("/learn/map")
    def learn_map(uid: str = Depends(current_user), user_id: str | None = None):
        # 身份只认会话；查询串里若显式指了别人，直接 403，绝不拿它当身份。
        require_self((user_id or "").strip(), uid, "其他用户的学习地图")
        user_id = uid
        ab = ctx.store.abilities(user_id)
        director = ctx.get_director()
        # 技能点 → 它涉及的事件（教学掌握度 ≥60 才解锁；和事件无关的点留空）
        events_of: dict[str, list] = {}
        for r in INCIDENT_RULES:
            for sp in r["skill_points"]:
                events_of.setdefault(sp, []).append(r)
        dims_out = []
        for d in Dimension:
            pts = []
            for spo in sp_module.SKILL_POINTS:
                if spo.dimension is not d:
                    continue
                row = ab.get(spo.id, {})
                teach = float(row.get("teach") or 0)
                evs = []
                for r in events_of.get(spo.id, []):
                    opened = any(float((ab.get(x) or {}).get("teach") or 0) >= ctx.director.TEACH_UNLOCK
                                 for x in r["skill_points"])
                    evs.append({"code": r["code"], "title": r["title"], "step": r["step"],
                                "channel": r["channel"], "unlocked": opened})
                pts.append({"id": spo.id, "name": spo.name, "checkpoint": spo.checkpoint.value,
                            "teach": teach, "real": float(row.get("real_v") or 0),
                            "events": evs})
            avg_t = round(sum(p["teach"] for p in pts) / len(pts), 1) if pts else 0
            avg_r = round(sum(p["real"] for p in pts) / len(pts), 1) if pts else 0
            dims_out.append({"id": d.value, "name": DIMENSION_NAMES[d], "teach": avg_t, "real": avg_r, "points": pts})
        all_t = [p["teach"] for d in dims_out for p in d["points"]]
        all_r = [p["real"] for d in dims_out for p in d["points"]]
        return {"dimensions": dims_out,
                "overall": {"teach": round(sum(all_t) / len(all_t), 1) if all_t else 0,
                            "real": round(sum(all_r) / len(all_r), 1) if all_r else 0}}

    # ---------------- 技能点对话线程（第 27 章） ----------------

    def _known_sp(sp: str) -> bool:
        """技能点，或文化桥（十大客源国）——文化桥复用同一套对话工作台。"""
        return sp in sp_module.SKILL_POINTS_BY_ID or cb.get(sp) is not None

    @router.get("/threads/{sp}")
    def thread_snapshot(sp: str, uid: str = Depends(current_user), user_id: str | None = None):
        if not _known_sp(sp):
            raise HTTPException(404, f"未知技能点: {sp}")
        require_self((user_id or "").strip(), uid, "其他用户的学习线程")
        user_id = uid
        try:
            return _sanitize_quiz_payload(ctx.get_threads().snapshot(user_id, sp))
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/threads/{sp}/messages")
    def thread_message(sp: str, body: S.ThreadMsg, uid: str = Depends(current_user)):
        """统一入口：讲解 / 问答 / 做题 / 生成讲义都从这一句话进来，服务端分流。"""
        if not _known_sp(sp):
            raise HTTPException(404, f"未知技能点: {sp}")
        _self_of_body(body, uid, "其他用户的学习线程")
        try:
            return _sanitize_quiz_payload(ctx.get_threads().chat(uid, sp, body.text))
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/threads/{sp}/assets")
    def thread_asset(sp: str, body: S.ThreadAssetBody, uid: str = Depends(current_user)):
        if not _known_sp(sp):
            raise HTTPException(404, f"未知技能点: {sp}")
        _self_of_body(body, uid, "其他用户的学习资源")
        try:
            return ctx.get_threads().generate_asset(uid, sp, body.kind)
        except (LLMError, ValueError) as exc:
            raise HTTPException(503, str(exc))

    @router.post("/threads/{sp}/quiz")
    def thread_quiz(sp: str, uid: str = Depends(current_user),
                    body: S.ThreadQuizAnswer | None = None):
        if not _known_sp(sp):
            raise HTTPException(404, f"未知技能点: {sp}")
        if body is not None:
            _self_of_body(body, uid, "其他用户的练习题")
        try:
            return _sanitize_quiz_payload(ctx.get_threads().pick_question(uid, sp))
        except LLMError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/threads/{sp}/quiz/answer")
    def thread_quiz_answer(sp: str, body: S.ThreadQuizAnswer, uid: str = Depends(current_user)):
        if not _known_sp(sp):
            raise HTTPException(404, f"未知技能点: {sp}")
        _self_of_body(body, uid, "其他用户的答题记录")
        try:
            return ctx.get_threads().submit_answer(uid, sp, body.question, body.answer)
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        except Exception as exc:  # noqa: BLE001
            # P0 判分拒绝规则：缺 question_id→400、题目不存在→404、别人的题/别的技能点→403。
            # 服务层异常自带 .status（QuizQuestionMissing/NotFound/Forbidden），这里统一映射。
            status_code = getattr(exc, "status", None)
            if isinstance(status_code, int) and 400 <= status_code <= 599:
                raise HTTPException(status_code, str(exc))
            raise

    # ---------------- 画像 ----------------

    # 画像读写统一走数据库 ability 表（与实时评分同源）：
    # 之前这里读写的是内存里的 LearnerProfile，和评分实际写入的表是两套，导致「怎么调分都不影响难度」。
    def _profile_values(user_id: str) -> dict[str, float]:
        ab = ctx.store.abilities(user_id)
        out: dict[str, float] = {}
        for x in sp_module.SKILL_POINTS:
            row = ab.get(x.id) or {}
            real = float(row.get("real_v") or 0)
            teach = float(row.get("teach") or 0)
            out[x.id] = real if real > 0 else teach
        return out

    def _owned(user_id: str, uid: str, what: str = "其他用户的学习数据") -> str:
        """路径参数形式的归属校验：别人的资料一律 403（security v2 require_self）。"""
        return require_self(user_id, uid, what)

    @router.get("/profiles/{user_id}")
    def get_profile(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        values = _profile_values(user_id)
        weak = [x.id for x in sp_module.SKILL_POINTS if values[x.id] < 70]
        return {
            "user_id": user_id,
            "dimensions": {
                d.value: {"name": DIMENSION_NAMES[d], "value": dimension_value(values, d)}
                for d in Dimension
            },
            "mastery": {
                x.id: {"value": round(values[x.id], 1), "level": mastery_of(values[x.id]).value,
                       "level_name": MASTERY_NAMES[mastery_of(values[x.id])]}
                for x in sp_module.SKILL_POINTS
            },
            "weak_points": weak,
        }

    # ---------------- R14：真实分数趋势（题目口径 / 订单口径 + 均分 + 样本数） ----------------

    def _quiz_series(user_id: str) -> dict:
        """题目口径：quiz_attempt 真实记录，按天聚合准确率与均分。"""
        rows = ctx.store.all_attempts(user_id)
        by_day: dict[str, dict] = {}
        for r in rows:
            day = str(r.get("created_at") or "")[:10]
            if not day:
                continue
            bucket = by_day.setdefault(day, {"total": 0, "correct": 0, "scores": []})
            bucket["total"] += 1
            bucket["correct"] += 1 if r.get("correct") else 0
            try:
                bucket["scores"].append(float(r.get("score") or 0))
            except (TypeError, ValueError):
                pass
        points = []
        for day in sorted(by_day):
            b = by_day[day]
            points.append({
                "date": day,
                "accuracy": round(100.0 * b["correct"] / b["total"], 1) if b["total"] else None,
                "avg_score": round(sum(b["scores"]) / len(b["scores"]), 1) if b["scores"] else None,
                "samples": b["total"],
                "correct": b["correct"],
            })
        return {
            "unit": "题目",
            "unit_key": "quiz",
            "metric": "准确率(%)",
            "total_samples": len(rows),
            "correct": sum(1 for r in rows if r.get("correct")),
            "accuracy": round(100.0 * sum(1 for r in rows if r.get("correct")) / len(rows), 1) if rows else None,
            "avg_score": round(sum(float(r.get("score") or 0) for r in rows) / len(rows), 1) if rows else None,
            "points": points,
        }

    def _order_series(user_id: str) -> dict:
        """订单口径：order_score 真实记录（已经按 biz_order.user_id 过滤为本人订单）。"""
        rows = ctx.store.order_scores_all(user_id)
        by_day: dict[str, list[float]] = {}
        for r in rows:
            day = str(r.get("created_at") or "")[:10]
            if not day:
                continue
            try:
                by_day.setdefault(day, []).append(float(r.get("score") or 0))
            except (TypeError, ValueError):
                continue
        points = [{"date": day, "avg_score": round(sum(v) / len(v), 1), "samples": len(v)}
                  for day, v in sorted(by_day.items())]
        scores = [float(r.get("score") or 0) for r in rows]
        orders = {str(r.get("order_id") or "") for r in rows}
        return {
            "unit": "订单",
            "unit_key": "order",
            "metric": "订单评分(0-100)",
            "total_samples": len(rows),
            "distinct_orders": len(orders - {""}),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "points": points,
        }

    @router.get("/profiles/{user_id}/trend")
    def profile_trend(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        quiz = _quiz_series(user_id)
        order = _order_series(user_id)
        scope = _data_scope(ctx.store.user_by_id(user_id), user_id)

        # 逐日合并（旧图表契约：date=MM-DD，teach=题目口径，real=订单口径）。
        # 只对「当天有真实样本」的点给值；没有样本的另一口径沿用前值仅为画线连续，
        # 因此每点同时给出 samples，前端可据此区分「实测」与「沿用」。
        days = sorted({p["date"] for p in quiz["points"]} | {p["date"] for p in order["points"]})
        quiz_by = {p["date"]: p for p in quiz["points"]}
        order_by = {p["date"]: p for p in order["points"]}
        last_t: float | None = None
        last_r: float | None = None
        trend = []
        for day in days:
            q = quiz_by.get(day)
            o = order_by.get(day)
            if q and q["accuracy"] is not None:
                last_t = q["accuracy"]
            if o and o["avg_score"] is not None:
                last_r = o["avg_score"]
            trend.append({
                "date": day[5:],
                "full_date": day,
                "teach": last_t,
                "real": last_r,
                "quiz_samples": int(q["samples"]) if q else 0,
                "order_samples": int(o["samples"]) if o else 0,
            })
        return {
            "user_id": user_id,
            "data_scope": scope,
            "has_data": bool(quiz["total_samples"] or order["total_samples"]),
            "quiz": quiz,
            "order": order,
            "trend": trend,
        }

    @router.post("/profiles/{user_id}/abilities")
    def set_ability(user_id: str, body: S.AbilityBody, uid: str = Depends(current_user)):
        """手工写能力分是**内部调试面**，不是学员入口。

        理由（R12「不能假增分」）：能力分是评估产物，学员侧的正规写入口只有
        初始测评（/profile/assessment）、答题（/threads/{sp}/quiz/answer）与
        实战评分（/practice/orders/{id}/score）。若把它开放给学员，等于允许自评造假。
        因此：必须显式开 TRIPCRAFT_DEBUG_PROFILE=1，且只能写自己的分。
        """
        require_debug(PROFILE_DEBUG_ENV, "画像写分")
        _owned(user_id, uid)
        if body.field == "real":
            ctx.store.set_ability(user_id, body.skill_point_id, real_v=body.value)
        else:
            ctx.store.set_ability(user_id, body.skill_point_id, teach=body.value)
        return get_profile(user_id, uid)

    # ---------------- 三来源能力雷达与持久化历史 ----------------

    def radar_payload(user_id: str, abilities: dict | None = None) -> dict:
        displayed_abilities = radar_abilities(abilities if abilities is not None else ctx.store.abilities(user_id),
                                            ctx.store.order_scores_all(user_id))
        return build_radar(user_id, displayed_abilities,
                           ctx.store.baseline(user_id), ctx.store.initial_profile_report(user_id),
                           practice_completed_at=ctx.store.completed_practice_at(user_id))

    @router.get("/profiles/{user_id}/radar")
    def profile_radar(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        return radar_payload(user_id)

    @router.get("/profiles/{user_id}/radar/history")
    def profile_radar_history(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        history = ctx.store.profile_snapshots(user_id)
        if not any(item["kind"] == "initial" for item in history):
            initial = radar_payload(user_id)["initial"]
            if any(d["assessed"] for d in initial["dimensions"]):
                history.append({"id": "initial", "kind": "initial", "at": initial["at"]})
        return {"user_id": user_id, "history": history}

    @router.get("/profiles/{user_id}/radar/history/{snapshot_id}")
    def profile_radar_snapshot(user_id: str, snapshot_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        if snapshot_id == "initial":
            radar = initial_only(radar_payload(user_id))
            if not radar["assessed"]:
                raise HTTPException(404, "没有该账号的初始测评记录")
            return {"id": "initial", "kind": "initial", "at": radar["at"], "radar": radar,
                    "report": ctx.store.initial_profile_report(user_id)}
        snapshot = ctx.store.profile_snapshot(user_id, snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "未找到该账号的画像历史记录")
        return snapshot

    # ---------------- 画像 Agent：初始画像测评 + 动态刷新（D-066） ----------------

    def load_report(user_id: str) -> dict:
        row = ctx.store.latest_memory(user_id, REPORT_TYPE)
        if not row:
            return {}
        try:
            data = json.loads(row.get("content") or "{}")
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        data["created_at"] = data.get("created_at") or row.get("created_at") or ""
        return data

    def recent_order_scores(user_id: str) -> list[dict]:
        """按订单聚合成一条：均分 + 档位 + 一句评语（给画像 Agent 当证据）。"""
        agg: dict[str, dict] = {}
        for r in ctx.store.order_scores_all(user_id):
            oid = r.get("order_id") or ""
            bucket = agg.setdefault(oid, {"scores": [], "levels": [], "comment": ""})
            try:
                bucket["scores"].append(float(r.get("score") or 0))
            except (TypeError, ValueError):
                pass
            if r.get("level"):
                bucket["levels"].append(str(r["level"]))
            if not bucket["comment"] and r.get("comment"):
                bucket["comment"] = str(r["comment"])
        out = []
        for oid, bucket in agg.items():
            order = ctx.store.order(oid) or {}
            avg = round(sum(bucket["scores"]) / len(bucket["scores"]), 1) if bucket["scores"] else 0
            out.append({"order_id": oid, "destination": order.get("destination", ""),
                        "level": (bucket["levels"] or [""])[0], "score": f"{avg}",
                        "comment": bucket["comment"][:80]})
        return out

    def profile_llm():
        try:
            return ctx.get_llm()
        except LLMError:
            return None      # 没有模型也要能出画像（走确定性模板）

    @router.get("/profile/quiz")
    def profile_quiz():
        return {"questions": profile_agent.questions_public(),
                "total": len(profile_agent.QUIZ),
                "dimensions": [{"id": d.value, "name": DIMENSION_NAMES[d]} for d in Dimension]}

    # ---------------- 学习路线管家（初始画像 + 学习需求） ----------------

    @router.get("/profiles/{user_id}/learning-route")
    def get_learning_route(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        route = learning_route.latest_route(ctx.store, user_id)
        return {"route": route, "has_profile": ctx.store.has_profile_data(user_id)}

    @router.post("/profiles/{user_id}/learning-route")
    def create_learning_route(user_id: str, body: S.LearningRouteBody,
                              uid: str = Depends(current_user)):
        _owned(user_id, uid)
        return {"route": learning_route.generate_route(ctx.store, user_id, body.demand),
                "has_profile": ctx.store.has_profile_data(user_id)}

    @router.post("/profiles/{user_id}/learning-route/revise")
    def revise_learning_route(user_id: str, body: S.LearningRouteReviseBody,
                              uid: str = Depends(current_user)):
        _owned(user_id, uid)
        if not body.message.strip():
            raise HTTPException(400, "请先告诉管家希望怎么调整路线")
        return {"route": learning_route.revise_route(ctx.store, user_id, body.message),
                "has_profile": ctx.store.has_profile_data(user_id)}
    @router.get("/profiles/{user_id}/intake")
    def profile_intake(user_id: str, uid: str = Depends(current_user)):
        """初始测评可补做一次；已有做题或实战记录不关闭入口。"""
        _owned(user_id, uid)
        has_data = ctx.store.has_profile_data(user_id)
        has_assessment = ctx.store.has_initial_assessment(user_id)
        report = load_report(user_id)
        return {"user_id": user_id, "has_profile_data": has_data,
                "has_initial_assessment": has_assessment,
                "can_assess": not has_assessment, "has_report": bool(report),
                "report": report}

    @router.post("/profile/assessment")
    def profile_assessment(body: S.AssessmentBody, uid: str = Depends(current_user)):
        _self_of_body(body, uid, "其他用户的画像")
        user_id = uid
        if ctx.store.has_initial_assessment(user_id):
            raise HTTPException(409, "该账号已完成初始测评，请用「更新画像」刷新当前学情。")
        answers = [a for a in (body.answers or []) if isinstance(a, dict)]
        if len(answers) < len(profile_agent.QUIZ):
            raise HTTPException(400, f"请完成全部 {len(profile_agent.QUIZ)} 道题再提交")
        scores = profile_agent.score_answers(answers)
        user_row = ctx.store.user_by_id(user_id) or {}
        from tripcraft.services import demo_blank_state
        blank_demo = user_row.get("username") == demo_blank_state.USERNAME
        if blank_demo:
            scores = demo_blank_state.normalize_assessment_scores(scores)
        # 空白演示账号使用确定性画像，避免模型写成与分数不一致的“标准案例”摘要。
        agent = profile_agent.ProfileAgent(None if blank_demo else profile_llm())
        report = agent.assess(answers, scores, sp_module.SKILL_POINTS, language=body.language)
        existing_abilities = ctx.store.abilities(user_id)
        for spo in sp_module.SKILL_POINTS:
            # 补做初始测评只初始化缺失项，已通过学习或实战形成的能力值继续保留。
            if spo.id not in existing_abilities:
                ctx.store.set_ability(user_id, spo.id, teach=float(scores.get(spo.dimension.value, 0)), source="initial")
        # 初始快照单独落 profile_baseline：ability.teach 之后会被练习/刷新覆盖，不能当初始口径
        for d in Dimension:
            ctx.store.save_baseline(user_id, d.value, float(scores.get(d.value, 0)), source="intake")
        radar = build_radar(user_id, ctx.store.abilities(user_id), ctx.store.baseline(user_id), report)
        saved = ctx.store.save_profile_snapshot(user_id, "initial", radar, report)
        return {**saved, "scores": scores, "user_id": user_id}

    @router.get("/profiles/{user_id}/report")
    def profile_report(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        return {"report": load_report(user_id)}

    @router.post("/profiles/{user_id}/refresh")
    def profile_refresh(user_id: str, uid: str = Depends(current_user)):
        _owned(user_id, uid)
        abilities = radar_abilities(ctx.store.abilities(user_id), ctx.store.order_scores_all(user_id))
        radar = radar_payload(user_id, abilities)
        initial_values = {row["id"]: row["value"] for row in radar["initial"]["dimensions"]}
        learning_values = {row["id"]: row["value"] for row in radar["learning"]["dimensions"]}
        practice_values = {row["id"]: row["value"] for row in radar["practice"]["dimensions"]}
        # 定性报告与雷达使用同一份维度结果，避免把未涉及技能点当作零分拉低均分。
        dims = {dim.value: {"name": DIMENSION_NAMES[dim],
                            "teach": learning_values[dim.value] if learning_values[dim.value] is not None else initial_values[dim.value] or 0,
                            "real": practice_values[dim.value] if practice_values[dim.value] is not None else initial_values[dim.value] or 0}
                for dim in Dimension}
        if not radar["assessed"]:
            raise HTTPException(409, "还没有画像数据：先做一次初始画像测评。")
        agent = profile_agent.ProfileAgent(profile_llm())
        report = agent.refresh(dims, sp_module.SKILL_POINTS, abilities,
                               orders=recent_order_scores(user_id),
                               attempts=ctx.store.all_attempts(user_id),
                               previous=load_report(user_id))
        return ctx.store.save_profile_snapshot(user_id, "refresh", radar, report)

    return router
