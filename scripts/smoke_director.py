"""导演总线 + 覆盖校验 + 低置信度升级 冒烟。

流程：学员动作 → 事件 → 注入突发事件（写进聊天群）→ 学员回话（覆盖 B 型）
      → 覆盖校验 → 评分 → 低置信度转人工。

用法：python -X utf8 scripts/smoke_director.py [order_id]
前置：后端已启动（127.0.0.1:18020）。
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:18020"


def call(method: str, path: str, body: dict | None = None, timeout: float = 240.0):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> int:
    order_id = sys.argv[1] if len(sys.argv) > 1 else "9000000000000004"

    print("== 1. 规则表 ==")
    cat = call("GET", "/practice/director/catalog")
    for r in cat["rules"]:
        print(f"   {r['code']:26} 触发={','.join(r['trigger']):20} 阶段>={r['stage_min']}  考={','.join(r['skill_points'])}")

    print("\n== 2. 学员动作 -> 事件 -> 注入 ==")
    for ev in ["grab_order", "call_done", "plan_sent", "quote_sent", "resource_locked"]:
        out = call("POST", f"/practice/orders/{order_id}/events", {"type": ev})
        inc = out.get("injected")
        if inc:
            print(f"   [{ev}] -> 注入 {inc['title']}（{inc['channel']} / {inc['speaker']}）")
            print(f"        {inc['body'][:78]}")
            print(f"        考 {','.join(inc['skill_points'])}  规则：{inc['rule']}")
        else:
            print(f"   [{ev}] -> 未注入（不满足规则）")

    print("\n== 3. 覆盖校验（学员还没回话）==")
    cov = call("GET", f"/practice/orders/{order_id}/coverage")
    print(f"   目标 {cov['targets']} 项，已覆盖 {cov['covered']}，覆盖度 {round(cov['ratio']*100)}% "
          f"（门槛 {round(cov['threshold']*100)}%，{'通过' if cov['passed'] else '未通过'}）")
    for it in cov["items"]:
        if not it["covered"]:
            print(f"   未覆盖 {it['skill_point_id']} {it['name']}（{it['checkpoint']}型）— {it['reason']}")

    print("\n== 4. 学员在群里回应（B 型考点算覆盖）==")
    sessions = call("GET", "/practice/im/sessions")
    target = None
    for s in sessions:
        if any("司导" in s["name"] or "供应商" in s["name"] or "客户服务" in s["name"] for _ in [0]):
            target = s
            break
    print("   会话：", [s["name"] for s in sessions])
    tls = call("GET", f"/practice/orders/{order_id}/timeline")
    for inc in tls["incidents"]:
        sid = urllib.parse.quote(inc["session_id"])
        replied = call("POST", f"/practice/im/sessions/{sid}/messages",
                       {"sender": "我", "role": "me",
                        "content": "收到，我马上去核实；先稳住客人，10 分钟内给你替代方案。"})
        print(f"   在「{inc['channel']}」回应 -> 覆盖 {','.join(replied['reacted']) or '（无）'}")

    print("\n== 5. 覆盖校验（回话后）==")
    cov = call("GET", f"/practice/orders/{order_id}/coverage")
    print(f"   目标 {cov['targets']} 项，已覆盖 {cov['covered']}，覆盖度 {round(cov['ratio']*100)}% "
          f"（{'通过' if cov['passed'] else '未通过'}）")

    print("\n== 6. 补交付物（A 型考点靠交付物覆盖）==")
    for kind, content in [
        ("需求确认单", "必须满足：3大 1 小、10月 20 日出发 5 天、住四星、不超预算；"
                          "希望满足：节奏不太赶、有一天自由活动；"
                          "可替代：酒店可降一档；明确不要：石林。"),
        ("行程方案", "D1 抵达昆明，入住市区四星；D2 大理古城+洱海环湖；"
                        "D3 丽江古城（自由活动）；D4 束河古镇；D5 返程。"
                        "全程 7 座商务车，含司导；已与地接确认房态与车档；"
                        "人均 5,400 元含高铁，疑难风险预留 300 元/人；"
                        "已备一套四星降级作为备选。"),
    ]:
        out = call("POST", "/tools/deliverable", {
            "kind": kind, "content": content, "customer": "客户", "order_id": order_id})
        print(f"   投递「{kind}」-> 客户：{out.get('reply', '')[:48]}")

    print("\n== 7. 覆盖校验（补齐交付物后）==")
    cov = call("GET", f"/practice/orders/{order_id}/coverage")
    print(f"   目标 {cov['targets']} 项，已覆盖 {cov['covered']}，覆盖度 {round(cov['ratio']*100)}% "
          f"（{'通过' if cov['passed'] else '未通过'}）")
    for it in cov["items"]:
        if not it["covered"]:
            print(f"   仍未覆盖 {it['skill_point_id']} {it['name']}（{it['checkpoint']}型）— {it['reason']}")

    print("\n== 8. 评分（含覆盖校验与低置信度升级）==")
    rep = call("POST", f"/practice/orders/{order_id}/score")
    c = rep["coverage"]
    print(f"   候选 {rep['candidates']} / 判出 {rep['scored']} / 写画像 {rep['written']} / 缺证据丢弃 {len(rep['dropped'])}")
    print(f"   覆盖 {c['covered']}/{c['targets']}（{round(c['ratio']*100)}%）"
          f"{'，通过' if c['passed'] else '，不通过 → 本次不写画像'}")
    if rep.get("deferred"):
        print("   deferred：", rep["deferred_reason"])
    if rep["escalated"]:
        print("   转人工复核：")
        for e in rep["escalated"]:
            print(f"     {e['skill_point_id']} {e['score']} {e['level']}（置信 {e['confidence']}）— {e['review_reason']}")
    else:
        print("   无低置信度判定")

    print("\n== 9. 人工复核（若有）==")
    for p in call("GET", f"/practice/orders/{order_id}/reviews"):
        out = call("POST", f"/practice/orders/{order_id}/reviews/{p['skill_point_id']}", {"decision": "accept"})
        print(f"   采纳 {out['skill_point_id']} -> 写画像={out['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())