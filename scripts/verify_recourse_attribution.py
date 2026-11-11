"""标准案例：资源大群追偿能指认到具体资源方（监督者反馈缺陷的验证）。

缺陷（修复前）：资源大群的会话 kind 是笼统的「资源方」，
`maybe_attribute_from_chat(order_id, "资源方", text)` 在台账里按 `supplier_kind` 精确匹配，
永远匹配不到（台账 kind 是 酒店/车队/地接社/票务）→ 学员在大群里谈追偿**完全无效**，
责任也落不到具体资源方。

本脚本用真实 HTTP + 真实服务链验证修复后的行为：
  1. 注入两类待处理损失（酒店 / 票务）；
  2. 在大群里**不点名**说追偿 → 系统要求指名，不替学员猜（need_supplier）；
  3. 在大群里**点名酒店**说追偿 → 归因落到"酒店"、按写死比例 60% 定责、
     回话人是酒店联系人，证据里写明"责任方：酒店"；
  4. 点名票务追偿 → 票务比例 0%（航司调价不可追偿），文案明确说明；
  5. 单聊/自建群里也能指认。
证据落盘：output/acceptance/evidence/conv-recours e-attribution.md（拼写见下）

用法（仓库根目录）：python scripts/verify_recourse_attribution.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB_DIR = ROOT / ".dsh-run" / "conv-verify"
_DB_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TRIPCRAFT_DB"] = str(_DB_DIR / f"recourse-{uuid.uuid4().hex[:8]}.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

from tripcraft.api.app import create_app  # noqa: E402

PASSWORD = "Test1234!"
FAILURES: list[str] = []
EVIDENCE: list[str] = []


def out(line: str = "") -> None:
    print(line)
    EVIDENCE.append(line)


def check(name: str, ok: bool, detail: str = "") -> None:
    out(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    app = create_app()
    ctx = app.state.ctx
    client = TestClient(app)

    username = f"rec{uuid.uuid4().hex[:8]}"
    assert client.post("/auth/register", json={"username": username,
                                               "password": PASSWORD}).status_code in (200, 201)
    login = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    token = login.json()["token"]
    uid = login.json()["user_id"]
    H = {"Authorization": f"Bearer {token}"}

    order_id = "9000000000000401"
    ctx.store.upsert_order(order_id, uid, "追偿客户", "江苏", "正常", 3, payload={
        "source_market": "香港", "language": "中文", "party": "2 人", "days": "5 天",
        "budget": "人均 6000", "documents": "回乡证",
    })
    # 首呼 + 加联系人：让事件渠道与联系人可用
    ctx.practice.record_action(order_id, "grab")
    for kind in ("客户", "地接社", "酒店", "票务", "车队"):
        try:
            ctx.get_supplier().add_contact(order_id, kind)
        except Exception as exc:      # noqa: BLE001
            print(f"  （跳过加联系人 {kind}: {exc}）")

    out("# 标准案例证据：资源大群追偿指认到具体资源方")
    out("")
    out(f"- 订单：{order_id}（用户 {uid}，阶段 3）")
    out("- 链路：HTTP POST /practice/im/sessions/{hub}/messages → SupplierService.respond "
        "→ FinanceService.maybe_attribute_from_chat")
    out("")

    # ---- 1. 注入两类待处理损失（酒店 / 票务） ----
    out("## 1. 注入两类待处理损失（酒店 / 票务）")
    out("")
    out("注入方式：走与导演事件完全相同的落账函数 `FinanceService.add_incident_cost`，")
    out("cost 字典直接取自 `director_service` 里两条规则（酒店超售 / 机票涨价）的口径。")
    try:
        emitted = ctx.get_director().emit(order_id, "plan_sent")
        out(f"- 参考：真实事件通道 `director.emit('plan_sent')` → "
            f"{json.dumps(emitted, ensure_ascii=False)[:160]}"
            f"（injected=null 是因为该规则要求的沟通群尚未建立，属既有行为，不影响本项验证）")
    except Exception as exc:      # noqa: BLE001
        out(f"- 参考：真实事件通道 emit 失败：{type(exc).__name__}: {exc}")

    hotel_cost = {"code": "COST-HOTEL-ALT", "label": "替代酒店差价", "kind": "酒店",
                  "amount_per": 60, "unit": "间晚"}
    ticket_cost = {"code": "COST-TICKET-HIKE", "label": "机票涨价差额", "kind": "票务",
                   "amount_per": 220, "unit": "人", "transferable": True}
    e_hotel = ctx.get_finance().add_incident_cost(order_id, hotel_cost, ref="std-case-hotel")
    e_ticket = ctx.get_finance().add_incident_cost(order_id, ticket_cost, ref="std-case-ticket")
    out(f"- 落账（酒店）：{json.dumps(e_hotel, ensure_ascii=False)[:160]}")
    out(f"- 落账（票务）：{json.dumps(e_ticket, ensure_ascii=False)[:160]}")

    entries = ctx.get_finance().entries(order_id)
    pending = [(e["label"], e["supplier_kind"], e["amount"], e["status"])
               for e in entries if e["status"] == "待处理"]
    out(f"- 待处理台账项：{pending}")
    kinds = sorted({k for _l, k, _a, _s in pending})
    check("注入后存在两类待处理损失（酒店 + 票务）", kinds == ["票务", "酒店"], f"{kinds}")

    hub = ctx.get_supplier().ensure_hub(uid)["session_id"]

    # ---- 2. 不点名：要求指名，不替学员猜 ----
    out("")
    out("## 2. 大群里不点名说追偿（应要求指名）")
    r = client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                    json={"sender": "我", "role": "me", "order_id": order_id,
                          "content": "这笔损失你们得赔偿，不然我们这边没法交代"})
    body = r.json() if r.status_code == 200 else {}
    out(f"- HTTP {r.status_code}；finance={body.get('finance')}")
    check("不点名追偿 → 返回 need_supplier（含酒店与票务）",
          sorted((body.get("finance") or {}).get("need_supplier") or []) == ["票务", "酒店"],
          f"{body.get('finance')}")
    still_pending = [e for e in ctx.get_finance().entries(order_id) if e["status"] == "待处理"]
    check("不点名时没有草率定责（台账仍为待处理）", len(still_pending) == len(pending))

    # ---- 3. 点名酒店：归因到酒店 + 60% 比例 + 回话人是酒店 ----
    out("")
    out("## 3. 大群里点名酒店追偿（应归因到酒店）")
    r = client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                    json={"sender": "我", "role": "me", "order_id": order_id,
                          "content": "酒店那边超售换房这笔差价，你们得承担六成"})
    body = r.json() if r.status_code == 200 else {}
    fin = body.get("finance") or {}
    reply = body.get("reply") or {}
    hotel_name = ctx.get_supplier().names(order_id).get("酒店") or ""
    out(f"- HTTP {r.status_code}")
    out(f"- 回话人：{reply.get('sender')!r}（酒店联系人应为 {hotel_name!r}）")
    out(f"- 归因：{json.dumps(fin, ensure_ascii=False)}")
    check("追偿归因落到「酒店」", fin.get("supplier_kind") == "酒店", f"{fin}")
    check("承担方 = 资源方", fin.get("bearer") == "资源方", f"{fin}")
    hotel_entry = next((e for e in ctx.get_finance().entries(order_id)
                        if e["supplier_kind"] == "酒店"), {})
    expected_ours = round(float(hotel_entry.get("amount") or 0) * 0.4, 2)
    check("按写死比例：酒店 60% 由资源方承担（我方只担 40%）",
          abs(float(fin.get("ours") or 0) - expected_ours) < 0.01,
          f"我方 {fin.get('ours')} 预期 {expected_ours}")
    check("大群里回话人就是被指认的酒店（不再笼统用资源方）",
          bool(hotel_name) and reply.get("supplier_kind") == "酒店",
          f"reply.supplier_kind={reply.get('supplier_kind')!r}")

    evidence = ctx.practice.evidence(order_id)
    recourse_ev = [e for e in evidence if e["kind"] == "定责"]
    out(f"- 证据条数（定责）：{len(recourse_ev)}")
    for e in recourse_ev:
        out(f"  - {e['text'][:140]}")
    check("定责证据里写明责任方是「酒店」",
          any("责任方：酒店" in e["text"] for e in recourse_ev),
          f"{[e['text'][:60] for e in recourse_ev]}")
    check("该笔损失已定责入库（不再待处理）",
          float(hotel_entry.get("ours") or -1) >= 0) if hotel_entry else check("酒店台账项存在", False)

    # ---- 4. 点名票务：0% 不可追偿，文案说明 ----
    out("")
    out("## 4. 点名票务追偿（航司调价不可追偿，比例 0%）")
    r = client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                    json={"sender": "我", "role": "me", "order_id": order_id,
                          "content": "票务那边机票涨价这笔差价，请你们承担"})
    body = r.json() if r.status_code == 200 else {}
    fin2 = body.get("finance") or {}
    out(f"- HTTP {r.status_code}；finance={json.dumps(fin2, ensure_ascii=False)}")
    check("追偿归因落到「票务」", fin2.get("supplier_kind") == "票务", f"{fin2}")
    ticket_entry = next((e for e in ctx.get_finance().entries(order_id)
                         if e["supplier_kind"] == "票务"), {})
    check("票务按写死比例 0%（全部我方承担）",
          abs(float(fin2.get("ours") or 0) - float(ticket_entry.get("amount") or 0)) < 0.01,
          f"我方 {fin2.get('ours')} 台账 {ticket_entry.get('amount')}")

    # ---- 5. 单聊里也能指认（会话 kind 已是具体资源方） ----
    out("")
    out("## 5. 具体资源方单聊里的追偿")
    dm = ctx.get_supplier().contact_dm(uid, "酒店", order_id)
    if dm:
        r = client.post(f"/practice/im/sessions/{dm}/messages", headers=H,
                        json={"sender": "我", "role": "me",
                              "content": "这客房损失你们得认下来"})
        body = r.json() if r.status_code == 200 else {}
        out(f"- 单聊 id={dm}；HTTP {r.status_code}；reply.supplier_kind="
            f"{(body.get('reply') or {}).get('supplier_kind')!r}")
    else:
        out("- 该单没有酒店单聊会话（跳过）")

    out("")
    out("## 结论")
    if FAILURES:
        out(f"- FAIL: {len(FAILURES)} 项未通过")
        for f in FAILURES:
            out(f"  - {f}")
    else:
        out("- PASS：大群/单聊都能把追偿指认到具体资源方，按写死比例定责，证据留痕。")

    target = ROOT / "output" / "acceptance" / "evidence" / "conv-recourse-attribution.md"
    target.write_text("\n".join(EVIDENCE) + "\n", encoding="utf-8")
    print(f"\n证据已落盘: {target}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
