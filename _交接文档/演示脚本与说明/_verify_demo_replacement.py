#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""定向自检：「演示实例把随机游客替换成固定标准案例」+「普通实例不受影响」。

用法：python -X utf8 output/demo-rehearsal-20261017/_verify_demo_replacement.py

覆盖（都在独立临时库里跑，不碰 .dsh-run 与现场账号）：
  普通实例（不设开关）：
    1. 注册初始单是随机游客（不是黄先生、payload 无 scenario_id）
    2. POST /practice/dispatch/generate 仍是随机游客
    3. 内部演示路由被拒：import → 403 / provider/offline → 409（不得偷偷切演示）
    4. GET /scenario/status 如实报 demo_instance.enabled=false
  演示实例（TRIPCRAFT_SCENARIO_MODE=offline + TRIPCRAFT_DEMO_TOURIST=on）：
    5. 注册初始单被替换成固定黄先生（含资源约束），且带 scenario_id
    6. 再次 dispatch 幂等复用同一单，不重复建单
    7. 首呼台词与固定题卡不脱节（opening=案例第 1 句；学员第 1 句后=案例第 2 句）
  前端（静态）：
    8. 公开界面（App 导航 / 登录 / 注册 / 首页）不再有标准案例入口
    9. 内部排查页 /demo 有实例门禁
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CASE_FILE = ROOT / "data" / "scenario" / "standard_case.json"
CASE = json.loads(CASE_FILE.read_text(encoding="utf-8"))["cases"][0]
CASE_ID = CASE["case_id"]
FIXED_CUSTOMER = CASE["tourist"]["customer"]
FIXED_MARKET = CASE["tourist"]["source_market"]
OPENING = CASE["first_call"]["customer_lines"][0]
AFTER_FIRST = CASE["first_call"]["customer_lines"][1]

RESULTS: list[tuple[bool, str, dict]] = []


def check(name: str, ok: bool, detail: dict | None = None) -> None:
    RESULTS.append((bool(ok), name, detail or {}))
    print(f"  [{'OK' if ok else 'NG'}] {name}" + (f"  {json.dumps(detail, ensure_ascii=False)[:160]}" if detail else ""))


def fresh_env(db_name: str) -> str:
    db = Path(tempfile.gettempdir()) / db_name
    if db.exists():
        db.unlink()
    os.environ["TRIPCRAFT_DB"] = str(db)
    os.environ["SERVE_WEB"] = "0"
    os.environ["TRIPCRAFT_AUTH"] = "on"
    os.environ["TRIPCRAFT_BOOTSTRAP_ORDERS"] = "1"
    os.environ.pop("TRIPCRAFT_SCENARIO_TOGGLE", None)
    return str(db)


def make_app():
    """每次按当前环境变量新建一个 app 实例（等价于一次进程启动）。"""
    from tripcraft.api.app import create_app
    return create_app()


def register(client, username: str) -> dict:
    r = client.post("/auth/register", json={"username": username, "password": "LvyuanDemo#2026"})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    return r.json()


def main() -> int:
    from fastapi.testclient import TestClient

    # ---------------- 普通实例 ----------------
    print("\n== 普通实例（默认：不设演示开关） ==")
    fresh_env("tripcraft_demo_replace_normal.sqlite")
    os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)
    os.environ.pop("TRIPCRAFT_DEMO_TOURIST", None)
    os.environ.pop("TRIPCRAFT_DEMO_CASE", None)
    app = make_app()
    c = TestClient(app)
    reg = register(c, "normal-check-01")
    uid = reg["user_id"]
    boot = reg.get("bootstrap") or {}
    orders = boot.get("orders") or []
    check("普通实例注册初始单已生成（随机来源）", bool(orders) and not boot.get("replaced_random_tourist"),
          {"bootstrap": {k: v for k, v in boot.items() if k != "orders"}})
    oid = orders[0] if orders else ""
    if oid:
        od = c.get(f"/practice/orders/{oid}").json()
        payload = od.get("payload") or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        check("普通实例初始单不是固定黄先生、也没有案例标记",
              str(od.get("customer") or "") != FIXED_CUSTOMER and not payload.get("scenario_id"),
              {"customer": od.get("customer"), "scenario_id": payload.get("scenario_id")})

    r = c.post("/practice/dispatch/generate", json={"user_id": uid, "count": 1})
    check("普通实例 /practice/dispatch/generate 返回 200 且仍是随机来源",
          r.status_code == 200 and not (r.json().get("replaced")),
          {"status": r.status_code, "replaced": r.json().get("replaced") if r.status_code == 200 else None})

    r = c.post(f"/scenario/cases/{CASE_ID}/import", json={})
    check("普通实例调用内部导入被拒（403，不能偷偷切演示）", r.status_code == 403,
          {"status": r.status_code, "detail": str(r.json().get("detail"))[:90]})
    r = c.post("/scenario/provider/offline")
    check("普通实例运行期切模式被拒（409，须启动期声明）", r.status_code == 409,
          {"status": r.status_code})
    st = c.get("/scenario/status").json()
    di = st.get("demo_instance") or {}
    check("普通实例 status 如实报 demo_instance.enabled=false",
          (di.get("enabled") if isinstance(di, dict) else di) is False,
          {"demo_instance": di})

    # ---------------- 演示实例 ----------------
    print("\n== 演示实例（启动期显式开启固定案例替换） ==")
    fresh_env("tripcraft_demo_replace_demo.sqlite")
    os.environ["TRIPCRAFT_SCENARIO_MODE"] = "offline"
    os.environ["TRIPCRAFT_DEMO_TOURIST"] = "on"
    app2 = make_app()
    c2 = TestClient(app2)
    reg2 = register(c2, "demo-check-01")
    boot2 = reg2.get("bootstrap") or {}
    orders2 = boot2.get("orders") or []
    check("演示实例注册初始单被替换成固定案例（replaced_random_tourist=true）",
          bool(orders2) and boot2.get("replaced_random_tourist") is True and boot2.get("case_id") == CASE_ID,
          {"bootstrap": {k: v for k, v in boot2.items() if k != "orders"}})
    oid2 = orders2[0] if orders2 else ""
    if oid2:
        od2 = c2.get(f"/practice/orders/{oid2}").json()
        check("固定单的客人就是黄先生（不再随机）", str(od2.get("customer") or "") == FIXED_CUSTOMER,
              {"customer": od2.get("customer"), "destination": od2.get("destination"),
               "difficulty": od2.get("difficulty")})
        check("接单卡片字段不是「标准案例演示」口径（不显眼暴露内部身份）",
              "标准案例" not in str(od2.get("difficulty") or "")
              and "标准案例" not in str(od2.get("rationale") or ""),
              {"difficulty": od2.get("difficulty"), "rationale": str(od2.get("rationale"))[:70]})
        check("固定资料与案例一致（客源/语言来自案例）",
              od2.get("source_market") == FIXED_MARKET and bool(od2.get("language")),
              {"source_market": od2.get("source_market"), "language": od2.get("language")})
        cnt_before = c2.get(f"/scenario/account?case_id={CASE_ID}").json()
        r = c2.post("/practice/dispatch/generate", json={"user_id": reg2["user_id"], "count": 1})
        body = r.json()
        cnt_after = c2.get(f"/scenario/account?case_id={CASE_ID}").json()
        check("演示实例再次派单=幂等复用已有单（不新建订单）",
              body.get("reused") is True
              and cnt_after.get("scenario_orders") == cnt_before.get("scenario_orders")
              and (body.get("orders") or [""])[0] in (cnt_before.get("scenario_order_ids") or []),
              {"reused": body.get("reused"), "orders": body.get("orders"),
               "before": cnt_before.get("scenario_orders"), "after": cnt_after.get("scenario_orders"),
               "existing": cnt_before.get("scenario_order_ids")})
        # 资源约束：走案例导入回执（同一段注入逻辑）+ 直接读库核对已落库的资源状态
        imp = c2.post(f"/scenario/cases/{CASE_ID}/import", json={}).json()
        check("案例导入回执里有资源约束注入（不是空壳单）",
              len(imp.get("resources_injected") or []) >= 1,
              {"resources": [r.get("kind") for r in (imp.get("resources_injected") or [])]})
        import sqlite3
        con = sqlite3.connect(os.environ["TRIPCRAFT_DB"])
        try:
            rows = con.execute("SELECT kind FROM supplier_state WHERE user_id=?",
                               (reg2["user_id"],)).fetchall()
        except sqlite3.Error as exc:
            rows = [("__err__" + str(exc),)]
        finally:
            con.close()
        check("资源方状态已按案例写库（supplier_state 有该账号的记录）",
              len(rows) >= 1 and all("__err__" not in str(r[0]) for r in rows),
              {"kinds": [r[0] for r in rows]})

        c2.post(f"/practice/orders/{oid2}/grab", json={})
        snap = c2.post(f"/practice/orders/{oid2}/call", json={}).json()
        check("首呼与固定案例不脱节：opening = 案例第 1 句",
              (snap.get("lines") or [""])[-1] == OPENING or snap.get("opening") == OPENING
              or OPENING in json.dumps(snap, ensure_ascii=False),
              {"lines": snap.get("lines")})
        sid = snap.get("session_id")
        said = c2.post(f"/practice/call/{sid}/messages", json={"text": CASE["first_call"]["student_lines"][0]}).json()
        check("学员第 1 句后客户回案例第 2 句（题卡/台词不脱节）",
              said.get("reply") == AFTER_FIRST, {"reply": said.get("reply")})
    st2 = c2.get("/scenario/status").json()
    di2 = st2.get("demo_instance") or {}
    check("演示实例 status 报 demo_instance.enabled=true",
          isinstance(di2, dict) and di2.get("enabled") is True, {"demo_instance": di2})

    # ---------------- 学习等待超期：演示固定单仍可接（普通规则不变） ----------------
    print("\n== 学习等待超期（模拟 12 题 + C6.1 学习超过抢单窗口） ==")
    import sqlite3

    def _age_order(order_id: str, minutes: int, status: str | None = None) -> None:
        """把订单的 dispatch_at 拨回过去（并可选改状态），模拟长时间等待。"""
        con = sqlite3.connect(os.environ["TRIPCRAFT_DB"])
        try:
            row = con.execute("SELECT payload FROM biz_order WHERE order_id=?", (order_id,)).fetchone()
            payload = json.loads(row[0] or "{}")
            payload["dispatch_at"] = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
            if status:
                con.execute("UPDATE biz_order SET payload=?, status=? WHERE order_id=?",
                            (json.dumps(payload, ensure_ascii=False), status, order_id))
            else:
                con.execute("UPDATE biz_order SET payload=? WHERE order_id=?",
                            (json.dumps(payload, ensure_ascii=False), order_id))
            con.commit()
        finally:
            con.close()

    def _status_of(order_id: str) -> str:
        con = sqlite3.connect(os.environ["TRIPCRAFT_DB"])
        try:
            row = con.execute("SELECT status FROM biz_order WHERE order_id=?", (order_id,)).fetchone()
            return str(row[0]) if row else ""
        finally:
            con.close()

    # A) 未抢单的固定单：拨回 40 分钟前（远超 15 分钟窗口/竞争时点）仍要能接
    _reg_a = register(c2, "demo-age-01")
    oid_age = (_reg_a["bootstrap"]["orders"] or [""])[0]
    _age_order(oid_age, 40)
    avail = c2.get("/practice/orders/available").json()
    avail_ids = [o.get("order_id") for o in (avail if isinstance(avail, list) else avail.get("orders") or [])]
    check("演示实例：超期 40 分钟后固定单仍在消息中心可接（未判负）",
          oid_age in avail_ids, {"available": avail_ids[:5], "status": _status_of(oid_age)})
    grab2 = c2.post(f"/practice/orders/{oid_age}/grab", json={})
    check("演示实例：超期后仍能正常接单（黄先生那单）", grab2.status_code == 200,
          {"status": grab2.status_code})
    # 已抢单不得被续期改写：再拨回过去也不会复活成待接单
    _age_order(oid_age, 40)
    avail_after_grab = c2.get("/practice/orders/available").json()
    ids_after = [o.get("order_id") for o in (avail_after_grab if isinstance(avail_after_grab, list)
                                             else avail_after_grab.get("orders") or [])]
    check("演示实例：已抢单不回退为待接单（不复活已认领单）", oid_age not in ids_after,
          {"available": ids_after[:5]})

    # B) 已被判负（已派他人）的固定单：消息中心筛选前复活为可接
    _reg_b = register(c2, "demo-age-02")
    oid_lost = (_reg_b["bootstrap"]["orders"] or [""])[0]
    _age_order(oid_lost, 40, status="已派他人")
    avail3 = c2.get("/practice/orders/available").json()
    ids3 = [o.get("order_id") for o in (avail3 if isinstance(avail3, list) else avail3.get("orders") or [])]
    check("演示实例：已判负的固定单在消息中心被复活为可接", oid_lost in ids3,
          {"available": ids3[:5], "status": _status_of(oid_lost)})

    # 普通实例：同一个账号在**普通库**里，超期随机单照旧判负（竞争规则未被改动）
    print("\n== 普通实例对照：超期随机单照旧判负 ==")
    _normal_db = os.environ["TRIPCRAFT_DB"]
    fresh_env("tripcraft_demo_replace_normal_age.sqlite")
    os.environ.pop("TRIPCRAFT_SCENARIO_MODE", None)
    os.environ.pop("TRIPCRAFT_DEMO_TOURIST", None)
    c3 = TestClient(make_app())
    reg3 = register(c3, "normal-age-01")
    oid_n = (reg3["bootstrap"]["orders"] or [""])[0]
    _age_order(oid_n, 40)
    c3.get("/practice/orders/available")               # 触发惰性判负
    check("普通实例：超期随机单被判为丢单（规则保持原样）",
          _status_of(oid_n) == "已派他人", {"status": _status_of(oid_n)})
    avail_n = c3.get("/practice/orders/available").json()
    ids_n = [o.get("order_id") for o in (avail_n if isinstance(avail_n, list) else avail_n.get("orders") or [])]
    check("普通实例：被判负的单不再出现在可接列表", oid_n not in ids_n, {"available": ids_n[:5]})
    os.environ["TRIPCRAFT_DB"] = _normal_db

    # ---------------- 前端公开入口（静态） ----------------
    print("\n== 前端公开界面 ==")
    pub = {
        "App.vue": ROOT / "frontend/src/App.vue",
        "LoginView.vue": ROOT / "frontend/src/views/LoginView.vue",
        "RegisterView.vue": ROOT / "frontend/src/views/RegisterView.vue",
        "HomeView.vue": ROOT / "frontend/src/views/HomeView.vue",
    }
    import re as _re

    def _template_and_nav(path: Path) -> tuple[str, str]:
        """去掉注释，返回 (模板片段, 导航 groups 片段)：只看用户真能看到的字符串。"""
        body = path.read_text(encoding="utf-8")
        body = _re.sub(r"<!--.*?-->", "", body, flags=_re.S)
        body = _re.sub(r"/\*.*?\*/", "", body, flags=_re.S)
        body = _re.sub(r"^\s*//.*$", "", body, flags=_re.M)
        m_tpl = _re.search(r"<template>.*?</template>", body, _re.S)
        tpl = m_tpl.group(0) if m_tpl else ""
        nav = ""
        m = _re.search(r"const groups = \[.*?\n\]", body, _re.S)
        if m:
            nav = m.group(0)
        return tpl, nav

    hits = {}
    for name, path in pub.items():
        tpl, nav = _template_and_nav(path)
        found = [m for m in ("/demo", "标准案例", "标准案例演示") if m in tpl or m in nav]
        if found:
            hits[name] = found
    check("公开界面不再出现标准案例入口（App 导航 + 登录/注册/首页模板）",
          not hits, {"hits": hits})
    demo_view = (ROOT / "frontend/src/views/DemoCaseView.vue").read_text(encoding="utf-8")
    check("内部排查页 /demo 有实例门禁（普通实例访问直接回首页）",
          "demo_instance" in demo_view and "router.replace('/')" in demo_view, {})
    launcher = (ROOT / "scripts/desktop_launch.ps1").read_text(encoding="utf-8")
    bat = (ROOT / "司南礼客桌面版.bat").read_text(encoding="utf-8")
    check("普通入口 bat 固定指向 ASCII 脚本且传 -Mode Normal",
          "scripts\\desktop_launch.ps1" in bat and "-Mode Normal" in bat and "*.ps1" not in bat, {})
    check("演示分支才设 TRIPCRAFT_DEMO_TOURIST（普通分支显式清掉）",
          "TRIPCRAFT_DEMO_TOURIST = 'on'" in launcher
          and "Remove-Item Env:TRIPCRAFT_DEMO_TOURIST" in launcher, {})

    bad = [n for ok, n, _ in RESULTS if not ok]
    print("\n" + "=" * 68)
    print(f"结论：{'全部通过' if not bad else '存在失败'} · 断言 {len(RESULTS)} · 失败 {len(bad)}")
    if bad:
        for n in bad:
            print("  - " + n)
    print("=" * 68)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
