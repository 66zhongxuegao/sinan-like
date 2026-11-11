"""场景域路由：标准案例目录 / 导入 / 重置 / 模式与依赖状态。

对外契约：`build(ctx) -> APIRouter`（与其它域一致）。属主：scenario 域。

安全边界：
- 所有端点都要登录：统一走 `security.current_user`，**不信任**调用方传来的 user_id。
- 导入/重置只作用于当前登录账号；重置的删除清单逐表返回，便于核对「只影响当前示例账号」。
- `provider/offline`（离线确定性响应器）是**进程级**开关：默认只允许标准案例的演示账号
  开启，或显式设置环境变量 `TRIPCRAFT_SCENARIO_TOGGLE=on` 才放开；否则 403 并说明原因。
- 请求体不新增 DTO：需要参数的端点用 query 参数，避免改动 Lead 单写的 schemas.py。
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException, Request

from tripcraft.api.context import AppContext
from tripcraft.api.security import current_user, own_order
from tripcraft.contracts import stages as stage_contract
from tripcraft.services import scenario_service as sc


def _service(ctx: AppContext) -> sc.ScenarioService:
    """每个 app 一个 ScenarioService（provider 开关是进程级状态，必须共用一个）。

    环境变量 `TRIPCRAFT_SCENARIO_MODE=offline` 时，本进程第一次用到场景域就自动进入
    离线确定性模式（全局调试开关；`/scenario/status` 会如实标注 scope=process）。
    """
    svc = getattr(ctx, "_scenario", None)
    if svc is None:
        svc = sc.ScenarioService(ctx)
        setattr(ctx, "_scenario", svc)
        try:
            svc.ensure_env_mode()
        except sc.ScenarioError:
            pass                     # 资料缺失不阻断装配；/scenario/status 会报 live
    return svc


def _require_demo_instance(as_conflict: bool = False) -> dict:
    """内部演示路由开关：只有**启动期显式开启的内部演示实例**才能导入/重置/校准/切模型。

    普通实例（未开 TRIPCRAFT_DEMO_TOURIST）一律拒绝 —— 公开场景入口不能把正常训练实例
    偷偷切成固定演示（替换随机游客必须来自后台启动配置，不来自账号名 / UI / 请求体）。
    `as_conflict=True`（provider 模式开关）返回 409：这是「运行期无法切换、必须启动期声明」
    的状态冲突，沿用既有对外契约；其余内部动作返回 403。
    """
    info = sc.demo_instance()
    if not info["enabled"]:
        detail = ("本实例未声明为演示实例，运行期不能切换模型模式（须启动期声明）："
                  + str(info.get("reason") or ""))
        if as_conflict:
            raise HTTPException(409, detail)
        raise HTTPException(403, "本实例不是内部演示实例（未开启固定案例替换）："
                                 + str(info.get("reason") or ""))
    return info


def _can_toggle_provider(ctx: AppContext, user_id: str) -> tuple[bool, str]:
    if os.environ.get("TRIPCRAFT_SCENARIO_TOGGLE", "").strip().lower() in ("on", "1", "true"):
        return True, "环境变量 TRIPCRAFT_SCENARIO_TOGGLE 已放开"
    try:
        user = ctx.get_auth().user(user_id) or {}
    except Exception as exc:                      # 认证模块未就绪：不放行
        return False, f"认证模块不可用（{type(exc).__name__}），按默认拒绝"
    names = set()
    for c in sc.list_cases():
        iso = c.get("isolation") or {}
        for k in ("demo_account_username", "replay_account_username", "debug_account_username"):
            v = str(iso.get(k) or "")
            if v:
                names.add(v)
    if str(user.get("username") or "") in names:
        return True, "调用方是标准案例演示账号（成品 verified / 现场 replay / 排查留存 之一）"
    return False, ("进程级模型开关默认关闭：仅标准案例演示账号或 TRIPCRAFT_SCENARIO_TOGGLE=on 可用；"
                   "需要离线演示请在启动脚本里设置该变量")


def build(ctx: AppContext) -> APIRouter:
    router = APIRouter()

    # ---------------- 目录 ----------------

    @router.get("/scenario/cases")
    def scenario_cases(request: Request):
        """标准案例目录（含六阶段计划与固定资料摘要）；需登录。"""
        current_user(request)
        return _service(ctx).catalog()

    @router.get("/scenario/cases/{case_id}")
    def scenario_case(case_id: str, request: Request):
        current_user(request)
        try:
            return _service(ctx).case_view(case_id)
        except sc.ScenarioError as exc:
            raise HTTPException(404, str(exc))

    @router.get("/scenario/status")
    def scenario_status(request: Request, probe: bool = False):
        """当前模式与实时依赖状态。

        `probe=1` 时**真发一次**最小模型请求核验连通（需要 key）；默认只报配置是否存在，
        并明确写清「未核验」的原因，不把 key 存在当成可用。
        """
        current_user(request)
        out = _service(ctx).status(probe_llm=probe)
        # 实例级开关（启动期后台配置）：前端据此决定是否暴露内部排查入口
        out["demo_instance"] = sc.demo_instance()
        return out

    # ---------------- 导入 / 重置（只作用于当前登录账号） ----------------

    @router.post("/scenario/cases/{case_id}/import")
    def scenario_import(case_id: str, request: Request):
        _require_demo_instance()
        """把标准案例的固定资料落成一条真实订单（走 PracticeService.spawn_order）。"""
        uid = current_user(request)
        try:
            return _service(ctx).import_case(uid, case_id)
        except sc.ScenarioError as exc:
            raise HTTPException(400, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @router.post("/scenario/cases/{case_id}/reset")
    def scenario_reset(case_id: str, request: Request, include_profile: bool = True,
                       all_orders: bool = False):
        """重置当前登录账号的标准案例数据（默认连同该账号的学习/画像数据）。

        只删当前账号名下记录；删除清单逐表返回，便于核对隔离边界。
        """
        _require_demo_instance()
        uid = current_user(request)
        try:
            return _service(ctx).reset(uid, case_id, include_profile=include_profile,
                                       all_orders=all_orders)
        except sc.ScenarioError as exc:
            raise HTTPException(400, str(exc))

    @router.get("/scenario/account")
    def scenario_account(request: Request, case_id: str = ""):
        """当前账号的标准案例数据计数（重置前后对比、A/B 隔离核对用）。"""
        uid = current_user(request)
        return _service(ctx).counts(uid)

    @router.get("/scenario/orders/{order_id}/state")
    def scenario_order_state(order_id: str, request: Request):
        """标准案例订单的服务端状态（每步证据）：六阶段映射取自 contracts/stages.py。

        归属校验走 `security.own_order`：不是自己的单 403，不存在 404。
        """
        uid = current_user(request)
        row = own_order(ctx, uid, order_id)
        payload = json.loads(row.get("payload") or "{}")
        detail = ctx.practice.order_detail(order_id) or {}
        gate = detail.get("gate") or {}
        step = str(gate.get("step") or "")
        deliverables = [d.get("deliverable_id") for d in ctx.store.deliverables(order_id)]
        abilities = ctx.store.abilities(uid)
        scored = ctx.store.order_scores(order_id)
        return {
            "order_id": order_id,
            "scenario_id": payload.get("scenario_id", ""),
            "demo_label": payload.get("scenario_label", ""),
            "demo_data": bool(payload.get("demo_data")),
            "status": row.get("status"),
            "stage_index": row.get("stage_index"),
            "stage_name": gate.get("stage_name", ""),
            "stage_id": stage_contract.stage_of_step(step),
            "stage_of_step_contract_version": 1,
            "internal_step": step,
            "gate": gate,
            "actions": sorted(ctx.store.action_keys(order_id)),
            "evidence_count": len(ctx.store.evidence(order_id)),
            "deliverables": deliverables,
            "incidents": [{"code": i["code"], "title": i["title"], "channel": i["channel"]}
                          for i in ctx.store.incidents(order_id)],
            "scores": {
                "evaluated": len(scored),
                "pending_review": len(ctx.store.pending_reviews(order_id)),
                "average": (round(sum(r["score"] for r in scored.values()) / len(scored))
                            if scored else None),
            },
            "ability_written": {k: {"real_v": v.get("real_v"), "teach": v.get("teach")}
                                for k, v in abilities.items()
                                if (v.get("real_v") or 0) > 0 or (v.get("teach") or 0) > 0},
        }

    # ---------------- 演示实例的离线 provider（启动期声明，不做运行期全局切换） ----------------

    @router.post("/scenario/provider/offline")
    def scenario_provider_offline(request: Request):
        _require_demo_instance(as_conflict=True)
        """确认/进入确定性离线模式（**仅演示实例**）。

        需要实例以 `TRIPCRAFT_SCENARIO_MODE=offline` 启动；否则 409 并说明正确启动方式。
        该模式只影响本实例（专用演示实例），普通生产实例不受影响。
        """
        uid = current_user(request)
        allowed, why = _can_toggle_provider(ctx, uid)
        if not allowed:
            raise HTTPException(403, why)
        case = sc.list_cases()[0]
        try:
            out = _service(ctx).activate_offline(str(case.get("case_id")))
        except sc.ScenarioError as exc:
            raise HTTPException(409, str(exc))
        out["reason"] = why
        out["demo_label"] = case.get("demo_label") or sc.DEMO_LABEL
        out["instance_mode"] = "demo"
        return out

    @router.post("/scenario/provider/live")
    def scenario_provider_live(request: Request):
        _require_demo_instance(as_conflict=True)
        """演示实例内回到真实模型（常规实例本来就没有开启过，不存在被影响的情况）。"""
        uid = current_user(request)
        if os.environ.get("TRIPCRAFT_SCENARIO_MODE", "").strip().lower() != "offline":
            raise HTTPException(
                409, "本实例不是演示实例（未设置 TRIPCRAFT_SCENARIO_MODE=offline）：常规实例始终走真实模型，"
                     "无需也无法运行期切换")
        allowed, why = _can_toggle_provider(ctx, uid)
        if not allowed:
            raise HTTPException(403, why)
        out = _service(ctx).deactivate()
        out["reason"] = why
        return out

    # ---------------- 校准（离线不伪造结果，live 才跑真实标定） ----------------

    @router.post("/scenario/cases/{case_id}/calibrate")
    def scenario_calibrate(case_id: str, request: Request, repeats: int = 1,
                           use_scenario_provider: bool = True):
        _require_demo_instance()
        uid = current_user(request)
        allowed, why = _can_toggle_provider(ctx, uid)
        if not allowed:
            raise HTTPException(403, why)
        svc = _service(ctx)
        try:
            sc.get_case(case_id)          # 未知案例 → ScenarioError → 404
            out = svc.calibrate(repeats=repeats, use_scenario_provider=use_scenario_provider)
        except sc.ScenarioError as exc:
            raise HTTPException(400, str(exc))
        out["reason"] = why
        return out

    return router
