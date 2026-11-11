"""把真实订单推进过「提交交付物 + 登记动作」两轮，抓非首阶段的 journey（一次性脚本）。

用途：验证订单详情页的「当前阶段置顶 / 继续按 next_action.route / 定位交付物 code」
在**真实响应**下（而不只是首阶段）也成立。落盘的 journey JSON 交给
`node --experimental-strip-types tools/verify_orderdetail_realdata.mts` 断言。

用法：
  $env:PROBE_DUMP_DIR="$env:TEMP\tc-journey-dump"; python tools/probe_advance_deliverables.py
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
REQUIRED_ACTIONS = ("确认联系", "confirm_contact", "首呼", "first_call")


def call(method: str, path: str, body: dict | None = None, token: str = ""):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def blank_values(spec: dict) -> dict:
    """按契约字段类型给出「结构正确但不写死业务内容」的值（只用于打通阶段流转）。"""
    out: dict = {}
    for f in spec.get("fields") or []:
        key, typ = f.get("key"), f.get("type") or "text"
        if not f.get("required"):
            if typ == "rows":
                out[key] = []
            continue
        if typ == "number":
            out[key] = 1000
        elif typ == "date":
            out[key] = "2026-11-01"
        elif typ == "select":
            out[key] = (f.get("options") or ["未选"])[0]
        elif typ == "rows":
            out[key] = []
        else:
            out[key] = f"探测填充（{key}）"
    return out


def dump_journey(tag: str, j: dict) -> None:
    if not DUMP_DIR:
        return
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    p = DUMP_DIR / f"journey-{tag}.json"
    p.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"         [dump] {p}")


def snapshot(oid: str, token: str, label: str) -> str:
    _, j = call("GET", f"/practice/orders/{oid}/journey", token=token)
    _, d = call("GET", f"/practice/orders/{oid}", token=token)
    cur = (j or {}).get("current_stage", "?")
    na = (j or {}).get("next_action") or {}
    print(f"  {label:34} platform={((d or {}).get('stage_name') or '?')!r} current={cur} "
          f"next={na.get('kind')}/{na.get('label')} -> {na.get('route')}")
    return cur


def main() -> int:
    name = "adv" + uuid.uuid4().hex[:8]
    pw = "Probe1234!"
    st, reg = call("POST", "/auth/register", {"username": name, "password": pw, "display_name": name})
    uid = (reg or {}).get("user_id") or ""
    st, login = call("POST", "/auth/login", {"username": name, "password": pw})
    token = (login or {}).get("token", "")
    if not token:
        print(f"[auth] register={st} login={st} -> 无 token，退出")
        return 1
    st, gen = call("POST", "/practice/dispatch/generate", {"user_id": uid, "count": 1}, token=token)
    oid = ((gen or {}).get("created") or [{}])[0].get("order_id", "")
    if not oid:
        print(f"[order] 派单失败 {st} {gen}")
        return 1
    print(f"[order] {oid} uid={uid}")
    print(f"[grab]  {call('POST', f'/practice/orders/{oid}/grab', None, token=token)[0]}")

    stages_seen: list[str] = []
    stages_seen.append(snapshot(oid, token, "grab 之后"))

    # 第 1 轮：提交当前阶段所有未投递交付物
    for _round in range(6):
        _, dl = call("GET", f"/practice/orders/{oid}/deliverables", token=token)
        pending = [d["code"] for d in (dl or {}).get("deliverables", []) if not d.get("submitted")]
        if not pending:
            print("  [submit] 没有待投递交付物")
            break
        code = pending[0]
        _, spec = call("GET", f"/practice/orders/{oid}/deliverables/{code}", token=token)
        values = blank_values(spec or {})
        st, out = call("POST", f"/practice/orders/{oid}/deliverables/{code}", {"values": values}, token=token)
        detail = "" if st == 200 else str(out)[:160]
        print(f"  [submit] {code:18} http {st} {detail}")
        if st != 200:
            break
        c = snapshot(oid, token, f"提交 {code} 之后")
        if c not in stages_seen:
            stages_seen.append(c)
            dump_journey(c, (call("GET", f"/practice/orders/{oid}/journey", token=token)[1]) or {})

    # 第 2 轮：逐个登记可用的手动动作（含首呼确认），直到不再跨阶段
    _, acts = call("GET", f"/practice/orders/{oid}/actions", token=token)
    options = [str(a) for a in ((acts or {}).get("manual_options") or [])]
    first = [a for a in options if any(k in a for k in REQUIRED_ACTIONS)]
    ordered = list(dict.fromkeys(first + options))
    print(f"[actions] 候选 {ordered}")
    for act in ordered:
        st, out = call("POST", f"/practice/orders/{oid}/actions", {"action": act}, token=token)
        c = snapshot(oid, token, f"动作 {act} 之后（http {st}）")
        if c not in stages_seen:
            stages_seen.append(c)
            dump_journey(c, (call("GET", f"/practice/orders/{oid}/journey", token=token)[1]) or {})

    print(f"[summary] 触及阶段 {stages_seen}")
    return 0 if len(stages_seen) > 1 else 1


if __name__ == "__main__":
    sys.exit(main())
