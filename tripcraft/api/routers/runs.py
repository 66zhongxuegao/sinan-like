"""训练与评测域：Run 状态机演练 + S2 垂直切片会话。

本模块由 api/app.py 的路由块机械拆分而来（见 docs/携程改版说明.txt）。
对外契约：`build(ctx) -> APIRouter`，ctx 为 tripcraft.api.context.AppContext。

安全（v2，监督者静态审查后收紧）：
- 所有 /runs、/s2 路由都必须带真实会话，并且**按归属**校验：
  Run 与 S2Session 记的 user_id 必须等于当前登录用户；请求体里的 user_id 不得冒用他人。
- 原始状态机控制入口（flags 改名、rollback 回退）默认 404，需要显式
  TRIPCRAFT_DEBUG_RUNS=1 才开放——普通学员不应能任意搬动考核状态。
  advance 是状态机自身的合法前进（仍受 gate() 约束），保持对学员开放但严格归属。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from tripcraft.agents.llm import LLMError
from tripcraft.api import schemas as S
from tripcraft.api.context import AppContext
from tripcraft.api.security import current_user, debug_enabled, require_debug
from tripcraft.contracts.deliverables import Deliverable
from tripcraft.contracts.enums import DIMENSION_NAMES, STEP_NAMES, Dimension, StepId
from tripcraft.contracts.profile import LearnerProfile, dimension_value
from tripcraft.contracts.task import TaskInstance
from tripcraft.engine.state_machine import Run
from tripcraft.services.s2_session import S2Session

RUNS_DEBUG_ENV = "TRIPCRAFT_DEBUG_RUNS"


def build(ctx: AppContext) -> APIRouter:
    """装配本域路由。每个 app 实例调用一次。"""
    router = APIRouter()

    # ---------------- 演练与状态机 ----------------

    def snapshot(run: Run) -> dict:
        outcome = run.gate()
        return {
            "instance_id": run.instance.id,
            "current_step": run.instance.current_step.value,
            "current_step_name": STEP_NAMES[run.instance.current_step],
            "order_status": run.instance.status.value,
            "steps": [
                {"step": s.value, "name": STEP_NAMES[s], "status": run.steps[s].status.value}
                for s in StepId
            ],
            "gate": {"passed": outcome.passed, "reasons": outcome.reasons, "hard": outcome.hard},
            "deliverables": [d.kind.value for d in run.deliverables],
            "flags": dict(run.flags),
            "log": run.log[-20:],
        }

    def get_run(run_id: str, user_id: str) -> Run:
        """按归属取演练：不存在 404，不属于当前用户 403。"""
        run = ctx.runs.get(run_id)
        if run is None:
            raise HTTPException(404, f"未找到演练: {run_id}")
        if (run.instance.user_id or "") != user_id:
            raise HTTPException(403, "无权访问该演练")
        return run

    @router.post("/runs")
    def create_run(body: S.CreateRun, user: str = Depends(current_user)):
        # 身份一律取服务端会话，请求体里的 user_id 不参与建单（防冒用）
        user_id = user
        inst = TaskInstance(id=f"run-{len(ctx.runs) + 1}", template_id=body.template_id,
                            user_id=user_id, inbound=body.inbound, language=body.language)
        run = Run(instance=inst)
        ctx.runs[inst.id] = run
        ctx.profiles.setdefault(user_id, LearnerProfile(user_id=user_id))
        return snapshot(run)

    @router.get("/runs/{run_id}")
    def get_run_state(run_id: str, user: str = Depends(current_user)):
        return snapshot(get_run(run_id, user))

    @router.post("/runs/{run_id}/advance")
    def advance(run_id: str, user: str = Depends(current_user)):
        run = get_run(run_id, user)
        result = run.advance()
        return {"ok": result.ok, "from": result.from_step.value, "to": result.to_step.value,
                "reason": result.reason, "hard_blocked": result.hard_blocked, "state": snapshot(run)}

    @router.post("/runs/{run_id}/rollback")
    def rollback(run_id: str, body: S.RollbackBody, user: str = Depends(current_user)):
        require_debug(RUNS_DEBUG_ENV, "状态机回退")
        run = get_run(run_id, user)
        result = run.rollback(body.to_step, body.reason)
        return {"ok": result.ok, "from": result.from_step.value, "to": result.to_step.value,
                "reason": result.reason, "state": snapshot(run)}

    @router.post("/runs/{run_id}/flags")
    def set_flag(run_id: str, body: S.FlagBody, user: str = Depends(current_user)):
        require_debug(RUNS_DEBUG_ENV, "状态机旗标")
        run = get_run(run_id, user)
        run.set_flag(body.name, body.value)
        return snapshot(run)

    @router.post("/runs/{run_id}/deliverables")
    def add_deliverable(run_id: str, body: S.DeliverableBody, user: str = Depends(current_user)):
        run = get_run(run_id, user)
        d = Deliverable(id=f"d-{len(run.deliverables) + 1}", instance_id=run.instance.id,
                        kind=body.kind, step=body.step, payload=body.payload)
        run.add_deliverable(d)
        return snapshot(run)

    # ---------------- S2 垂直切片（M1） ----------------

    def get_s2(sid: str, user_id: str) -> S2Session:
        sess = ctx.s2_sessions.get(sid)
        if sess is None:
            raise HTTPException(404, "未找到会话")
        if (sess.user_id or "") != user_id:
            raise HTTPException(403, "无权访问该会话")
        return sess

    @router.post("/s2/sessions")
    def create_s2(body: S.CreateS2, user: str = Depends(current_user)):
        try:
            llm = ctx.get_llm()
        except LLMError as exc:
            raise HTTPException(503, str(exc))
        sid = f"s2-{len(ctx.s2_sessions) + 1}"
        sess = S2Session(user_id=user, llm=llm, inbound=body.inbound,
                         instance_id=sid, language=body.language)
        opening = sess.start()
        ctx.s2_sessions[sid] = sess
        ctx.profiles.setdefault(user, LearnerProfile(user_id=user))
        return {"session_id": sid, "customer_opening": opening, "snapshot": sess.snapshot()}

    @router.post("/s2/sessions/{sid}/messages")
    def s2_send(sid: str, body: S.SendMessage, user: str = Depends(current_user)):
        sess = get_s2(sid, user)
        reply = sess.send(body.text)
        return {"customer_reply": reply, "snapshot": sess.snapshot()}

    @router.post("/s2/sessions/{sid}/finish")
    def s2_finish(sid: str, user: str = Depends(current_user)):
        sess = get_s2(sid, user)
        prof = ctx.profiles.setdefault(sess.user_id, LearnerProfile(user_id=sess.user_id))
        report = sess.finish(profile=prof)
        values = prof.values()
        report["profile"] = {
            "dimensions": {d.value: {"name": DIMENSION_NAMES[d], "value": dimension_value(values, d)}
                           for d in Dimension},
            "weak_points": prof.weak_points(),
        }
        return report

    @router.get("/s2/sessions/{sid}")
    def s2_get(sid: str, user: str = Depends(current_user)):
        return get_s2(sid, user).snapshot()

    # ---------------- 调试面可见性（供前端/脚本判断，不含敏感信息） ----------------

    @router.get("/runs/debug/status")
    def runs_debug_status(user: str = Depends(current_user)):
        """便于验收脚本确认原始状态机控制面是否开放；不随调用者变化。"""
        return {"runs_debug": debug_enabled(RUNS_DEBUG_ENV)}

    return router
