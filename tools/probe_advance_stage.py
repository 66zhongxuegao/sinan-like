"""把探测账号的一单推进到非首阶段，验证「当前阶段置顶」在真实数据下真有位移。

用法：python tools/probe_advance_stage.py
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
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def main() -> int:
    name = "stage" + uuid.uuid4().hex[:8]
    pw = "Probe1234!"
    st, reg = call("POST", "/auth/register", {"username": name, "password": pw, "display_name": name})
    uid = (reg or {}).get("user_id") or ""
    st, login = call("POST", "/auth/login", {"username": name, "password": pw})
    token = (login or {}).get("token", "")
    print(f"[auth] register={st} login={st} uid={uid}")

    st, gen = call("POST", "/practice/dispatch/generate", {"user_id": uid, "count": 1}, token=token)
    oid = ((gen or {}).get("created") or [{}])[0].get("order_id", "")
    print(f"[order] {oid}")

    # 先抢单，再逐个尝试动作；每步看平台状态与六阶段当前位置
    st, _ = call("POST", f"/practice/orders/{oid}/grab", None, token=token)
    st, acts = call("GET", f"/practice/orders/{oid}/actions", token=token)
    options = (acts or {}).get("manual_options") or []
    print(f"[actions] 可登记动作 {len(options)} 个")

    seen = set()
    for act in options:
        st, out = call("POST", f"/practice/orders/{oid}/actions", {"action": act}, token=token)
        st2, j = call("GET", f"/practice/orders/{oid}/journey", token=token)
        st3, d = call("GET", f"/practice/orders/{oid}", token=token)
        cur = (j or {}).get("current_stage", "?")
        na = ((j or {}).get("next_action") or {}).get("route", "-")
        print(f"  action={act:16} -> http {st} platform={((d or {}).get('stage_name') or '?')!r} "
              f"current_stage={cur} next={na}")
        if cur and cur not in seen:
            seen.add(cur)
            if DUMP_DIR and cur != "pre1_requirement":
                DUMP_DIR.mkdir(parents=True, exist_ok=True)
                p = DUMP_DIR / f"journey-advanced-{cur}.json"
                p.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"         [dump] {p}")
    print(f"[summary] 触及阶段 {sorted(seen)}")
    return 0 if len(seen) > 1 else 1


if __name__ == "__main__":
    sys.exit(main())
