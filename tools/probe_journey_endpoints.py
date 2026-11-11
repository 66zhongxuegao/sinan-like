"""R01 运行期探测（一次性脚本，非产品代码）：用真实 HTTP 验证接口现状与字段形状。

用法：python tools/probe_journey_endpoints.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:18020"
DUMP_DIR = Path(os.environ.get("PROBE_DUMP_DIR", ""))


def call(method: str, path: str, body: dict | None = None, token: str = ""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def main() -> int:
    name = "probe" + uuid.uuid4().hex[:8]
    pw = "Probe1234!"
    st, reg = call("POST", "/auth/register", {"username": name, "password": pw, "display_name": name})
    print(f"[register] {st} user_id={(reg or {}).get('user_id')}")
    st, login = call("POST", "/auth/login", {"username": name, "password": pw})
    token = (login or {}).get("token", "") if st == 200 else ""
    print(f"[login]    {st} token={'yes' if token else 'no'}")
    if not token:
        return 1

    # 当前用户自己的订单（新账号没有单：走真实派单接口生成一张）
    uid = (reg or {}).get("user_id") or ""
    st, orders = call("GET", "/practice/orders?user_id=" + uid, token=token)
    rows = orders if isinstance(orders, list) else (orders or {}).get("orders", []) if st == 200 else []
    print(f"[orders]   {st} count={len(rows)}")
    if not rows:
        st, gen = call("POST", "/practice/dispatch/generate", {"user_id": uid, "count": 1}, token=token)
        created = (gen or {}).get("created") or [] if st == 200 else []
        print(f"[generate] {st} created={len(created)} " + json.dumps(created, ensure_ascii=False)[:200])
        st, orders = call("GET", "/practice/orders?user_id=" + uid, token=token)
        rows = orders if isinstance(orders, list) else (orders or {}).get("orders", [])
        if not rows and created:
            # 阶段 0 未抢的单不算「我的订单」，用 generate 返回的 order_id 继续探测
            st2, grabbed = call("POST", f"/practice/orders/{created[0]['order_id']}/grab", None, token=token)
            print(f"[grab]     {st2} " + json.dumps(grabbed, ensure_ascii=False)[:120])
            st, orders = call("GET", "/practice/orders?user_id=" + uid, token=token)
            rows = orders if isinstance(orders, list) else (orders or {}).get("orders", [])
        print(f"[orders]   重查 count={len(rows)}")
    oid = rows[0].get("order_id") if rows else ""
    if rows:
        print("           样例: " + json.dumps({k: rows[0].get(k) for k in
              ("order_id", "customer", "destination", "source_market", "language",
               "documents", "hint", "stage_name", "status")}, ensure_ascii=False))

    print("\n=== 前端订单详情页实际依赖的接口 ===")
    probes = [
        ("GET", "/practice/stages", None),
        ("GET", f"/practice/orders/{oid}/journey", None),
        ("GET", f"/practice/orders/{oid}", None),
        ("GET", f"/practice/orders/{oid}/deliverables", None),
        ("GET", f"/practice/orders/{oid}/gates", None),
        ("GET", f"/practice/orders/{oid}/contacts", None),
        ("GET", f"/practice/orders/{oid}/plans", None),
    ]
    detail = None
    journey = None
    delivs = None
    for method, path, body in probes:
        st, payload = call(method, path, body, token=token)
        keys = sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        print(f"{method:4} {path:56} -> {st}  keys={keys}")
        if path == f"/practice/orders/{oid}" and st == 200:
            detail = payload
        if path.endswith("/journey") and st == 200:
            journey = payload
        if path.endswith("/deliverables") and st == 200:
            delivs = payload

    if detail:
        print("\n=== 订单详情真实字段（前端去假数据后的数据来源） ===")
        print("documents      :", detail.get("documents"))
        print("source_market  :", detail.get("source_market"))
        print("language       :", detail.get("language"))
        print("hint           :", detail.get("hint"))
        print("contacts[0]    :", json.dumps((detail.get("contacts") or [{}])[0], ensure_ascii=False)[:200])
        print("steps[0]       :", json.dumps((detail.get("steps") or [{}])[0], ensure_ascii=False)[:200])
        print("step_keys      :", sorted((detail.get("steps") or [{}])[0].keys()))

    if journey:
        if DUMP_DIR:
            DUMP_DIR.mkdir(parents=True, exist_ok=True)
            out = DUMP_DIR / f"journey-{oid}.json"
            out.write_text(json.dumps(journey, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n[dump] journey 已落盘 {out}")
        print("\n=== journey 投影（OrderDetailView 阶段分区的数据源） ===")
        print("current_stage  :", journey.get("current_stage"), " index=", journey.get("current_stage_index"))
        print("next_action    :", json.dumps(journey.get("next_action"), ensure_ascii=False))
        print("stages[]       :")
        for s in journey.get("stages") or []:
            codes = [d.get("code") for d in (s.get("deliverables") or [])]
            print(f"  - {s.get('id'):18} state={s.get('state'):7} order={s.get('order')} "
                  f"docs={codes} {s.get('done_count')}/{s.get('total_count')}")
        print("documents[]    :", json.dumps(journey.get("documents"), ensure_ascii=False)[:300])

        # 前端契约断言（INTERFACE-v1 §2）
        bad = []
        if not isinstance(journey.get("stages"), list) or len(journey.get("stages")) != 6:
            bad.append("stages 不是 6 个")
        for s in journey.get("stages") or []:
            if s.get("state") not in ("done", "current", "todo"):
                bad.append(f"{s.get('id')} state 越界")
        na = journey.get("next_action")
        if na is not None:
            if not isinstance(na, dict) or "route" not in na or "label" not in na:
                bad.append("next_action 缺 route/label")
            elif not str(na["route"]).startswith("/"):
                bad.append("next_action.route 不是前端路径")
        print("契约断言       :", "全部通过" if not bad else "失败 -> " + "; ".join(bad))

    if delivs:
        rows = delivs.get("deliverables") or []
        print("\n=== deliverables（工作台与跳转 code 的口径） ===")
        print("deliverables[] :", json.dumps(rows, ensure_ascii=False)[:600])
        print("顶层 next_action:", json.dumps(delivs.get("next_action"), ensure_ascii=False)[:200])
        print("当前阶段文档   :", [r.get("code") for r in rows if r.get("in_current_stage")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
