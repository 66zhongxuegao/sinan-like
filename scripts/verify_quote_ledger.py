"""标准案例（S22）报价落库闭环验证：资源口径成本必须按**完整**成本算，不是只算问到的那一类。

缺陷（Codex 从标准案例 23-S22.json 读出）：
  地接/酒店/票务的询价在对话里有证据，但 `store.quotations(order_id)` 只有 `车队` 一类，
  于是 12690 的收入只减了 车队 4250 + 保险 120 = 4370 → 毛利 66%（真实财务错误）。

本脚本复现标准案例的询价动作（同一句群消息 + 单聊 + 工具箱），然后断言：
  ① 四类报价（地接社/酒店/车队/票务）全部落库，且字段齐全（kind/items/summary/可用性/价格因子）；
  ② 重复询价幂等：同一 (order_id, kind) 不新增行、summary 不变；
  ③ 跨单不串：另一张单的报价不受影响；
  ④ `finance.baseline_cost()` 明细包含住宿/用车/导游/门票（地接组合）或分项，毛利按完整成本算。

用法（仓库根目录）：python scripts/verify_quote_ledger.py
证据落盘：output/acceptance/evidence/conv-quote-ledger.md
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
os.environ["TRIPCRAFT_DB"] = str(_DB_DIR / f"ledger-{uuid.uuid4().hex[:8]}.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

from tripcraft.api.app import create_app  # noqa: E402

PASSWORD = "Test1234!"
FAILURES: list[str] = []
EVIDENCE: list[str] = []

# 标准案例的同一句话（取自 15-S14 / 22-S21 的真实请求体）
CASE_HUB_MSG = "请把车型、座位、日价、含不含司机与油费，以及今天几点前能给准信，一次发我。"


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

    username = f"led{uuid.uuid4().hex[:8]}"
    assert client.post("/auth/register", json={"username": username,
                                               "password": PASSWORD}).status_code in (200, 201)
    login = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()
    uid, token = login["user_id"], login["token"]
    H = {"Authorization": f"Bearer {token}"}

    # 标准案例口径：云南 / 4 人 / 5 天（见 23-S22.json：people=4 days=5 rooms=2）
    order_a = "9000000000000501"
    ctx.store.upsert_order(order_a, uid, "黄先生", "云南", "正常", 2, payload={
        "source_market": "香港", "language": "中文", "party": "4 人", "days": "5 天",
        "documents": "回乡证", "budget": "人均 3000",
    })
    order_b = "9000000000000502"          # 跨单对照
    ctx.store.upsert_order(order_b, uid, "对照组", "江苏", "正常", 2, payload={
        "source_market": "香港", "language": "中文", "party": "2 人", "days": "3 天",
    })
    ctx.practice.record_action(order_a, "grab")
    ctx.practice.record_action(order_b, "grab")
    for oid in (order_a, order_b):
        for kind in ("地接社", "酒店", "车队", "票务"):
            try:
                ctx.get_supplier().add_contact(oid, kind)
            except Exception as exc:      # noqa: BLE001
                print(f"  （{oid} 跳过加联系人 {kind}: {exc}）")

    out("# 标准案例 S22：询价落库闭环（资源口径成本必须完整）")
    out("")
    out(f"- 订单 A（标准案例口径）：{order_a}　云南 · 4 人 · 5 天")
    out(f"- 订单 B（跨单对照）：{order_b}　江苏 · 2 人 · 3 天")
    out("- 链路：HTTP 群消息 / 单聊 / 工具箱 → SupplierService.respond|ask → build_quote → supplier_quote")
    out("")

    hub = ctx.get_supplier().ensure_hub(uid)["session_id"]

    # ---- 1. 复现标准案例的群内询价 ----
    out("## 1. 复现标准案例的群内询价（同一句话）")
    r = client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                    json={"sender": "我", "role": "me", "order_id": order_a,
                          "content": CASE_HUB_MSG})
    body = r.json() if r.status_code == 200 else {}
    reply = body.get("reply") or {}
    out(f"- HTTP {r.status_code}；回话人={reply.get('sender')!r}；deferred={reply.get('deferred')}")
    out(f"- 回复内容：{str(reply.get('content'))[:160]}")
    quotes = ctx.store.quotations(order_a)
    out(f"- 落库 kinds = {sorted(quotes)}")
    check("群内询价后四类报价全部落库",
          set(quotes) == {"地接社", "票务", "酒店", "车队"}, f"{sorted(quotes)}")

    # ---- 2. 单聊 + 工具箱两条渠道 ----
    out("")
    out("## 2. 单聊与工具箱渠道")
    dm = ctx.get_supplier().contact_dm(uid, "酒店", order_a)
    if dm:
        r = client.post(f"/practice/im/sessions/{dm}/messages", headers=H,
                        json={"sender": "我", "role": "me", "order_id": order_a,
                              "content": "四星酒店这档什么价？有没有房？"})
        out(f"- 酒店单聊 HTTP {r.status_code}")
    r = client.post("/tools/supplier", headers=H,
                    json={"kind": "票务", "request": "高铁二等座什么价", "order_id": order_a})
    out(f"- 工具箱询价（票务）HTTP {r.status_code}：{str(r.json().get('reply'))[:120]}")
    quote_fields = ("kind", "items", "summary", "availability", "price_factor")
    missing_fields = {k: [f for f in quote_fields if f not in (q or {})]
                      for k, q in ctx.store.quotations(order_a).items()}
    check("每条报价字段齐全（kind/items/summary/availability/price_factor）",
          not any(missing_fields.values()), f"{ {k: v for k, v in missing_fields.items() if v} }")
    check("工具箱询价也落库（票务仍在）", "票务" in ctx.store.quotations(order_a))

    # ---- 3. 幂等：重复询价不新增行、不改数字 ----
    out("")
    out("## 3. 幂等（同一 order+kind 重复询价）")
    before = {k: (v.get("summary"), v.get("state_key")) for k, v in ctx.store.quotations(order_a).items()}
    rows_before = len(ctx.store._all("SELECT * FROM supplier_quote WHERE order_id=?", (order_a,)))
    for _ in range(3):
        client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                    json={"sender": "我", "role": "me", "order_id": order_a,
                          "content": CASE_HUB_MSG})
    after = {k: (v.get("summary"), v.get("state_key")) for k, v in ctx.store.quotations(order_a).items()}
    rows_after = len(ctx.store._all("SELECT * FROM supplier_quote WHERE order_id=?", (order_a,)))
    out(f"- 行数 {rows_before} → {rows_after}；kinds={sorted(after)}")
    check("重复询价不新增报价行", rows_before == rows_after, f"{rows_before} → {rows_after}")
    check("重复询价 summary/state_key 不变（同口径复用）", before == after,
          f"before={before}\nafter={after}")

    # ---- 4. 跨单不串 ----
    out("")
    out("## 4. 跨单不串")
    quotes_b = ctx.store.quotations(order_b)
    out(f"- 订单 B 落库 kinds = {sorted(quotes_b)}（未询价 → 应为空）")
    check("订单 A 的询价没有写进订单 B", not quotes_b, f"{sorted(quotes_b)}")
    # B 单独问一次，再看两边各自口径
    hub_b_msg = "酒店四星什么价？"
    client.post(f"/practice/im/sessions/{hub}/messages", headers=H,
                json={"sender": "我", "role": "me", "order_id": order_b, "content": hub_b_msg})
    qa = ctx.store.quotations(order_a)
    qb = ctx.store.quotations(order_b)
    out(f"- 订单 A kinds={sorted(qa)}；订单 B kinds={sorted(qb)}")
    check("向 B 询价不会改写 A 的报价",
          all(qa[k]["summary"] == before[k][0] for k in qa))
    check("B 拿到了自己的报价（地接社组合 summary 含江苏/南京口径）",
          "地接社" in qb and qb["地接社"]["city"] != qa["地接社"]["city"],
          f"A.city={qa['地接社'].get('city')} B.city={qb['地接社'].get('city')}")

    # ---- 5. 结算口径：baseline_cost + summary ----
    out("")
    out("## 5. 结算口径（finance.baseline_cost / summary）")
    base = ctx.get_finance().baseline_cost(order_a)
    out(f"- cost_source = {base['source']}")
    out(f"- cost_items = {json.dumps(base['items'], ensure_ascii=False)}")
    out(f"- cost_total = {base['total']}　people={base['people']} days={base['days']} rooms={base['rooms']}")
    names = [i["name"] for i in base["items"]]
    check("成本明细含住宿/用车/导游/门票（完整口径，不再只有用车）",
          any("住宿" in n for n in names) and any("用车" in n for n in names)
          and any("导游" in n for n in names) and any("门票" in n for n in names),
          f"{names}")
    # 收入：标准案例的客户确认分项报价总额 12690 → 用 revenue 台账复算毛利
    ctx.get_finance().add_entry(order_a, "REV-STD-CASE", "客户确认分项报价总额", 12690,
                                category="revenue")
    summary = ctx.get_finance().summary(order_a)
    out(f"- summary = {json.dumps({k: summary[k] for k in ('revenue','cost','loss','profit','margin','grade')}, ensure_ascii=False)}")
    out(f"- cost_items = {json.dumps(summary['cost_items'], ensure_ascii=False)}")
    check("毛利 = 收入 − 完整成本 − 损失",
          abs(round(summary["revenue"] - summary["cost"] - summary["loss"], 2)
              - summary["profit"]) < 0.01,
          f"revenue={summary['revenue']} cost={summary['cost']} loss={summary['loss']} profit={summary['profit']}")
    check("成本显著高于「只有车队」的口径（不再虚高毛利）",
          summary["cost"] > 4370 * 1.5, f"cost={summary['cost']}")

    out("")
    out("## 结论")
    if FAILURES:
        out(f"- FAIL: {len(FAILURES)} 项未通过")
        for f in FAILURES:
            out(f"  - {f}")
    else:
        out("- PASS：四类报价全部落库、字段齐全、幂等、跨单不串；结算按完整成本复算毛利。")
    out("")
    section_incident(ctx, uid, order_a)
    out("")
    if FAILURES:
        out(f"- 复核后 FAIL: {len(FAILURES)} 项未通过")
    else:
        out("- 复核后仍全部 PASS")

    target = ROOT / "output" / "acceptance" / "evidence" / "conv-quote-ledger.md"
    target.write_text("\n".join(EVIDENCE) + "\n", encoding="utf-8")
    print(f"\n证据已落盘: {target}")
    return 1 if FAILURES else 0


def section_incident(ctx, uid: str, order_id: str) -> None:
    """案例注入的固定资源约束 / 事件 effect 也必须落成结构化报价。

    同时回答 Lead 的问题：`director.emit('plan_sent')` 返回 injected:null 是不是
    「同一处漏落账」——不是。`_decide` 的门控是：配额 / 技能未解锁（teach<60）/
    该事件要求的沟通群不存在；三者都不满足时本就**不该**注入，与报价落库无关。
    """
    from tripcraft.services.director_service import INCIDENT_RULES

    out("## 6. 事件 effect / 案例注入的资源约束是否落账（兼答 injected:null）")
    # 先说明门控：把该事件涉及的技能点教学掌握度提到解锁线，并确认渠道群存在
    rule = next((r for r in INCIDENT_RULES if r["code"] == "INC-RESOURCE-UNAVAILABLE"), None)
    if rule is None:
        out("- 未找到 INC-RESOURCE-UNAVAILABLE 规则，跳过（不虚构结论）")
        return
    for sp in rule["skill_points"]:
        ctx.store.set_ability(uid, sp, teach=70)
    channel_ok = bool(ctx.get_supplier().group_by_name(order_id, rule["channel"]))
    out(f"- 规则 {rule['code']} 渠道={rule['channel']!r} 当前存在={channel_ok}；"
        f"技能点解锁={list(rule['skill_points'])}（teach=70）")
    check("该事件要求的沟通群存在（否则 injected 必然为 null，与报价无关）", channel_ok)

    before_quote = ctx.store.quote(order_id, "酒店") or {}
    fired = ctx.get_director().emit(order_id, "plan_sent")
    injected = fired.get("injected")
    out(f"- director.emit('plan_sent') → injected={json.dumps(injected, ensure_ascii=False)[:160] if injected else None}")
    check("门控满足后事件确实注入（证明 injected:null 是门控，不是漏落账）",
          bool(injected), f"{injected}")

    after_quote = ctx.store.quote(order_id, "酒店") or {}
    out(f"- 酒店报价 note：改前 {before_quote.get('note')!r} → 改后 {after_quote.get('note')!r}")
    out(f"- 酒店报价 state_key：{after_quote.get('state_key')}")
    check("事件 effect 落成结构化报价（supplier_quote 里看得到注入的约束）",
          bool(after_quote) and after_quote.get("note") != before_quote.get("note")
          and "满房" in str(after_quote.get("note")), f"{after_quote.get('note')}")
    entries = [e for e in ctx.get_finance().entries(order_id) if e.get("supplier_kind") == "酒店"]
    out(f"- 酒店类损失台账项：{[(e['code'], e['amount'], e['status']) for e in entries]}")
    base = ctx.get_finance().baseline_cost(order_id)
    out(f"- baseline_cost 仍按完整口径：{base['total']}（{base['source']}）")


if __name__ == "__main__":
    raise SystemExit(main())
