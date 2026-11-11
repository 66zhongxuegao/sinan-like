"""场景路由装配自检（scenario-api 的交付验收脚本）。

跑法：
    python -X utf8 scripts/acceptance_scenario_api.py

security v2 已删除 TRIPCRAFT_AUTH=off 身份直通：本脚本一律用**真实注册/登录**拿会话，
在独立临时库上把 routers/scenario.py 单独挂到最小 FastAPI，验证端点与权限边界
（未登录 401、越权 403/404、只影响当前账号）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_db = Path(tempfile.gettempdir()) / "tripcraft_scenario_api.sqlite"
if _db.exists():
    _db.unlink()
os.environ["TRIPCRAFT_DB"] = str(_db)
os.environ.pop("TRIPCRAFT_SCENARIO_TOGGLE", None)
os.environ["TRIPCRAFT_BOOTSTRAP_ORDERS"] = "1"

from fastapi import FastAPI                            # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

from tripcraft.api.context import AppContext           # noqa: E402
from tripcraft.api.routers import auth as auth_router  # noqa: E402
from tripcraft.api.routers import scenario as scenario_router   # noqa: E402
from tripcraft.api.security import install_auth        # noqa: E402
from tripcraft.contracts import stages as stage_contract        # noqa: E402

def _out_base() -> Path:
    """--output-dir <dir> 可换输出根目录（默认 output/acceptance，旧证据不被覆盖）。"""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--output-dir" and i + 1 < len(argv):
            return Path(argv[i + 1]).resolve()
        if a.startswith("--output-dir="):
            return Path(a.split("=", 1)[1]).resolve()
    return ROOT / "output" / "acceptance"


_OUT = _out_base()
EVID = _OUT / "evidence" / "scenario-api"
LOGS = _OUT / "logs"
EVID.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)
STEPS: list[dict] = []

DEMO_USER, DEMO_PASS = "demo-linxiao-verified-20261017", "LvyuanDemo#2026"
OTHER_USER, OTHER_PASS = "realcase-ab-01", "RealCase#2026"


def check(name: str, ok: bool, detail: dict | None = None) -> None:
    STEPS.append({"step": name, "ok": bool(ok), "detail": detail or {}})
    print(f"  [{'OK ' if ok else 'NG '}] {name}"
          + (f" → {json.dumps(detail, ensure_ascii=False)[:220]}" if detail else ""))


def main() -> int:
    app = FastAPI()
    ctx = AppContext()
    app.state.ctx = ctx
    app.include_router(auth_router.build(ctx))
    app.include_router(scenario_router.build(ctx))
    install_auth(app, ctx)
    c = TestClient(app)

    print("=" * 74)
    print("场景路由装配自检（独立库 / 真实注册登录 / security v2）")
    print("=" * 74)

    # ---- 未登录一律 401 ----
    for path in ("/scenario/cases", "/scenario/status", "/scenario/account"):
        r = c.get(path)
        check(f"未登录 {path} → 401", r.status_code == 401, {"status": r.status_code})

    # ---- 真实注册（demo- 前缀 → kind=demo，注册不初始化派单）----
    r = c.post("/auth/register", json={"username": DEMO_USER, "password": DEMO_PASS})
    reg = r.json()
    check("注册 demo 账号 200 且拿到 token", r.status_code == 200 and bool(reg.get("token")),
          {"status": r.status_code, "user_id": reg.get("user_id"), "kind": reg.get("kind")})
    check("demo 账号不初始化派单", reg.get("bootstrap", {}).get("seeded") is False,
          reg.get("bootstrap"))
    demo_tok = {"Authorization": f"Bearer {reg.get('token','')}"}

    r = c.post("/auth/register", json={"username": OTHER_USER, "password": OTHER_PASS})
    other_reg = r.json()
    other_tok = {"Authorization": f"Bearer {other_reg.get('token','')}"}
    check("对照账号注册（kind=real）",
          other_reg.get("kind") == "real" and bool(other_reg.get("token")),
          {"kind": other_reg.get("kind")})

    # ---- 目录 / 状态 ----
    r = c.get("/scenario/cases", headers=demo_tok)
    body = r.json()
    check("GET /scenario/cases 200", r.status_code == 200, {"status": r.status_code})
    ids = [s["id"] for s in body.get("stage_plan") or []]
    check("六阶段口径来自 contracts/stages.py", ids == list(stage_contract.STAGE_ORDER),
          {"stages": ids})
    check("目录带演示标识",
          (body.get("cases") or [{}])[0].get("demo_label") == "标准案例/演示数据",
          {"label": (body.get("cases") or [{}])[0].get("demo_label")})

    r = c.get("/scenario/status", headers=demo_tok)
    st = r.json()
    check("GET /scenario/status 200", r.status_code == 200, {"mode": st.get("mode")})
    check("状态区分「key 存在」与「连通已核验」",
          {"llm_key_present", "llm_connectivity_verified", "llm_not_verified_reason",
           "voice_key_present", "voice_connectivity_verified", "voice_not_verified_reason",
           "db_path", "auth_mode"} <= set(st.get("deps") or {}), st.get("deps"))
    check("未核验时不谎报连通",
          st["deps"]["llm_connectivity_verified"] is False
          and bool(st["deps"]["llm_not_verified_reason"]),
          {"reason": st["deps"]["llm_not_verified_reason"]})
    check("认证按 security v2 如实报告（不读已删除的 TRIPCRAFT_AUTH）",
          "always-on" in st["deps"]["auth_mode"] and "TRIPCRAFT_AUTH" not in st["deps"],
          {"auth_mode": st["deps"]["auth_mode"]})
    check("未声明演示实例时 mode=live（不虚报离线）", st.get("mode") == "live",
          {"mode": st.get("mode")})

    r = c.get("/scenario/cases/not-exist", headers=demo_tok)
    check("未知案例 404", r.status_code == 404, {"status": r.status_code})

    # ---- 导入：真实服务落单 ----
    r = c.post("/scenario/cases/hk-huang-yunnan-5d/import", headers=demo_tok)
    imp = r.json()
    check("POST import 200", r.status_code == 200, {"status": r.status_code, "order_id": imp.get("order_id")})
    check("import 带标准案例标记",
          imp.get("scenario_marker", {}).get("scenario_id") == "hk-huang-yunnan-5d",
          imp.get("scenario_marker"))
    check("import 注入固定资源约束", len(imp.get("resources_injected") or []) == 4,
          {"kinds": [x["kind"] for x in imp.get("resources_injected") or []]})
    oid = imp.get("order_id")

    r = c.get("/scenario/account", headers=demo_tok)
    check("demo 账号：1 条标准案例订单",
          r.json().get("scenario_orders") == 1, r.json())

    # ---- order state：归属校验 ----
    r = c.get(f"/scenario/orders/{oid}/state", headers=demo_tok)
    state = r.json()
    check("自己的订单 state 200", r.status_code == 200, {"status": r.status_code})
    check("state 带六阶段映射与演示标识",
          bool(state.get("stage_id")) and state.get("demo_data") is True,
          {"stage_id": state.get("stage_id"), "stage": state.get("stage_name"),
           "demo_label": state.get("demo_label")})
    check("state 的 stage_of_step 与契约一致",
          state.get("stage_id") == stage_contract.stage_of_step(state.get("internal_step", "")),
          {"internal_step": state.get("internal_step"), "stage_id": state.get("stage_id")})
    r = c.get(f"/scenario/orders/{oid}/state", headers=other_tok)
    check("另一账号访问该订单 403（越权不泄漏）", r.status_code == 403, {"status": r.status_code})
    r = c.get("/scenario/orders/9999999999999999/state", headers=demo_tok)
    check("不存在的订单 404", r.status_code == 404, {"status": r.status_code})

    # ---- 账号隔离：另一账号计数不受影响 ----
    other_before = c.get("/scenario/account", headers=other_tok).json()
    check("对照账号看不到 demo 的案例单",
          other_before.get("scenario_orders") == 0 and other_before.get("orders") >= 1,
          other_before)

    # ---- 重置：只影响当前账号 ----
    r = c.post("/scenario/cases/hk-huang-yunnan-5d/reset", headers=demo_tok)
    reset = r.json()
    check("POST reset 200 且订单清零",
          r.status_code == 200 and reset["after"]["orders"] == 0,
          {"before": reset["before"]["orders"], "after": reset["after"]["orders"]})
    check("reset 返回逐表删除清单", bool(reset.get("deleted")), reset.get("deleted"))
    check("reset 残留检查全 0（先子后父 + 单事务）",
          reset.get("residual_clean") is True
          and all(v == 0 for v in (reset.get("residual") or {}).values()),
          {"residual_nonzero": {k: v for k, v in (reset.get("residual") or {}).items() if v},
           "transaction": reset.get("transaction")})
    other_after = c.get("/scenario/account", headers=other_tok).json()
    check("reset 后对照账号数据不变",
          other_before.get("orders") == other_after.get("orders"),
          {"before": other_before.get("orders"), "after": other_after.get("orders")})

    # ---- provider 作用域：常规实例拒绝运行期切换；演示实例（启动变量）才允许 ----
    r = c.post("/scenario/provider/offline", headers=demo_tok)
    check("常规实例（未声明 TRIPCRAFT_SCENARIO_MODE）拒绝开启确定性模式 → 409",
          r.status_code == 409, {"status": r.status_code,
                                 "detail": str(r.json().get("detail"))[:80]})
    os.environ["TRIPCRAFT_SCENARIO_MODE"] = "offline"      # 模拟「独立演示实例」的启动声明
    r = c.post("/scenario/provider/offline", headers=demo_tok)
    off = r.json()
    check("演示实例内 demo 账号可进入离线模式",
          r.status_code == 200 and off.get("mode") == "offline",
          {"status": r.status_code, "mode": off.get("mode"), "scope": off.get("scope")})
    st2 = c.get("/scenario/status", headers=demo_tok).json()
    check("status 标注 scope=instance / demo_instance",
          st2.get("scope") == "instance" and st2.get("demo_instance") is True,
          {"scope": st2.get("scope"), "mode": st2.get("mode")})
    r = c.post("/scenario/provider/offline", headers=other_tok)
    check("真实账号不能切模型模式（403）", r.status_code == 403,
          {"status": r.status_code, "detail": str(r.json().get("detail"))[:70]})
    r = c.post("/scenario/provider/live", headers=demo_tok)
    check("演示实例内可回到实时模式",
          r.status_code == 200 and r.json().get("mode") == "live",
          {"status": r.status_code, "mode": r.json().get("mode")})
    os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)

    # ---- 重放：重置后再导入，固定字段一致 ----
    r2 = c.post("/scenario/cases/hk-huang-yunnan-5d/import", headers=demo_tok)
    imp2 = r2.json()
    check("重放后固定字段与首轮一致",
          imp2.get("fixed_fields") == imp.get("fixed_fields"),
          {"dates": imp2.get("fixed_fields", {}).get("dates")})
    c.post("/scenario/cases/hk-huang-yunnan-5d/reset", headers=demo_tok)

    ok = all(s["ok"] for s in STEPS)
    out = {"script": "acceptance_scenario_api.py", "ok": ok, "db": os.environ["TRIPCRAFT_DB"],
           "auth_mode": "on（真实注册/登录，无直通旁路）", "steps": STEPS}
    (EVID / "router-wiring.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    (LOGS / "scenario-api-wiring.log").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                  encoding="utf-8")
    print(f"\n证据：{EVID / 'router-wiring.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
