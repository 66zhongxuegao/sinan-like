"""核对 FinanceView 的结算交付物定位与 contracts/stages.py 完全一致（一次性脚本）。

FinanceView 的做法：从 `GET /practice/stages` 里找出 deliverables 含 `settlement` 的阶段，
用它作为 `?code=settlement` 的可用性门。本脚本对照**契约本身**（deliverable_stage）核对：
  1) 前端取到的那条记录确实来自契约透传，且 stage_of_deliverable['settlement'] == 该阶段 id；
  2) 该阶段 id 在六个阶段里存在，且是唯一的（不会出现两个阶段都声明 settlement）。

用法：$env:PROBE_ORDER_ID="<已抢单的订单号>" python tools/probe_finance_settlement.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tripcraft.contracts.stages import STAGE_ORDER, as_payload, deliverable_stage  # noqa: E402

BASE = "http://127.0.0.1:18020"


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
        return e.code, e.read().decode()


def main() -> int:
    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        if not ok:
            fails += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  —  ' + detail if detail else ''}")

    name = "fin" + uuid.uuid4().hex[:8]
    pw = "Probe1234!"
    call("POST", "/auth/register", {"username": name, "password": pw, "display_name": name})
    st, login = call("POST", "/auth/login", {"username": name, "password": pw})
    token = (login or {}).get("token", "") if st == 200 else ""
    check("拿到登录 token", bool(token))
    if not token:
        return 1

    st, payload = call("GET", "/practice/stages", token=token)
    check("/practice/stages 可读", st == 200, f"http {st}")
    if st != 200:
        return 1

    contract = as_payload()
    check("接口透传的契约与本地 contracts 一致",
          payload == contract, f"接口 {len((payload or {}).get('stages') or [])} 阶段 / 本地 {len(contract['stages'])} 阶段")

    api_stages = {s["id"]: s for s in payload["stages"]}
    owners = [s["id"] for s in payload["stages"] if "settlement" in (s.get("deliverables") or [])]
    check("含 settlement 的阶段唯一", len(owners) == 1, f"owners={owners}")
    check("该阶段与 deliverable_stage('settlement') 一致",
          owners == [deliverable_stage("settlement")], f"{owners} vs {deliverable_stage('settlement')}")
    check("该阶段在六阶段顺序里", owners and owners[0] in STAGE_ORDER, str(STAGE_ORDER))
    check("接口里的 stage_of_deliverable 也指向同一阶段",
          (payload.get("stage_of_deliverable") or {}).get("settlement") == deliverable_stage("settlement"),
          str((payload.get("stage_of_deliverable") or {}).get("settlement")))
    if owners:
        print(f"  （附加信息）阶段 {owners[0]} 的接口定义：{json.dumps(api_stages[owners[0]], ensure_ascii=False)[:260]}")

    print(f"\n{'全部通过' if not fails else str(fails) + ' 项失败'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
